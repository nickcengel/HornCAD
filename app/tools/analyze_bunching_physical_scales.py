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
    }
    for fraction in (0.1, 0.5, 0.9):
        position = _first_crossing(z, termination, fraction)
        scales[f"termination_{round(100 * fraction):02d}_from_throat"] = position
        scales[f"termination_{round(100 * fraction):02d}_to_mouth"] = length - position
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
    g, basis = config["global"], config["horizontal_basis"]
    report_path = candidate_dir / next(iter(sorted(
        path.name for path in candidate_dir.glob("*_Report.html"))), "")
    report = (str(report_path.relative_to(root)) if report_path.is_file() else None)
    return Observation(
        identifier=str(candidate_dir.relative_to(root)), report=report,
        mouth_mm=float(g["mouth_width"]),
        coverage_deg=float(intent.get("horizontal_coverage_deg",
                                      basis["coverage_deg"])),
        length_mm=float(g["length"]), k=float(basis["k"]), n=float(basis["n"]),
        s=float(basis.get("solved_s", math.nan)), frequencies_hz=frequencies,
        departure_db=departure, peaks=find_bunching_peaks(frequencies, departure),
        troughs=find_bunching_troughs(frequencies, departure),
        scales_mm=physical_scales(config),
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


def analyze(root: Path) -> dict[str, Any]:
    observations, inventory = load_observations(root)
    association = association_summary(observations)
    trough_association = association_summary(observations, "trough")
    matched = matched_scale_summary(observations)
    try:
        source_root = str(root.relative_to(Path.cwd()))
    except ValueError:
        source_root = str(root)
    return {
        "schema_version": 2,
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
        "matched_pairs": matched,
        "observations": [{
            "id": item.identifier, "report": item.report,
            "mouth_mm": item.mouth_mm, "coverage_deg": item.coverage_deg,
            "length_mm": item.length_mm, "k": item.k, "n": item.n, "s": item.s,
            "scales_mm": item.scales_mm, "peaks": list(item.peaks),
            "troughs": list(item.troughs),
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
        f"This initial analysis found {inventory['npz']} retained NPZ archives and "
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
                  "## Matched one-control shifts", ""])
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
