#!/usr/bin/env python3
"""Associate slice-energy bunching with analytic horn length scales."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from scipy.stats import spearmanr
import yaml

from .export_horncad import (
    osse_radius, solved_s, termination_metrics, termination_unit,
)
from .webster_1d import AreaProfile, horncad_area_profile, solve_sweep


SOUND_SPEED_M_S = 343.21
RESAMPLE_POINTS_PER_OCTAVE = 48
SMOOTH_SIGMA_OCTAVES = 1.0 / 12.0
MINIMUM_PEAK_PROMINENCE_DB = 0.12
MINIMUM_PEAK_SPACING_OCTAVES = 1.0 / 6.0
MAXIMUM_MATCHED_SHIFT_OCTAVES = 0.75
MINIMUM_TRANSLATION_ALIGNMENT_GAIN = 0.10
CONTROLS = ("length_mm", "k", "n")


@dataclass(frozen=True)
class Observation:
    identifier: str
    report: str | None
    mouth_mm: float
    coverage_deg: float
    length_mm: float
    k: float
    n: float
    s: float
    frequencies_hz: np.ndarray
    departure_db: np.ndarray
    peaks: tuple[dict[str, float | bool], ...]
    troughs: tuple[dict[str, float | bool], ...]
    scales_mm: dict[str, float]
    webster: dict[str, float | None]

    @property
    def dominant_peak(self) -> dict[str, float | bool] | None:
        interior = [peak for peak in self.peaks if not peak["at_band_edge"]]
        return max(interior, key=lambda peak: float(peak["departure_db"]),
                   default=None)

    @property
    def dominant_trough(self) -> dict[str, float | bool] | None:
        interior = [trough for trough in self.troughs
                    if not trough["at_band_edge"]]
        return min(interior, key=lambda trough: float(trough["departure_db"]),
                   default=None)

    @property
    def frequency_spacings_hz(self) -> dict[str, float]:
        peak_frequencies = sorted(float(item["frequency_hz"]) for item in self.peaks
                                  if not item["at_band_edge"])
        trough_frequencies = sorted(float(item["frequency_hz"]) for item in self.troughs
                                    if not item["at_band_edge"])
        output: dict[str, float] = {}
        for name, frequencies in (
                ("peak_to_peak", peak_frequencies),
                ("trough_to_trough", trough_frequencies),
                ("adjacent_extrema", sorted(peak_frequencies + trough_frequencies))):
            if len(frequencies) >= 2:
                output[name] = float(np.median(np.diff(frequencies)))
        return output


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _log_grid(lower_hz: float, upper_hz: float) -> np.ndarray:
    octaves = math.log2(upper_hz / lower_hz)
    count = max(2, round(octaves * RESAMPLE_POINTS_PER_OCTAVE) + 1)
    return lower_hz * np.power(2.0, np.linspace(0.0, octaves, count))


def slice_energy_departure(
        frequencies_hz: np.ndarray, angles_deg: np.ndarray,
        levels_db: np.ndarray, lower_hz: float, upper_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a smoothed, log-frequency slice-energy departure curve."""
    frequencies = np.asarray(frequencies_hz, dtype=float)
    angles = np.asarray(angles_deg, dtype=float)
    levels = np.asarray(levels_db, dtype=float)
    order = np.argsort(frequencies)
    frequencies, levels = frequencies[order], levels[order]
    positive = (angles >= 0.0) & (angles <= 90.0)
    angles, levels = angles[positive], levels[:, positive]
    if len(angles) < 2 or angles[0] > 0.0 or angles[-1] < 90.0:
        raise ValueError("response angles must span 0 through 90 degrees")
    if lower_hz < frequencies[0] or upper_hz > frequencies[-1]:
        raise ValueError("diagnostic band lies outside retained response data")
    energy = 2.0 * np.trapezoid(np.power(10.0, levels / 10.0), angles, axis=1)
    if np.any(energy <= 0.0):
        raise ValueError("slice energy must be positive")
    target = _log_grid(lower_hz, upper_hz)
    log_energy = np.interp(np.log2(target), np.log2(frequencies), np.log(energy))
    departure = (10.0 / math.log(10.0)) * (log_energy - np.mean(log_energy))
    sigma = SMOOTH_SIGMA_OCTAVES * RESAMPLE_POINTS_PER_OCTAVE
    return target, gaussian_filter1d(departure, sigma=sigma, mode="nearest")


def _find_bunching_extrema(
        frequencies_hz: np.ndarray, departure_db: np.ndarray, sign: float,
) -> tuple[dict[str, float | bool], ...]:
    spacing = max(1, round(
        MINIMUM_PEAK_SPACING_OCTAVES * RESAMPLE_POINTS_PER_OCTAVE))
    transformed = sign * departure_db
    indices, properties = find_peaks(
        transformed, prominence=MINIMUM_PEAK_PROMINENCE_DB, distance=spacing)
    records = [{
        "frequency_hz": float(frequencies_hz[index]),
        "departure_db": float(departure_db[index]),
        "prominence_db": float(properties["prominences"][position]),
        "at_band_edge": False,
    } for position, index in enumerate(indices)]
    for index in (0, len(departure_db) - 1):
        neighbor = transformed[1] if index == 0 else transformed[-2]
        if transformed[index] > neighbor and transformed[index] > 0.0:
            records.append({
                "frequency_hz": float(frequencies_hz[index]),
                "departure_db": float(departure_db[index]),
                "prominence_db": float(abs(transformed[index] - neighbor)),
                "at_band_edge": True,
            })
    return tuple(sorted(records, key=lambda item: float(item["frequency_hz"])))


def find_bunching_peaks(frequencies_hz: np.ndarray,
                        departure_db: np.ndarray) -> tuple[dict[str, float | bool], ...]:
    """Find broad positive slice-energy departures on a uniform log grid."""
    return _find_bunching_extrema(frequencies_hz, departure_db, 1.0)


def find_bunching_troughs(frequencies_hz: np.ndarray,
                          departure_db: np.ndarray) -> tuple[dict[str, float | bool], ...]:
    """Find broad negative slice-energy departures on a uniform log grid."""
    return _find_bunching_extrema(frequencies_hz, departure_db, -1.0)


def _first_crossing(z: np.ndarray, values: np.ndarray, target: float) -> float:
    index = int(np.searchsorted(values, target, side="left"))
    if index <= 0:
        return float(z[0])
    if index >= len(z):
        return float(z[-1])
    fraction = (target - values[index - 1]) / max(
        values[index] - values[index - 1], 1e-12)
    return float(z[index - 1] + fraction * (z[index] - z[index - 1]))


def physical_scales(config: dict[str, Any]) -> dict[str, float]:
    """Measure predeclared axial, radial, path, and termination length scales."""
    global_config = config["global"]
    basis = config["horizontal_basis"]
    length = float(global_config["length"])
    mouth_radius = float(global_config["mouth_width"]) / 2.0
    authored_throat = float(global_config["throat_radius"])
    throat_angle = float(global_config.get("throat_angle_deg", 0.0))
    extension = max(0.0, float(global_config.get("conical_extension_length", 0.0)))
    effective_throat = authored_throat + extension * math.tan(math.radians(throat_angle))
    coverage = float(basis["coverage_deg"])
    k, n = float(basis["k"]), float(basis["n"])
    s = solved_s(length, effective_throat, coverage, k, n, mouth_radius,
                 throat_angle)
    z = np.linspace(0.0, length, 2049)
    radius = np.asarray([
        osse_radius(value, length, effective_throat, coverage, k, n, s,
                    throat_angle) for value in z
    ])
    slope = np.gradient(radius, z)
    curvature = np.abs(np.gradient(slope, z)) / np.power(1.0 + slope ** 2, 1.5)
    interior = slice(20, -20)
    curvature_index = int(np.argmax(curvature[interior])) + 20
    area_flare_rate = np.abs(2.0 * slope / np.maximum(radius, 1e-12))
    flare_index = int(np.argmax(area_flare_rate[interior])) + 20
    flare_length = 1.0 / max(float(area_flare_rate[flare_index]), 1e-12)
    mouth_zone = slice(round(0.8 * len(z)), -20)
    mouth_zone_flare_length = float(np.median(
        1.0 / np.maximum(area_flare_rate[mouth_zone], 1e-12)))
    rapid_flare_indices = np.flatnonzero(
        area_flare_rate >= 0.5 * area_flare_rate[flare_index])
    rapid_flare_zone = float(
        z[rapid_flare_indices[-1]] - z[rapid_flare_indices[0]])
    high_curvature_indices = np.flatnonzero(
        curvature >= 0.5 * curvature[curvature_index])
    high_curvature_zone = float(
        z[high_curvature_indices[-1]] - z[high_curvature_indices[0]])
    wall_path = float(np.trapezoid(np.sqrt(1.0 + slope ** 2), z))
    radial_fraction = (radius - radius[0]) / max(radius[-1] - radius[0], 1e-12)
    half_growth_z = _first_crossing(z, radial_fraction, 0.5)
    termination = np.asarray([
        termination_unit(value, length, 0.995, n) for value in z
    ])
    termination /= max(termination[-1], 1e-12)
    metrics = termination_metrics(
        length, effective_throat, coverage, k, n, mouth_radius, throat_angle)
    scales = {
        "osse_length": length,
        "mouth_width": 2.0 * mouth_radius,
        "mouth_radius": mouth_radius,
        "radial_growth": mouth_radius - effective_throat,
        "wall_path_length": wall_path,
        "half_radial_growth_from_throat": half_growth_z,
        "half_radial_growth_to_mouth": length - half_growth_z,
        "max_curvature_from_throat": float(z[curvature_index]),
        "max_curvature_to_mouth": float(length - z[curvature_index]),
        "diameter_at_max_curvature": float(2.0 * radius[curvature_index]),
        "mouth_curvature_radius": float(metrics["curvature_radius_mm"]),
        "minimum_area_flare_length": flare_length,
        "mouth_zone_median_area_flare_length": mouth_zone_flare_length,
        "max_area_flare_from_throat": float(z[flare_index]),
        "max_area_flare_to_mouth": float(length - z[flare_index]),
        "diameter_at_max_area_flare": float(2.0 * radius[flare_index]),
        "rapid_area_flare_zone_length": rapid_flare_zone,
        "minimum_curvature_radius": float(
            1.0 / max(curvature[curvature_index], 1e-12)),
        "high_curvature_zone_length": high_curvature_zone,
    }
    termination_positions = {}
    for fraction in (0.1, 0.5, 0.9):
        position = _first_crossing(z, termination, fraction)
        termination_positions[fraction] = position
        scales[f"termination_{round(100 * fraction):02d}_from_throat"] = position
        scales[f"termination_{round(100 * fraction):02d}_to_mouth"] = length - position
    scales["termination_10_90_transition_length"] = (
        termination_positions[0.9] - termination_positions[0.1])
    return {
        name: value for name, value in scales.items()
        if math.isfinite(value) and value > 0.1
    }


def _same_axes(config: dict[str, Any]) -> bool:
    g = config["global"]
    h, v = config["horizontal_basis"], config["vertical_basis"]
    return all(abs(float(left) - float(right)) < 1e-6 for left, right in (
        (g["mouth_width"], g["mouth_height"]),
        (h["coverage_deg"], v["coverage_deg"]),
        (h["k"], v["k"]), (h["n"], v["n"]),
    ))


def _nearest_extremum_octaves(
        feature: dict[str, float | bool] | None,
        extrema: tuple[dict[str, float | bool], ...],
) -> float | None:
    if feature is None:
        return None
    frequencies = [float(item["frequency_hz"]) for item in extrema
                   if not item["at_band_edge"]]
    if not frequencies:
        return None
    target = float(feature["frequency_hz"])
    return min(abs(math.log2(frequency / target)) for frequency in frequencies)


def _webster_area_profile(
        config: dict[str, Any], yaml_path: Path,
) -> AreaProfile:
    """Build the round control-study profile without tessellating full rings."""
    g = config["global"]
    modifier = config.get("section_modifier", {})
    simple_round = (
        _same_axes(config)
        and abs(float(g["mouth_width"]) - float(g["mouth_height"])) <= 1e-9
        and float(g.get("conical_extension_length", 0.0)) == 0.0
        and float(g.get("mouth_sag", 0.0)) == 0.0
        and float(modifier.get("mouth_squareness", 0.0)) == 0.0
        and not modifier.get("horizontal_modifier", {}).get("enabled", False)
        and not modifier.get("vertical_modifier", {}).get("enabled", False)
    )
    if not simple_round:
        return horncad_area_profile(yaml_path, station_count=61)
    length = float(g["length"])
    basis = config["horizontal_basis"]
    throat_radius = float(g["throat_radius"])
    throat_angle = float(g.get("throat_angle_deg", 0.0))
    coverage = float(basis["coverage_deg"])
    k, n = float(basis["k"]), float(basis["n"])
    s_value = _finite(basis.get("solved_s"))
    if s_value is None:
        s_value = solved_s(
            length, throat_radius, coverage, k, n,
            float(g["mouth_width"]) / 2.0, throat_angle)
    z_mm = np.linspace(0.0, length, 81)
    radius_mm = np.asarray([
        osse_radius(value, length, throat_radius, coverage, k, n,
                    s_value, throat_angle)
        for value in z_mm
    ])
    return AreaProfile(
        positions_m=z_mm * 1e-3,
        areas_m2=np.pi * np.square(radius_mm * 1e-3),
        s_horizontal=s_value,
        s_vertical=s_value,
    )


def webster_reflection_comparison(
        config: dict[str, Any], yaml_path: Path,
        frequencies_hz: np.ndarray, departure_db: np.ndarray,
        peaks: tuple[dict[str, float | bool], ...],
        troughs: tuple[dict[str, float | bool], ...],
) -> dict[str, float | None]:
    """Compare BEM energy redistribution with a lossless 1D reflection spectrum."""
    profile = _webster_area_profile(config, yaml_path)
    results = solve_sweep(profile, frequencies_hz)
    reflection = np.asarray([
        max(abs(result.throat_reflection), 1e-9) for result in results])
    reflection_db = 20.0 * np.log10(reflection)
    reflection_db -= np.mean(reflection_db)
    reflection_db = gaussian_filter1d(
        reflection_db,
        sigma=SMOOTH_SIGMA_OCTAVES * RESAMPLE_POINTS_PER_OCTAVE,
        mode="nearest",
    )
    correlation = (float(np.corrcoef(departure_db, reflection_db)[0, 1])
                   if np.std(departure_db) > 1e-12 and
                   np.std(reflection_db) > 1e-12 else None)
    reflection_peaks = find_bunching_peaks(frequencies_hz, reflection_db)
    reflection_troughs = find_bunching_troughs(frequencies_hz, reflection_db)
    dominant_peak = max(
        (item for item in peaks if not item["at_band_edge"]),
        key=lambda item: float(item["departure_db"]), default=None)
    dominant_trough = min(
        (item for item in troughs if not item["at_band_edge"]),
        key=lambda item: float(item["departure_db"]), default=None)
    return {
        "curve_correlation": correlation,
        "positive_peak_to_reflection_peak_octaves": _nearest_extremum_octaves(
            dominant_peak, reflection_peaks),
        "positive_peak_to_reflection_trough_octaves": _nearest_extremum_octaves(
            dominant_peak, reflection_troughs),
        "negative_trough_to_reflection_peak_octaves": _nearest_extremum_octaves(
            dominant_trough, reflection_peaks),
        "negative_trough_to_reflection_trough_octaves": _nearest_extremum_octaves(
            dominant_trough, reflection_troughs),
    }


def load_observation(npz_path: Path, root: Path) -> Observation | None:
    candidate_dir = npz_path.parent.parent
    yaml_path = candidate_dir / "project.yaml"
    if not yaml_path.is_file():
        return None
    config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))["horncad_config"]
    if not _same_axes(config):
        return None
    intent = config.get("operating_intent", {})
    lower = float(intent.get("crossover_hz", 0.0))
    upper = float(intent.get("upper_frequency_hz", 0.0))
    if not 0.0 < lower < upper:
        return None
    with np.load(npz_path, allow_pickle=False) as data:
        curves = [slice_energy_departure(
            data["frequencies_hz"], data["angles_deg"], data[name], lower, upper)
            for name in ("horizontal_db", "vertical_db")]
    frequencies = curves[0][0]
    departure = np.mean([curve[1] for curve in curves], axis=0)
    peaks = find_bunching_peaks(frequencies, departure)
    troughs = find_bunching_troughs(frequencies, departure)
    g, basis = config["global"], config["horizontal_basis"]
    report_path = candidate_dir / next(iter(sorted(
        path.name for path in candidate_dir.glob("*_Report.html"))), "")
    report = (str(report_path.relative_to(root)) if report_path.is_file() else None)
    try:
        webster = webster_reflection_comparison(
            config, yaml_path, frequencies, departure, peaks, troughs)
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        # The BEM observation remains useful when the deliberately simplified
        # one-dimensional mechanism screen cannot represent its geometry.
        webster = {}
    return Observation(
        identifier=str(candidate_dir.relative_to(root)), report=report,
        mouth_mm=float(g["mouth_width"]),
        coverage_deg=float(intent.get("horizontal_coverage_deg",
                                      basis["coverage_deg"])),
        length_mm=float(g["length"]), k=float(basis["k"]), n=float(basis["n"]),
        s=float(basis.get("solved_s", math.nan)), frequencies_hz=frequencies,
        departure_db=departure, peaks=peaks, troughs=troughs,
        scales_mm=physical_scales(config),
        webster=webster,
    )


def load_observations(root: Path) -> tuple[list[Observation], dict[str, int]]:
    observations, counts = [], {"npz": 0, "usable": 0, "asymmetric": 0, "unreadable": 0}
    for npz_path in sorted(root.rglob("bem/responses.npz")):
        counts["npz"] += 1
        try:
            observation = load_observation(npz_path, root)
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
            counts["unreadable"] += 1
            continue
        if observation is None:
            counts["asymmetric"] += 1
        else:
            observations.append(observation)
    deduplicated: dict[tuple[float, ...], Observation] = {}
    for item in observations:
        key = tuple(round(value, 3) for value in (
            item.mouth_mm, item.coverage_deg, item.length_mm, item.k, item.n))
        deduplicated[key] = item
    counts["usable"] = len(deduplicated)
    counts["duplicates"] = len(observations) - len(deduplicated)
    return sorted(deduplicated.values(), key=lambda item: (
        item.coverage_deg, item.mouth_mm, item.length_mm, item.k, item.n)), counts


def association_summary(observations: Iterable[Observation],
                        feature: str = "peak") -> list[dict[str, Any]]:
    if feature not in {"peak", "trough"}:
        raise ValueError("feature must be peak or trough")
    attribute = "dominant_peak" if feature == "peak" else "dominant_trough"
    observations = [item for item in observations
                    if getattr(item, attribute) is not None]
    scale_names = sorted(set.intersection(*(
        set(item.scales_mm) for item in observations))) if observations else []
    output = []
    for name in scale_names:
        lengths = np.asarray([item.scales_mm[name] for item in observations])
        feature_frequencies = np.asarray([
            float(getattr(item, attribute)["frequency_hz"])
            for item in observations])
        log_length, log_frequency = np.log2(lengths), np.log2(feature_frequencies)
        dimensionless = log_frequency + np.log2(lengths * 1e-3 / SOUND_SPEED_M_S)
        center = float(np.median(dimensionless))
        mad = float(np.median(np.abs(dimensionless - center)))
        slope = float(np.polyfit(log_length, log_frequency, 1)[0])
        correlation = float(spearmanr(log_length, log_frequency).statistic)
        output.append({
            "scale": name, "count": len(observations),
            "log2_dimensionless_mad": mad,
            "dimensionless_p10_p90_span_octaves": float(
                np.percentile(dimensionless, 90) - np.percentile(dimensionless, 10)),
            "log_frequency_vs_log_length_slope": slope,
            "spearman_log_length_frequency": correlation,
            "expected_inverse_slope": -1.0,
        })
    return sorted(output, key=lambda item: (
        item["log2_dimensionless_mad"], abs(item["log_frequency_vs_log_length_slope"] + 1)))


def spacing_association_summary(
        observations: Iterable[Observation], spacing: str,
) -> list[dict[str, Any]]:
    """Test whether linear extremum spacing follows an inverse geometry scale."""
    observations = [item for item in observations
                    if spacing in item.frequency_spacings_hz]
    scale_names = sorted(set.intersection(*(
        set(item.scales_mm) for item in observations))) if observations else []
    output = []
    for name in scale_names:
        lengths = np.asarray([item.scales_mm[name] for item in observations])
        spacings = np.asarray([
            item.frequency_spacings_hz[spacing] for item in observations])
        log_length, log_spacing = np.log2(lengths), np.log2(spacings)
        dimensionless = log_spacing + np.log2(
            lengths * 1e-3 / SOUND_SPEED_M_S)
        center = float(np.median(dimensionless))
        output.append({
            "spacing": spacing, "scale": name, "count": len(observations),
            "log2_dimensionless_mad": float(
                np.median(np.abs(dimensionless - center))),
            "dimensionless_p10_p90_span_octaves": float(
                np.percentile(dimensionless, 90) - np.percentile(dimensionless, 10)),
            "log_spacing_vs_log_length_slope": float(
                np.polyfit(log_length, log_spacing, 1)[0]),
            "spearman_log_length_spacing": float(
                spearmanr(log_length, log_spacing).statistic),
            "expected_inverse_slope": -1.0,
        })
    return sorted(output, key=lambda item: (
        item["log2_dimensionless_mad"],
        abs(item["log_spacing_vs_log_length_slope"] + 1)))


def _pair_key(item: Observation, control: str) -> tuple[float, ...]:
    values = [item.mouth_mm, item.coverage_deg]
    if control != "length_mm":
        values.append(item.length_mm)
    if control != "k":
        values.append(item.k)
    if control != "n":
        values.append(item.n)
    return tuple(round(value, 3) for value in values)


def curve_translation(lower: Observation, upper: Observation) -> dict[str, float]:
    """Estimate a frequency translation by aligning complete departure curves."""
    lower_x = np.log2(lower.frequencies_hz)
    upper_x = np.log2(upper.frequencies_hz)
    left, right = max(lower_x[0], upper_x[0]), min(lower_x[-1], upper_x[-1])
    step = 1.0 / (2.0 * RESAMPLE_POINTS_PER_OCTAVE)
    shifts = np.arange(-MAXIMUM_MATCHED_SHIFT_OCTAVES,
                       MAXIMUM_MATCHED_SHIFT_OCTAVES + step / 2.0, step)

    def error(shift: float) -> float:
        overlap_left = max(left, upper_x[0] - shift)
        overlap_right = min(right, upper_x[-1] - shift)
        x = np.arange(overlap_left, overlap_right + step / 2.0, step)
        if len(x) < 16:
            return math.inf
        first = np.interp(x, lower_x, lower.departure_db)
        second = np.interp(x + shift, upper_x, upper.departure_db)
        first -= np.mean(first)
        second -= np.mean(second)
        return float(np.sqrt(np.mean((first - second) ** 2)))

    errors = np.asarray([error(float(shift)) for shift in shifts])
    best_index = int(np.argmin(errors))
    zero_index = int(np.argmin(np.abs(shifts)))
    zero_error, best_error = float(errors[zero_index]), float(errors[best_index])
    gain = ((zero_error - best_error) / zero_error
            if zero_error > 1e-12 else 0.0)
    return {
        "shift_octaves": float(shifts[best_index]),
        "zero_shift_rms_db": zero_error,
        "best_shift_rms_db": best_error,
        "alignment_gain_fraction": gain,
        "at_search_boundary": bool(best_index in (0, len(shifts) - 1)),
    }


def matched_scale_summary(observations: Iterable[Observation]) -> list[dict[str, Any]]:
    observations = list(observations)
    scale_names = sorted(set.intersection(*(
        set(item.scales_mm) for item in observations))) if observations else []
    residuals: dict[tuple[str, str], list[float]] = {}
    cells: dict[tuple[str, str], set[tuple[float, float]]] = {}
    raw_shifts: dict[str, list[float]] = {control: [] for control in CONTROLS}
    alignment_gains: dict[str, list[float]] = {control: [] for control in CONTROLS}
    for control in CONTROLS:
        groups: dict[tuple[float, ...], list[Observation]] = {}
        for item in observations:
            groups.setdefault(_pair_key(item, control), []).append(item)
        for group in groups.values():
            ordered = sorted(group, key=lambda item: getattr(item, control))
            for lower, upper in zip(ordered, ordered[1:]):
                if getattr(upper, control) <= getattr(lower, control) + 1e-6:
                    continue
                translation = curve_translation(lower, upper)
                if (translation["alignment_gain_fraction"] <
                        MINIMUM_TRANSLATION_ALIGNMENT_GAIN or
                        translation["at_search_boundary"]):
                    continue
                observed = translation["shift_octaves"]
                raw_shifts[control].append(abs(observed))
                alignment_gains[control].append(
                    translation["alignment_gain_fraction"])
                for scale in scale_names:
                    predicted = -math.log2(
                        upper.scales_mm[scale] / lower.scales_mm[scale])
                    residuals.setdefault((control, scale), []).append(
                        abs(observed - predicted))
                    cells.setdefault((control, scale), set()).add(
                        (lower.coverage_deg, lower.mouth_mm))
    output = []
    for (control, scale), values in residuals.items():
        baseline = median(raw_shifts[control]) if raw_shifts[control] else None
        error = median(values)
        output.append({
            "control": control, "scale": scale, "pair_count": len(values),
            "cell_count": len(cells[(control, scale)]),
            "median_absolute_shift_error_octaves": error,
            "no_shift_baseline_error_octaves": baseline,
            "improvement_over_no_shift_octaves": (
                baseline - error if baseline is not None else None),
            "median_curve_alignment_gain_fraction": median(
                alignment_gains[control]),
        })
    return sorted(output, key=lambda item: (
        item["control"], item["median_absolute_shift_error_octaves"]))


def webster_summary(observations: Iterable[Observation]) -> dict[str, Any]:
    observations = list(observations)
    correlations = [float(item.webster["curve_correlation"])
                    for item in observations
                    if item.webster.get("curve_correlation") is not None]
    output: dict[str, Any] = {
        "candidate_count": len(correlations),
        "model": "lossless Webster 1D with baffled-piston mouth load",
    }
    if correlations:
        output.update({
            "median_curve_correlation": median(correlations),
            "median_absolute_curve_correlation": median(
                abs(value) for value in correlations),
            "absolute_correlation_at_least_0_5_fraction": sum(
                abs(value) >= 0.5 for value in correlations) / len(correlations),
        })
    for key in (
            "positive_peak_to_reflection_peak_octaves",
            "positive_peak_to_reflection_trough_octaves",
            "negative_trough_to_reflection_peak_octaves",
            "negative_trough_to_reflection_trough_octaves"):
        values = [float(item.webster[key]) for item in observations
                  if item.webster.get(key) is not None]
        output[key] = {
            "count": len(values),
            "median_nearest_distance_octaves": median(values) if values else None,
            "within_one_sixth_octave_fraction": (
                sum(value <= 1.0 / 6.0 for value in values) / len(values)
                if values else None),
        }
    return output


def analyze(root: Path) -> dict[str, Any]:
    observations, inventory = load_observations(root)
    association = association_summary(observations)
    trough_association = association_summary(observations, "trough")
    spacing_association = {
        name: spacing_association_summary(observations, name)
        for name in ("adjacent_extrema", "peak_to_peak", "trough_to_trough")
    }
    matched = matched_scale_summary(observations)
    webster = webster_summary(observations)
    try:
        source_root = str(root.relative_to(Path.cwd()))
    except ValueError:
        source_root = str(root)
    return {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": source_root, "inventory": inventory,
        "method": {
            "sound_speed_m_s": SOUND_SPEED_M_S,
            "resample_points_per_octave": RESAMPLE_POINTS_PER_OCTAVE,
            "smoothing_sigma_octaves": SMOOTH_SIGMA_OCTAVES,
            "minimum_peak_prominence_db": MINIMUM_PEAK_PROMINENCE_DB,
            "minimum_peak_spacing_octaves": MINIMUM_PEAK_SPACING_OCTAVES,
            "matched_pair_maximum_shift_octaves": MAXIMUM_MATCHED_SHIFT_OCTAVES,
            "minimum_translation_alignment_gain_fraction": MINIMUM_TRANSLATION_ALIGNMENT_GAIN,
            "interpretation": "association only; causal attribution requires repeatable matched-pair shifts and prospective validation",
        },
        "association": association, "trough_association": trough_association,
        "spacing_association": spacing_association,
        "matched_pairs": matched, "webster_comparison": webster,
        "observations": [{
            "id": item.identifier, "report": item.report,
            "mouth_mm": item.mouth_mm, "coverage_deg": item.coverage_deg,
            "length_mm": item.length_mm, "k": item.k, "n": item.n, "s": item.s,
            "scales_mm": item.scales_mm, "peaks": list(item.peaks),
            "troughs": list(item.troughs),
            "frequency_spacings_hz": item.frequency_spacings_hz,
            "webster": item.webster,
        } for item in observations],
    }


def _number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def render_markdown(data: dict[str, Any]) -> str:
    inventory = data["inventory"]
    association = data["association"][:8]
    trough_association = data["trough_association"][:8]
    lines = [
        "# Physical-scale energy-bunching analysis", "",
        f"Snapshot: `{data['generated_at']}`.", "",
        "## Scope", "",
        f"This analysis found {inventory['npz']} retained NPZ archives and "
        f"used {inventory['usable']} unique symmetric candidates. It tests whether "
        "the dominant interior positive peak and negative trough become more stable "
        "when frequency is normalized by a measured physical length.", "",
        "A small collapse error is screening evidence, not proof of a resonance or "
        "causal mechanism. Matched one-control shifts are the stronger test; later "
        "completed canonical candidates serve as prospective validation.", "",
        "## Positive-peak dimensionless collapse", "",
        "| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in association:
        lines.append(
            f"| {item['scale'].replace('_', ' ')} | {item['count']} | "
            f"{_number(item['log2_dimensionless_mad'])} | "
            f"{_number(item['dimensionless_p10_p90_span_octaves'])} | "
            f"{_number(item['log_frequency_vs_log_length_slope'])} | "
            f"{_number(item['spearman_log_length_frequency'])} |")
    lines.extend(["", "## Negative-trough dimensionless collapse", "",
                  "| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for item in trough_association:
        lines.append(
            f"| {item['scale'].replace('_', ' ')} | {item['count']} | "
            f"{_number(item['log2_dimensionless_mad'])} | "
            f"{_number(item['dimensionless_p10_p90_span_octaves'])} | "
            f"{_number(item['log_frequency_vs_log_length_slope'])} | "
            f"{_number(item['spearman_log_length_frequency'])} |")
    lines.extend(["", "An inverse-length mechanism predicts an F–length slope "
                  "near -1. Collapse rank alone is insufficient when a scale is "
                  "correlated with mouth, coverage, or OSSE length. The matched "
                  "translation below aligns the full curve, so it tests peaks and "
                  "troughs together without assuming that one dominant extremum "
                  "keeps the same identity.", "",
                  "## Linear-frequency extremum spacing", "",
                  "A round-trip or standing-wave mechanism more naturally predicts "
                  "linear frequency spacing proportional to `1 / length` than it "
                  "predicts one absolute peak frequency.", ""])
    for spacing in ("adjacent_extrema", "peak_to_peak", "trough_to_trough"):
        rows = data["spacing_association"][spacing][:6]
        lines.extend([
            f"### {spacing.replace('_', ' ')}", "",
            "| Physical scale | Candidates | MAD octaves | P10–P90 span | Spacing–length slope | Spearman |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        if not rows:
            lines.append("| Insufficient repeated extrema | 0 | — | — | — | — |")
        for item in rows:
            lines.append(
                f"| {item['scale'].replace('_', ' ')} | {item['count']} | "
                f"{_number(item['log2_dimensionless_mad'])} | "
                f"{_number(item['dimensionless_p10_p90_span_octaves'])} | "
                f"{_number(item['log_spacing_vs_log_length_slope'])} | "
                f"{_number(item['spearman_log_length_spacing'])} |")
        lines.append("")
    closest_inverse = min(
        (item for rows in data["spacing_association"].values() for item in rows),
        key=lambda item: abs(item["log_spacing_vs_log_length_slope"] + 1.0),
        default=None,
    )
    if closest_inverse is not None:
        lines.extend([
            "The closest measured spacing slope to the inverse-length prediction "
            f"is {_number(closest_inverse['log_spacing_vs_log_length_slope'])} "
            f"for {closest_inverse['spacing'].replace('_', ' ')} versus "
            f"{closest_inverse['scale'].replace('_', ' ')}. Thus, a small "
            "dimensionless MAD in these tables is not evidence for a simple "
            "standing-wave law when the fitted slope remains far from -1.", "",
        ])
    webster = data["webster_comparison"]
    lines.extend([
        "## Webster 1D reflection comparison", "",
        "The lossless plane-wave Webster model is a mechanism screen, not BEM "
        "ground truth. A strong correspondence would support an axial impedance/"
        "reflection explanation; weak correspondence shifts attention toward "
        "aperture directivity or higher-order spatial behavior.", "",
        f"Candidates compared: {webster['candidate_count']}. Median signed curve "
        f"correlation: {_number(webster.get('median_curve_correlation'))}; median "
        f"absolute correlation: {_number(webster.get('median_absolute_curve_correlation'))}. "
        f"The fraction with absolute correlation at least 0.5 is "
        f"{_number(100 * webster.get('absolute_correlation_at_least_0_5_fraction', 0), 1)}%.", "",
        "| BEM feature → Webster feature | Comparisons | Median distance oct | Within 1/6 oct |",
        "| --- | ---: | ---: | ---: |",
    ])
    for key, label in (
            ("positive_peak_to_reflection_peak_octaves", "positive peak → reflection peak"),
            ("positive_peak_to_reflection_trough_octaves", "positive peak → reflection trough"),
            ("negative_trough_to_reflection_peak_octaves", "negative trough → reflection peak"),
            ("negative_trough_to_reflection_trough_octaves", "negative trough → reflection trough")):
        item = webster[key]
        fraction = item["within_one_sixth_octave_fraction"]
        lines.append(
            f"| {label} | {item['count']} | "
            f"{_number(item['median_nearest_distance_octaves'])} | "
            f"{_number(100 * fraction, 1) + '%' if fraction is not None else '—'} |")
    lines.extend(["", "## Matched one-control shifts", ""])
    for control in CONTROLS:
        rows = [item for item in data["matched_pairs"] if item["control"] == control][:6]
        lines.extend([
            f"### {control}", "",
            "| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        if not rows:
            lines.append("| No qualifying translated pairs yet | 0 | 0 | — | — | — | — |")
        for item in rows:
            lines.append(
                f"| {item['scale'].replace('_', ' ')} | {item['pair_count']} | "
                f"{item['cell_count']} | "
                f"{_number(item['median_absolute_shift_error_octaves'])} | "
                f"{_number(item['no_shift_baseline_error_octaves'])} | "
                f"{_number(item['improvement_over_no_shift_octaves'])} | "
                f"{_number(100 * item['median_curve_alignment_gain_fraction'], 1)}% |")
        lines.append("")
    lines.extend([
        "## Interpretation gate", "",
        "Promote a scale from *association* to *supported* only when it improves "
        "matched-pair shift prediction over the no-shift baseline, the full curve "
        "aligns materially better after translation, the result repeats across "
        "independent mouth/coverage cells, and predicts candidates completed after "
        "this snapshot. Endpoint peaks and troughs are retained in the JSON but "
        "excluded from the dominant-feature fits because their true extrema may lie outside the "
        "simulated band.", "",
        "The complete candidate peaks, troughs, physical scales, method constants, and all "
        "association rows are retained in `bunching_physical_scales.json`.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?",
                        default=Path("examples/control-decoupling"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output_dir.resolve() if args.output_dir else root / "analysis")
    output.mkdir(parents=True, exist_ok=True)
    data = analyze(root)
    (output / "bunching_physical_scales.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (output / "bunching_physical_scales.md").write_text(
        render_markdown(data), encoding="utf-8")
    print(f"Analyzed {data['inventory']['usable']} candidates into {output}")


if __name__ == "__main__":
    main()
