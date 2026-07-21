#!/usr/bin/env python3
"""Create interactive HornCAD result and multi-project comparison reports."""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yaml

try:
    from .surface_diagnostics import surface_diagnostics, surface_score
except ImportError:
    from surface_diagnostics import surface_diagnostics, surface_score


COLORS = ("#2563eb", "#dc2626", "#16a34a", "#9333ea")
AIR_DENSITY_KG_M3 = 1.2041
SOUND_SPEED_M_S = 343.21
PASSBAND_CONFIRMATION_OCTAVES = 1.0 / 3.0
COVERAGE_TRANSITION_SLOPE_DB_PER_OCTAVE = 12.0
COVERAGE_TRANSITION_DB_AT_CROSSOVER = -6.0
COVERAGE_LOCAL_SMOOTH_OCTAVES = 1.0 / 6.0
COVERAGE_SMOOTHNESS_TREND_OCTAVES = 1.0 / 3.0
COVERAGE_SMOOTHNESS_SCORE_GAIN = 3.4
COVERAGE_WAIST_REGION_OCTAVES = 2.0
COVERAGE_WAIST_MIN_UNDERSHOOT_PERCENT = 1.0
COVERAGE_WINDOW_PROBE_FRACTION = 0.5
COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB = 10.0
COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB = 20.0


def _scalar(value: Any) -> Any:
    if isinstance(value, np.ndarray) and value.ndim == 0:
        return value.item()
    return value


def _source_yaml(run_dir: Path) -> Path | None:
    for filename, key in (("run_settings.json", "yaml_path"),
                          ("manifest.json", "yaml")):
        path = run_dir / filename
        if path.is_file():
            candidate = Path(json.loads(path.read_text()).get(key, ""))
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            if candidate.is_file():
                return candidate
    candidates = list(run_dir.glob("*.yaml")) + list(run_dir.glob("*.YAML"))
    if candidates:
        return candidates[0]
    for parent in run_dir.parents:
        candidate = parent / "project.yaml"
        if candidate.is_file():
            return candidate
    return None


def acoustic_parameters(yaml_path: Path | None) -> dict[str, str]:
    if yaml_path is None:
        return {}
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    g = config.get("global", {})
    h = config.get("horizontal_basis", {})
    v = config.get("vertical_basis", {})
    modifier = config.get("section_modifier", {})
    length = float(g.get("length", 0))
    mouth_width = float(g.get("mouth_width", 0))
    length_mouth_ratio = mouth_width / length if length else 0.0
    values = {
        "Length": f"{length:g} mm",
        "Mouth": f"{g.get('mouth_width', 0):g} × {g.get('mouth_height', 0):g} mm",
        "Length-mouth ratio": f"{length_mouth_ratio:.3g}",
        "Mouth sag": f"{g.get('mouth_sag', 0):g} mm",
        "Throat radius": f"{g.get('throat_radius', 0):g} mm",
        "Throat angle": f"{g.get('throat_angle_deg', 0):g}°",
        "Conical extension": f"{g.get('conical_extension_length', 0):g} mm",
        "Effective throat radius": f"{g.get('effective_throat_radius', 0):g} mm",
        "Coverage H / V": f"{h.get('coverage_deg', 0):g}° / {v.get('coverage_deg', 0):g}°",
        "K H / V": f"{h.get('k', 0):g} / {v.get('k', 0):g}",
        "N H / V": f"{h.get('n', 0):g} / {v.get('n', 0):g}",
        "S H / V": f"{h.get('solved_s', 0):.6g} / {v.get('solved_s', 0):.6g}",
        "Mouth squareness": f"{modifier.get('mouth_squareness', 0):g}",
    }
    return values


def throat_reference_impedance(yaml_path: Path | None) -> float | None:
    """Return rho*c/S for the effective circular throat."""
    if yaml_path is None:
        return None
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    global_config = config.get("global", {})
    radius_mm = global_config.get(
        "effective_throat_radius", global_config.get("throat_radius"))
    if radius_mm is None or float(radius_mm) <= 0.0:
        return None
    area_m2 = np.pi * (float(radius_mm) * 1e-3) ** 2
    return AIR_DENSITY_KG_M3 * SOUND_SPEED_M_S / area_m2


def intended_coverages(yaml_path: Path | None) -> dict[str, float]:
    if yaml_path is None:
        return {}
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    intent = config.get("operating_intent", {})
    return {
        "horizontal": float(intent.get("horizontal_coverage_deg",
                           config.get("horizontal_basis", {}).get("coverage_deg", 0))),
        "vertical": float(intent.get("vertical_coverage_deg",
                         config.get("vertical_basis", {}).get("coverage_deg", 0))),
    }


def mouth_dimensions(yaml_path: Path | None) -> dict[str, float]:
    """Return physical dimensions used to weight H/V coverage diagnostics."""
    if yaml_path is None:
        return {}
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    global_config = config.get("global", {})
    return {
        "horizontal": float(global_config.get("mouth_width", 0)),
        "vertical": float(global_config.get("mouth_height", 0)),
    }


def crossover_frequency(yaml_path: Path | None) -> float | None:
    if yaml_path is None:
        return None
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    value = config.get("operating_intent", {}).get("crossover_hz")
    return float(value) if value is not None and float(value) > 0 else None


def _crossover_transition_weights(
        frequencies: np.ndarray, crossover_hz: float | None) -> np.ndarray:
    """Return amplitude weights for the assumed acoustic crossover transition."""
    frequencies = np.asarray(frequencies, dtype=float)
    weights = np.ones_like(frequencies)
    if crossover_hz is None or not np.isfinite(crossover_hz) or crossover_hz <= 0:
        return weights
    ratio = np.maximum(frequencies / crossover_hz, np.finfo(float).tiny)
    gain_db = (COVERAGE_TRANSITION_DB_AT_CROSSOVER +
               COVERAGE_TRANSITION_SLOPE_DB_PER_OCTAVE * np.log2(ratio))
    return np.minimum(1.0, 10 ** (gain_db / 20))


def load_run(run_dir: Path, name: str | None = None) -> dict[str, Any]:
    response_path = run_dir / "responses.npz"
    if not response_path.is_file():
        raise FileNotFoundError(response_path)
    with np.load(response_path, allow_pickle=False) as data:
        frequencies = np.asarray(data["frequencies_hz"], dtype=float)
        angles = np.asarray(data["angles_deg"], dtype=float)
        horizontal = np.asarray(data["horizontal_db"], dtype=float)
        vertical = np.asarray(data["vertical_db"], dtype=float)
        impedance = (np.asarray(data["impedance"], dtype=complex)
                     if "impedance" in data else None)
    yaml_path = _source_yaml(run_dir)
    reference_impedance = throat_reference_impedance(yaml_path)
    return {
        "name": name or (yaml_path.stem if yaml_path else run_dir.name),
        "run_dir": run_dir,
        "frequencies": frequencies,
        "angles": angles,
        "horizontal": horizontal,
        "vertical": vertical,
        "impedance": impedance,
        "normalized_impedance": (impedance / reference_impedance
                                 if impedance is not None and reference_impedance else None),
        "parameters": acoustic_parameters(yaml_path),
        "intended_coverages": intended_coverages(yaml_path),
        "mouth_dimensions_mm": mouth_dimensions(yaml_path),
        "crossover_hz": crossover_frequency(yaml_path),
        "yaml": yaml_path,
    }


def _positive_half_angle(angles: np.ndarray, levels: np.ndarray) -> np.ndarray:
    positive = angles >= 0
    a = angles[positive]
    output = []
    for row in levels[:, positive]:
        crossing = 90.0
        for index in range(len(a) - 1):
            if row[index] >= -6 and row[index + 1] < -6:
                crossing = float(a[index] + (-6 - row[index]) /
                                 (row[index + 1] - row[index]) *
                                 (a[index + 1] - a[index]))
                break
        output.append(crossing)
    return np.asarray(output)


def _measured_half_angle(angles: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Return genuine positive-side -6 dB crossings; no crossing is NaN."""
    positive = angles >= 0
    a = angles[positive]
    output = []
    for row in levels[:, positive]:
        crossing = np.nan
        for index in range(len(a) - 1):
            if row[index] >= -6 and row[index + 1] < -6:
                crossing = float(a[index] + (-6 - row[index]) /
                                 (row[index + 1] - row[index]) *
                                 (a[index + 1] - a[index]))
                break
        output.append(crossing)
    return np.asarray(output)


def coverage_diagnostics(
        run: dict[str, Any], evaluation_frequencies: np.ndarray | None = None,
        fixed_band: bool = False,
) -> dict[str, Any]:
    """Summarize coverage fidelity over an automatic or explicit common grid."""
    order = np.argsort(run["frequencies"])
    frequencies = np.asarray(run["frequencies"], dtype=float)[order]
    measured = {
        key: _measured_half_angle(run["angles"], run[key])[order]
        for key in ("horizontal", "vertical")
    }
    sorted_levels = {
        key: np.asarray(run[key], dtype=float)[order]
        for key in ("horizontal", "vertical")
    }
    valid_both = np.isfinite(measured["horizontal"]) & np.isfinite(measured["vertical"])
    start_index = None
    for index in np.flatnonzero(valid_both):
        confirmation_end = frequencies[index] * 2 ** PASSBAND_CONFIRMATION_OCTAVES
        end_index = int(np.searchsorted(frequencies, confirmation_end, side="left"))
        if (end_index < len(frequencies) and end_index > index
                and np.all(valid_both[index:end_index + 1])):
            start_index = int(index)
            break
    if start_index is None and not fixed_band:
        return {"status": "unavailable",
                "reason": "no sustained horizontal and vertical -6 dB crossings"}

    # A missing crossing after the passband is established means coverage exceeded
    # the measured hemisphere. Treat it as 90 degrees instead of discarding it.
    source_start = 0 if fixed_band else start_index
    source_frequencies = frequencies[source_start:]
    source_angles = {
        key: np.where(np.isfinite(values[source_start:]), values[source_start:], 90.0)
        for key, values in measured.items()
    }
    source_levels = {
        key: values[source_start:]
        for key, values in sorted_levels.items()
    }
    if evaluation_frequencies is None:
        evaluated_frequencies = source_frequencies
        angles = source_angles
        band_kind = "automatic"
    else:
        evaluated_frequencies = np.asarray(evaluation_frequencies, dtype=float)
        if (evaluated_frequencies.ndim != 1 or len(evaluated_frequencies) < 2
                or np.any(np.diff(evaluated_frequencies) <= 0)):
            raise ValueError("evaluation frequencies must be an increasing 1-D grid")
        tolerance = 1e-10
        if (evaluated_frequencies[0] < source_frequencies[0] * (1 - tolerance)
                or evaluated_frequencies[-1] > source_frequencies[-1] * (1 + tolerance)):
            return {"status": "unavailable",
                    "reason": "common comparison band is outside the valid passband"}
        angles = {
            key: np.interp(np.log(evaluated_frequencies), np.log(source_frequencies), values)
            for key, values in source_angles.items()
        }
        band_kind = "fixed optimization" if fixed_band else "common comparison"
    targets = run["intended_coverages"]
    if any(targets.get(key, 0) <= 0 for key in angles):
        return {"status": "unavailable", "reason": "intended coverage is missing"}
    log_frequency = np.log(evaluated_frequencies)
    log_span = log_frequency[-1] - log_frequency[0]
    crossover_hz = run.get("crossover_hz")
    crossover_hz = (float(crossover_hz)
                    if crossover_hz is not None and float(crossover_hz) > 0
                    else None)
    clipped_crossover_hz = (float(np.clip(crossover_hz, evaluated_frequencies[0],
                                          evaluated_frequencies[-1]))
                            if crossover_hz is not None else None)
    transition_weights = _crossover_transition_weights(
        evaluated_frequencies, clipped_crossover_hz)
    transition_full_weight_hz = (
        clipped_crossover_hz *
        2 ** ((0.0 - COVERAGE_TRANSITION_DB_AT_CROSSOVER) /
              COVERAGE_TRANSITION_SLOPE_DB_PER_OCTAVE)
        if clipped_crossover_hz is not None else float(evaluated_frequencies[0]))
    waist_region_lower_hz = max(float(evaluated_frequencies[0]),
                                float(transition_full_weight_hz))
    waist_region_upper_hz = min(
        float(evaluated_frequencies[-1]),
        waist_region_lower_hz * 2 ** COVERAGE_WAIST_REGION_OCTAVES)
    if waist_region_upper_hz <= waist_region_lower_hz:
        waist_region_lower_hz = float(evaluated_frequencies[0])
        waist_region_upper_hz = float(evaluated_frequencies[-1])

    def rms(values: np.ndarray, weights: np.ndarray | None = None) -> float:
        x = log_frequency
        selected = np.asarray(values, dtype=float)
        if weights is not None:
            selected = selected * weights
        if len(selected) < 2 or x[-1] <= x[0]:
            return float(np.max(np.abs(selected)))
        return float(np.sqrt(np.trapezoid(selected ** 2, x) / log_span))

    def local_smooth(values: np.ndarray, sigma_octaves: float) -> np.ndarray:
        """Smooth on a logarithmic frequency axis using local linear fits."""
        if len(values) < 3:
            return values.copy()
        sigma = np.log(2) * sigma_octaves
        smoothed = np.empty_like(values)
        for index, center in enumerate(log_frequency):
            offsets = log_frequency - center
            weights = np.exp(-0.5 * (offsets / sigma) ** 2)
            design = np.column_stack((np.ones(len(offsets)), offsets))
            coefficients = np.linalg.lstsq(
                design * np.sqrt(weights[:, None]), values * np.sqrt(weights),
                rcond=None)[0]
            smoothed[index] = coefficients[0]
        return smoothed

    def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
        selected = np.asarray(values, dtype=float)
        w = np.asarray(weights, dtype=float) ** 2
        if len(selected) < 2 or log_frequency[-1] <= log_frequency[0]:
            denominator = float(np.sum(w))
            return float(np.sum(selected * w) / denominator) if denominator > 0 else float(np.mean(selected))
        denominator = float(np.trapezoid(w, log_frequency))
        if denominator <= 0:
            return float(np.mean(selected))
        return float(np.trapezoid(selected * w, log_frequency) / denominator)

    def weighted_fraction(mask: np.ndarray, weights: np.ndarray) -> float:
        selected = np.asarray(mask, dtype=float)
        w = np.asarray(weights, dtype=float) ** 2
        if len(selected) < 2 or log_frequency[-1] <= log_frequency[0]:
            denominator = float(np.sum(w))
            return float(np.sum(selected * w) / denominator) if denominator > 0 else 0.0
        denominator = float(np.trapezoid(w, log_frequency))
        if denominator <= 0:
            return 0.0
        return float(np.trapezoid(selected * w, log_frequency) / denominator)

    angle_order = np.argsort(np.asarray(run["angles"], dtype=float))
    sorted_response_angles = np.asarray(run["angles"], dtype=float)[angle_order]

    def probe_trace(levels: np.ndarray, probe_angle: float) -> np.ndarray:
        if (probe_angle < sorted_response_angles[0] or
                probe_angle > sorted_response_angles[-1]):
            return np.full_like(evaluated_frequencies, np.nan, dtype=float)
        source_trace = np.asarray([
            np.interp(probe_angle, sorted_response_angles, row[angle_order])
            for row in levels
        ], dtype=float)
        if evaluation_frequencies is None:
            return source_trace
        return np.interp(np.log(evaluated_frequencies),
                         np.log(source_frequencies), source_trace)

    def evaluated_level_grid(levels: np.ndarray) -> np.ndarray:
        source_grid = np.asarray(levels[:, angle_order], dtype=float)
        if evaluation_frequencies is None:
            return source_grid
        output = np.empty((len(evaluated_frequencies), source_grid.shape[1]))
        source_log = np.log(source_frequencies)
        evaluated_log = np.log(evaluated_frequencies)
        for angle_index in range(source_grid.shape[1]):
            output[:, angle_index] = np.interp(
                evaluated_log, source_log, source_grid[:, angle_index])
        return output

    def positive_window_metrics(levels: np.ndarray,
                                edge_angles: np.ndarray) -> dict[str, Any]:
        grid = evaluated_level_grid(levels)
        positive_peaks = []
        positive_means = []
        positive_peak_angles = []
        for row, edge_angle in zip(grid, edge_angles):
            upper = float(np.clip(edge_angle, 0.0, sorted_response_angles[-1]))
            mask = ((sorted_response_angles >= 0.0) &
                    (sorted_response_angles <= upper))
            if not np.any(mask):
                mask = sorted_response_angles == sorted_response_angles[
                    np.argmin(np.abs(sorted_response_angles))]
            window_angles = sorted_response_angles[mask]
            positive = np.maximum(row[mask], 0.0)
            peak_index = int(np.argmax(positive))
            positive_peaks.append(float(positive[peak_index]))
            positive_peak_angles.append(float(window_angles[peak_index]))
            if len(positive) < 2 or window_angles[-1] <= window_angles[0]:
                positive_means.append(float(np.mean(positive)))
            else:
                positive_means.append(float(
                    np.trapezoid(positive, window_angles) /
                    (window_angles[-1] - window_angles[0])))
        peaks = np.asarray(positive_peaks, dtype=float)
        means = np.asarray(positive_means, dtype=float)
        active = peaks > 0.0
        return {
            "window_positive_rms_db": rms(peaks, transition_weights),
            "window_positive_mean_db": weighted_mean(means, transition_weights),
            "window_positive_peak_db": float(np.max(peaks)),
            "window_positive_peak_angle_deg": float(
                positive_peak_angles[int(np.argmax(peaks))]),
            "window_positive_band_fraction": weighted_fraction(
                active, transition_weights),
            "window_positive_score_per_db": COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB,
        }

    def window_metrics(levels: np.ndarray, target: float,
                       edge_angles: np.ndarray) -> dict[str, Any]:
        probe_angle = target * COVERAGE_WINDOW_PROBE_FRACTION
        trace = probe_trace(levels, probe_angle)
        if not np.all(np.isfinite(trace)):
            rms_deviation = 10.0
            return {
                "window_uniformity_percent": 0.0,
                "window_probe_fraction": COVERAGE_WINDOW_PROBE_FRACTION,
                "window_probe_angle_deg": probe_angle,
                "window_probe_mean_db": None,
                "window_rms_deviation_db": rms_deviation,
                "window_peak_deviation_db": None,
                "window_p90_deviation_db": None,
                "window_uniformity_score_per_db": COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB,
                "window_positive_rms_db": 10.0,
                "window_positive_mean_db": None,
                "window_positive_peak_db": None,
                "window_positive_peak_angle_deg": None,
                "window_positive_band_fraction": 1.0,
                "window_positive_score_per_db": COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB,
            }
        positive = positive_window_metrics(levels, edge_angles)
        mean = weighted_mean(trace, transition_weights)
        deviation = trace - mean
        rms_deviation = rms(deviation, transition_weights)
        peak_deviation = float(np.max(np.abs(deviation)))
        p90_deviation = float(np.percentile(np.abs(deviation), 90))
        uniformity_error_points = (
            COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB * rms_deviation +
            COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB *
            positive["window_positive_rms_db"])
        return {
            "window_uniformity_percent": max(0.0, 100.0 - uniformity_error_points),
            "window_probe_fraction": COVERAGE_WINDOW_PROBE_FRACTION,
            "window_probe_angle_deg": probe_angle,
            "window_probe_mean_db": mean,
            "window_rms_deviation_db": rms_deviation,
            "window_peak_deviation_db": peak_deviation,
            "window_p90_deviation_db": p90_deviation,
            "window_uniformity_score_per_db": COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB,
            "window_uniformity_error_points": uniformity_error_points,
            "window_positive_error_points": (
                COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB *
                positive["window_positive_rms_db"]),
            **positive,
        }

    def waist_metrics(smooth: np.ndarray, target: float) -> dict[str, Any]:
        """Find a broad lower-band narrowing trough and score its depth."""
        mask = ((evaluated_frequencies >= waist_region_lower_hz) &
                (evaluated_frequencies <= waist_region_upper_hz))
        indices = np.flatnonzero(mask)
        if len(indices) < 3:
            indices = np.arange(len(smooth))
        offset = int(np.argmin(smooth[indices]))
        waist_index = int(indices[offset])
        minimum_undershoot = target * COVERAGE_WAIST_MIN_UNDERSHOOT_PERCENT / 100.0
        detected = bool(0 < offset < len(indices) - 1 and
                        smooth[waist_index] < target - minimum_undershoot)
        undershoot = max(0.0, target - float(smooth[waist_index])) if detected else 0.0
        error = min(100.0, 100.0 * undershoot / target)
        frequency = float(evaluated_frequencies[waist_index]) if detected else None
        angle = float(smooth[waist_index]) if detected else None
        return {
            "waist_stability_percent": max(0.0, 100.0 - error),
            "waistbanding_error_percent": error,
            "waist_detected": detected,
            "waist_frequency_hz": frequency,
            "waist_half_angle_deg": angle,
            "waist_undershoot_deg": undershoot,
            "waist_region_lower_hz": waist_region_lower_hz,
            "waist_region_upper_hz": waist_region_upper_hz,
            "waist_region_octaves": COVERAGE_WAIST_REGION_OCTAVES,
            "waist_min_undershoot_percent": COVERAGE_WAIST_MIN_UNDERSHOOT_PERCENT,
        }

    plane_results = {}
    for key, values in angles.items():
        target = float(targets[key])
        smooth = local_smooth(values, COVERAGE_LOCAL_SMOOTH_OCTAVES)
        smooth_trend = local_smooth(smooth, COVERAGE_SMOOTHNESS_TREND_OCTAVES)
        deviation = smooth - target
        undershoot = np.maximum(-deviation, 0.0)
        overshoot = np.maximum(deviation, 0.0)
        weighted_total_error = 100 * rms(deviation / target, transition_weights)
        weighted_undershoot_error = 100 * rms(undershoot / target,
                                              transition_weights)
        weighted_overshoot_error = 100 * rms(overshoot / target,
                                             transition_weights)
        fine_ripple_error = 100 * rms((values - smooth) / target,
                                      transition_weights)
        broad_wiggle_error = 100 * rms((smooth - smooth_trend) / target,
                                       transition_weights)
        smoothness_raw_error = float(np.hypot(fine_ripple_error, broad_wiggle_error))
        smoothness_error = COVERAGE_SMOOTHNESS_SCORE_GAIN * smoothness_raw_error
        ripple_rms = rms(values - smooth, transition_weights)
        broad_wiggle_rms = rms(smooth - smooth_trend, transition_weights)
        waist = waist_metrics(smooth, target)
        window = window_metrics(source_levels[key], target, values)
        crossover_frequency = clipped_crossover_hz or float(evaluated_frequencies[0])
        crossover_angle = float(np.interp(np.log(crossover_frequency),
                                          log_frequency, values))
        transition_weight_at_crossover = float(np.interp(
            np.log(crossover_frequency), log_frequency, transition_weights))
        highest_frequency_error = float(smooth[-1] - target)
        plane_results[key] = {
            "coverage_match_percent": max(0.0, 100.0 - weighted_total_error),
            "coverage_smoothness_percent": max(0.0, 100.0 - smoothness_error),
            **waist,
            **window,
            "weighted_total_error_percent": weighted_total_error,
            "weighted_undershoot_error_percent": weighted_undershoot_error,
            "weighted_overshoot_error_percent": weighted_overshoot_error,
            "smoothness_error_percent": smoothness_error,
            "smoothness_raw_error_percent": smoothness_raw_error,
            "fine_ripple_error_percent": fine_ripple_error,
            "broad_wiggle_error_percent": broad_wiggle_error,
            "smoothness_score_gain": COVERAGE_SMOOTHNESS_SCORE_GAIN,
            "ripple_rms_deg": ripple_rms,
            "broad_wiggle_rms_deg": broad_wiggle_rms,
            "local_smooth_octaves": COVERAGE_LOCAL_SMOOTH_OCTAVES,
            "smoothness_trend_octaves": COVERAGE_SMOOTHNESS_TREND_OCTAVES,
            "crossover_frequency_hz": crossover_frequency,
            "crossover_half_angle_deg": crossover_angle,
            "transition_weight_at_crossover": transition_weight_at_crossover,
            "transition_full_weight_hz": float(transition_full_weight_hz),
            "worst_broad_undershoot_deg": float(np.max(undershoot)),
            "worst_broad_overshoot_deg": float(np.max(overshoot)),
            "highest_frequency_error_deg": highest_frequency_error,
            "highest_frequency_half_angle_deg": float(smooth[-1]),
            "highest_frequency_undershoot_deg": max(0.0, -highest_frequency_error),
            "highest_frequency_overshoot_deg": max(0.0, highest_frequency_error),
            "lower_half_angle_deg": float(values[0]),
            "upper_half_angle_deg": float(values[-1]),
        }
    dimensions = run.get("mouth_dimensions_mm", {})
    raw_weights = np.asarray([
        float(dimensions.get("horizontal", 1.0)),
        float(dimensions.get("vertical", 1.0)),
    ])
    if np.any(raw_weights <= 0) or not np.all(np.isfinite(raw_weights)):
        raw_weights = np.ones(2)
    weights = raw_weights / np.sum(raw_weights)
    horizontal_weight, vertical_weight = map(float, weights)
    weighted = lambda key: (horizontal_weight * plane_results["horizontal"][key] +
                            vertical_weight * plane_results["vertical"][key])
    combined_error = lambda key: float(np.sqrt(
        horizontal_weight * plane_results["horizontal"][key] ** 2 +
        vertical_weight * plane_results["vertical"][key] ** 2))
    combined_total_error = combined_error("weighted_total_error_percent")
    combined_smoothness_error = combined_error("smoothness_error_percent")
    combined_waistbanding_error = combined_error("waistbanding_error_percent")
    combined_window_rms_deviation = combined_error("window_rms_deviation_db")
    combined_window_positive_rms = combined_error("window_positive_rms_db")
    combined_window_uniformity_error = (
        COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB * combined_window_rms_deviation +
        COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB * combined_window_positive_rms)
    return {
        "status": "available",
        "passband_lower_hz": float(evaluated_frequencies[0]),
        "passband_upper_hz": float(evaluated_frequencies[-1]),
        "band_kind": band_kind,
        "confirmation_octaves": PASSBAND_CONFIRMATION_OCTAVES,
        "axis_weights": {"horizontal": horizontal_weight,
                         "vertical": vertical_weight},
        "horizontal": plane_results["horizontal"],
        "vertical": plane_results["vertical"],
        "combined": {
            "coverage_match_percent": max(0.0, 100.0 - combined_total_error),
            "coverage_smoothness_percent": max(0.0, 100.0 - combined_smoothness_error),
            "waist_stability_percent": max(0.0, 100.0 - combined_waistbanding_error),
            "window_uniformity_percent": max(
                0.0, 100.0 - combined_window_uniformity_error),
            "waistbanding_error_percent": combined_waistbanding_error,
            "waist_detected": (plane_results["horizontal"]["waist_detected"] or
                               plane_results["vertical"]["waist_detected"]),
            "waist_undershoot_deg": weighted("waist_undershoot_deg"),
            "waist_region_lower_hz": waist_region_lower_hz,
            "waist_region_upper_hz": waist_region_upper_hz,
            "waist_region_octaves": COVERAGE_WAIST_REGION_OCTAVES,
            "waist_min_undershoot_percent": COVERAGE_WAIST_MIN_UNDERSHOOT_PERCENT,
            "weighted_total_error_percent": combined_total_error,
            "weighted_undershoot_error_percent": combined_error(
                "weighted_undershoot_error_percent"),
            "weighted_overshoot_error_percent": combined_error(
                "weighted_overshoot_error_percent"),
            "smoothness_error_percent": combined_smoothness_error,
            "smoothness_raw_error_percent": combined_error(
                "smoothness_raw_error_percent"),
            "fine_ripple_error_percent": combined_error("fine_ripple_error_percent"),
            "broad_wiggle_error_percent": combined_error("broad_wiggle_error_percent"),
            "smoothness_score_gain": COVERAGE_SMOOTHNESS_SCORE_GAIN,
            "ripple_rms_deg": combined_error("ripple_rms_deg"),
            "broad_wiggle_rms_deg": combined_error("broad_wiggle_rms_deg"),
            "window_probe_fraction": COVERAGE_WINDOW_PROBE_FRACTION,
            "window_probe_angle_deg": weighted("window_probe_angle_deg"),
            "window_probe_mean_db": weighted("window_probe_mean_db"),
            "window_rms_deviation_db": combined_window_rms_deviation,
            "window_peak_deviation_db": combined_error("window_peak_deviation_db"),
            "window_p90_deviation_db": combined_error("window_p90_deviation_db"),
            "window_uniformity_score_per_db": COVERAGE_WINDOW_UNIFORMITY_SCORE_PER_DB,
            "window_uniformity_error_points": combined_window_uniformity_error,
            "window_positive_error_points": (
                COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB *
                combined_window_positive_rms),
            "window_positive_rms_db": combined_window_positive_rms,
            "window_positive_mean_db": weighted("window_positive_mean_db"),
            "window_positive_peak_db": combined_error("window_positive_peak_db"),
            "window_positive_peak_angle_deg": weighted(
                "window_positive_peak_angle_deg"),
            "window_positive_band_fraction": weighted(
                "window_positive_band_fraction"),
            "window_positive_score_per_db": COVERAGE_WINDOW_POSITIVE_SCORE_PER_DB,
            "worst_broad_undershoot_deg": weighted("worst_broad_undershoot_deg"),
            "worst_broad_overshoot_deg": weighted("worst_broad_overshoot_deg"),
            "highest_frequency_error_deg": weighted("highest_frequency_error_deg"),
            "highest_frequency_half_angle_deg": weighted(
                "highest_frequency_half_angle_deg"),
        },
    }


def comparison_diagnostics(runs: list[dict[str, Any]]) -> tuple[dict[str, Any], np.ndarray]:
    """Recompute all run diagnostics on one shared logarithmic frequency grid."""
    automatic = [coverage_diagnostics(run) for run in runs]
    unavailable = [item for item in automatic if item["status"] != "available"]
    if unavailable:
        raise ValueError("cannot establish comparison passband: " +
                         "; ".join(item["reason"] for item in unavailable))
    lower = max(item["passband_lower_hz"] for item in automatic)
    upper = min(item["passband_upper_hz"] for item in automatic)
    if upper <= lower:
        raise ValueError("compared runs have no overlapping valid passband")
    intervals = max(2, int(np.ceil(np.log2(upper / lower) * 48)))
    grid = np.geomspace(lower, upper, intervals + 1)
    diagnostics = {
        run["name"]: coverage_diagnostics(run, grid) for run in runs
    }
    return diagnostics, grid


def _frequency_axis(frequencies: np.ndarray) -> dict[str, Any]:
    minimum = float(np.min(frequencies))
    maximum = float(np.max(frequencies))
    tick_values = []
    for exponent in range(int(np.floor(np.log10(minimum))) - 1,
                          int(np.ceil(np.log10(maximum))) + 1):
        for multiplier in (1, 2, 5):
            value = multiplier * 10.0 ** exponent
            if minimum * (1 - 1e-12) <= value <= maximum * (1 + 1e-12):
                tick_values.append(value)
    for endpoint in (minimum, maximum):
        if not any(np.isclose(endpoint, value, rtol=1e-12) for value in tick_values):
            tick_values.append(endpoint)
    tick_values.sort()
    tick_text = [f"{value / 1000:g}k" if value >= 1000 else f"{value:g}"
                 for value in tick_values]
    return {
        "type": "log", "title_text": "Frequency (Hz)",
        "tickmode": "array", "tickvals": tick_values, "ticktext": tick_text,
        "ticks": "outside", "ticklen": 6,
        "showgrid": True, "gridcolor": "rgba(70,85,110,0.34)",
        "gridwidth": 1.2, "zeroline": False,
        "minor": {"dtick": "D1", "ticks": "inside", "ticklen": 3,
                  "showgrid": True, "gridcolor": "rgba(70,85,110,0.14)",
                  "griddash": "dot"},
    }


def _frequency_grid_values(frequencies: np.ndarray) -> tuple[list[float], list[float]]:
    axis = _frequency_axis(frequencies)
    major = [float(value) for value in axis["tickvals"]]
    minimum = float(np.min(frequencies))
    maximum = float(np.max(frequencies))
    fine = []
    for exponent in range(int(np.floor(np.log10(minimum))) - 1,
                          int(np.ceil(np.log10(maximum))) + 1):
        for multiplier in range(1, 10):
            value = multiplier * 10.0 ** exponent
            if (minimum < value < maximum and
                    not any(np.isclose(value, tick, rtol=1e-12) for tick in major)):
                fine.append(value)
    return major, fine


def _parameter_table(runs: list[dict[str, Any]]) -> str:
    def cell(value: Any) -> str:
        return html.escape(str(value)).replace(" / ", "&nbsp;/<wbr> ")

    keys = list(dict.fromkeys(key for run in runs for key in run["parameters"]))
    header = "<tr><th>Parameter</th>" + "".join(
        f"<th style='color:{COLORS[i]}'>{html.escape(run['name'])}</th>"
        for i, run in enumerate(runs)) + "</tr>"
    rows = "".join("<tr><td>" + cell(key) + "</td>" + "".join(
        f"<td>{cell(run['parameters'].get(key, '—'))}</td>" for run in runs)
        + "</tr>" for key in keys)
    return f"<table>{header}{rows}</table>"


DIAGNOSTIC_ROWS = (("Coverage Match", "coverage_match_percent"),
                   ("Coverage Smoothness", "coverage_smoothness_percent"),
                   ("Waist Stability", "waist_stability_percent"),
                   ("Window Uniformity", "window_uniformity_percent"))


def _score_cell(value: float) -> str:
    strength = "strong" if value >= 80 else "moderate" if value >= 60 else "weak"
    return (f"<td class='score {strength}'><span>{value:.1f}%</span>"
            f"<i style='width:{value:.1f}%'></i></td>")


def _diagnostic_tables(runs: list[dict[str, Any]],
                       diagnostics: dict[str, Any], comparison: bool) -> str:
    first = diagnostics[runs[0]["name"]]
    if first["status"] != "available":
        return f"<p>{html.escape(first['reason'])}</p>"
    band = f"{first['passband_lower_hz']:g}–{first['passband_upper_hz']:g} Hz"
    if comparison:
        sections = []
        header = "<th>Diagnostic</th>" + "".join(
            f"<th style='color:{COLORS[index]}'>{html.escape(run['name'])}</th>"
            for index, run in enumerate(runs))
        for label, plane in (("Combined", "combined"), ("Horizontal", "horizontal"),
                             ("Vertical", "vertical")):
            rows = "".join(
                f"<tr><th>{name}</th>" + "".join(
                    _score_cell(diagnostics[run["name"]][plane][key]) for run in runs) +
                "</tr>" for name, key in DIAGNOSTIC_ROWS)
            sections.append(f"<div class='diagnostic-card'><h3>{label}</h3>"
                            f"<table><tr>{header}</tr>{rows}</table></div>")
        return (f"<p class='diagnostic-band'><strong>Common evaluated band:</strong> "
                f"{band}</p><div class='diagnostic-grid'>{''.join(sections)}</div>")

    diagnostic = first
    weights = diagnostic.get("axis_weights", {"horizontal": .5, "vertical": .5})
    header = "<th>Diagnostic</th><th>Combined</th><th>Horizontal</th><th>Vertical</th>"
    rows = "".join(
        f"<tr><th>{name}</th>" + "".join(
            _score_cell(diagnostic[plane][key])
            for plane in ("combined", "horizontal", "vertical")) + "</tr>"
        for name, key in DIAGNOSTIC_ROWS)
    return (f"<p class='diagnostic-band'><strong>Evaluated band:</strong> {band}. "
            f"<strong>Combined H/V weights:</strong> "
            f"{100 * weights['horizontal']:.1f}%&nbsp;/<wbr> "
            f"{100 * weights['vertical']:.1f}% "
            "from mouth width/height.</p>"
            f"<table><tr>{header}</tr>{rows}</table>")


def _surface_diagnostic_tables(runs: list[dict[str, Any]],
                               diagnostics: dict[str, Any]) -> str:
    def value(number: float | None, suffix: str = "", scale: float = 1.0) -> str:
        if number is None or not np.isfinite(number):
            return "—"
        return f"{number * scale:.3g}{suffix}"

    sections = []
    for run in runs:
        result = diagnostics[run["name"]]
        if result["status"] != "available":
            sections.append(
                f"<div class='diagnostic-card'><h3>{html.escape(run['name'])}</h3>"
                f"<p>{html.escape(result['reason'])}</p></div>")
            continue
        score = result.get("score") or surface_score(
            result, run.get("mouth_dimensions_mm"))
        rows = [("Final surface score",
                 value(score["overall_percent"], "%") if score else "—")]
        for label, plane_name in (("Horizontal", "horizontal"),
                                  ("Vertical", "vertical")):
            plane = result[plane_name]
            containment = plane["containment"]
            distribution = plane["distribution"]
            stability = plane["slice_energy_stability"]
            line = plane["minus_six_line"]
            rows.extend((
                (f"{label} mean containment",
                 value(containment["mean_fraction"], "%", 100)),
                (f"{label} profile RMS error",
                 value(distribution["rms_profile_error_db"], " dB")),
                (f"{label} outward-rise violation",
                 value(distribution["rms_outward_rise_violation_db"], " dB")),
                (f"{label} slice-energy RMS departure",
                 value(stability["rms_departure_db"], " dB")),
                (f"{label} slice-energy peak-to-peak",
                 value(stability["peak_to_peak_db"], " dB")),
                (f"{label} −6 dB RMS coverage error",
                 value(line["rms_coverage_error_deg"], "°")),
                (f"{label} missing −6 dB crossings",
                 value(line["missing_fraction"], "%", 100)),
            ))
        table_rows = "".join(
            f"<tr><th>{html.escape(label)}</th><td>{measurement}</td></tr>"
            for label, measurement in rows)
        sections.append(
            f"<div class='diagnostic-card'><h3>{html.escape(run['name'])}</h3>"
            f"<p><strong>Evaluated band:</strong> {result['band_lower_hz']:g}–"
            f"{result['band_upper_hz']:g} Hz</p><table>{table_rows}</table></div>")
    return f"<div class='surface-summary'>{''.join(sections)}</div>"


def _surface_diagnostic_plot(runs: list[dict[str, Any]],
                             diagnostics: dict[str, Any]) -> str:
    figure = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        subplot_titles=("Coverage-window containment",
                        "In-window profile RMS error",
                        "Angular slice-energy departure",
                        "−6 dB coverage-angle error"),
        vertical_spacing=.07)
    dash = {"horizontal": "solid", "vertical": "dash"}
    for run_index, run in enumerate(runs):
        result = diagnostics[run["name"]]
        if result["status"] != "available":
            continue
        for plane_name, plane_label in (("horizontal", "H"), ("vertical", "V")):
            traces = result[plane_name]["traces"]
            frequency = traces["frequencies_hz"]
            name = f"{run['name']} {plane_label}"
            common = {
                "x": frequency, "mode": "lines", "name": name,
                "legendgroup": name, "line": {
                    "color": COLORS[run_index % len(COLORS)],
                    "dash": dash[plane_name], "width": 2.2},
            }
            figure.add_trace(go.Scatter(
                **common, y=np.asarray(traces["containment_fraction"]) * 100,
                showlegend=True,
                hovertemplate="%{x:.1f} Hz<br>%{y:.2f}%<extra>" +
                              html.escape(name) + "</extra>"), row=1, col=1)
            figure.add_trace(go.Scatter(
                **common, y=traces["profile_rms_error_db"], showlegend=False,
                hovertemplate="%{x:.1f} Hz<br>%{y:.3f} dB<extra>" +
                              html.escape(name) + "</extra>"), row=2, col=1)
            figure.add_trace(go.Scatter(
                **common, y=traces["slice_energy_departure_db"], showlegend=False,
                hovertemplate="%{x:.1f} Hz<br>%{y:.3f} dB<extra>" +
                              html.escape(name) + "</extra>"), row=3, col=1)
            figure.add_trace(go.Scatter(
                **common, y=traces["minus_six_error_deg"], showlegend=False,
                hovertemplate="%{x:.1f} Hz<br>%{y:.3f}°<extra>" +
                              html.escape(name) + "</extra>"), row=4, col=1)
    reference_line = {"color": "#69d6c8", "dash": "dash", "width": 1.8}
    for row, value, label in (
        (1, 100, "Best: 100%"),
        (2, 0, "Best: 0 dB"),
        (3, 0, "Best: 0 dB"),
        (4, 0, "Target: 0°"),
    ):
        figure.add_hline(
            y=value, row=row, col=1, line=reference_line,
            annotation_text=label, annotation_position="top right",
            annotation_font={"color": "#69d6c8", "size": 11})
    all_frequencies = np.concatenate([
        np.asarray(run["frequencies"], dtype=float) for run in runs])
    figure.update_xaxes(**_frequency_axis(all_frequencies))
    figure.update_yaxes(title_text="Contained power (%)", row=1, col=1)
    figure.update_yaxes(title_text="RMS error (dB)", rangemode="tozero", row=2, col=1)
    figure.update_yaxes(title_text="Departure (dB)", rangemode="tozero", row=3, col=1)
    figure.update_yaxes(title_text="Angle error (degrees)", row=4, col=1)
    figure.update_layout(
        height=980, hovermode="x unified", template="plotly_dark",
        paper_bgcolor="#121820", plot_bgcolor="#161f29",
        font={"color": "#e5edf2"}, legend={"orientation": "h"})
    return figure.to_html(
        full_html=False, include_plotlyjs=False,
        config={"displaylogo": False, "scrollZoom": True, "responsive": True})


def _embedded_stl_viewer(path: Path, triangle_limit: int = 50000) -> str:
    """Return a self-contained canvas preview for an adjacent candidate STL."""
    candidate_dir = path.parent.parent
    if path.parent.name != "bem" or not candidate_dir.is_dir():
        return ""
    stl_paths = sorted(candidate_dir.glob("*_Surface.STL"))
    if not stl_paths:
        stl_paths = sorted(candidate_dir.glob("*_Body.STL"))
    if not stl_paths:
        return ""
    stl_path = stl_paths[0]
    payload = stl_path.read_bytes()
    if len(payload) < 84:
        return ""
    triangle_count = int.from_bytes(payload[80:84], "little")
    if triangle_count < 1 or len(payload) < 84 + triangle_count * 50:
        return ""
    record_type = np.dtype({
        "names": ["normal", "vertices", "attribute"],
        "formats": [("<f4", 3), ("<f4", (3, 3)), "<u2"],
        "offsets": [0, 12, 48],
        "itemsize": 50,
    })
    records = np.frombuffer(payload, dtype=record_type, count=triangle_count,
                            offset=84)
    if triangle_count > triangle_limit:
        indices = np.linspace(0, triangle_count - 1, triangle_limit, dtype=int)
        vertices = records["vertices"][indices]
    else:
        vertices = records["vertices"]
    encoded = base64.b64encode(
        np.asarray(vertices, dtype="<f4").tobytes()).decode("ascii")
    stl_name = html.escape(stl_path.name)
    viewer = """
<section class='model-viewer'><div class='model-viewer-heading'><div><h2>Horn STL</h2><p class='hint'>Drag to orbit · wheel to zoom</p></div><a href='../__STL_NAME__'>STL</a></div>
<canvas class='stl-canvas' aria-label='Interactive STL preview'></canvas></section>
<script>
(() => {
  const canvas = document.currentScript.previousElementSibling.querySelector('.stl-canvas');
  const ctx = canvas.getContext('2d');
  const binary = atob('__STL_DATA__');
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const values = new Float32Array(bytes.buffer);
  const points = [];
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (let i = 0; i < values.length; i += 3) {
    const point = {x: values[i], y: values[i + 1], z: values[i + 2]};
    points.push(point);
    minX = Math.min(minX, point.x); maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y); maxY = Math.max(maxY, point.y);
    minZ = Math.min(minZ, point.z); maxZ = Math.max(maxZ, point.z);
  }
  const center = {x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2};
  const span = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1);
  const view = {yaw: -0.7, pitch: 0.42, zoom: 1, dragging: false, x: 0, y: 0};
  const rotate = (point) => {
    const x = point.x - center.x, y = point.y - center.y, z = point.z - center.z;
    const cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    const cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    const rx = x * cy + z * sy;
    const rz = -x * sy + z * cy;
    return {x: rx, y: y * cp - rz * sp, z: y * sp + rz * cp};
  };
  const render = () => {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(280, rect.width), height = Math.max(220, rect.height);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const scale = Math.min(width, height) * 0.78 * view.zoom / span;
    ctx.strokeStyle = 'rgba(105, 214, 200, 0.52)';
    ctx.lineWidth = 0.55;
    ctx.beginPath();
    for (let i = 0; i < points.length; i += 3) {
      const p = [rotate(points[i]), rotate(points[i + 1]), rotate(points[i + 2])];
      p.forEach((point, index) => {
        const x = width / 2 + point.x * scale;
        const y = height / 2 - point.y * scale;
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.closePath();
    }
    ctx.stroke();
  };
  canvas.addEventListener('pointerdown', (event) => {
    view.dragging = true; view.x = event.clientX; view.y = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!view.dragging) return;
    view.yaw += (event.clientX - view.x) * 0.009;
    view.pitch = Math.max(-1.45, Math.min(1.45, view.pitch + (event.clientY - view.y) * 0.009));
    view.x = event.clientX; view.y = event.clientY; render();
  });
  canvas.addEventListener('pointerup', () => { view.dragging = false; });
  canvas.addEventListener('pointercancel', () => { view.dragging = false; });
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    view.zoom = Math.max(0.35, Math.min(4, view.zoom * Math.exp(-event.deltaY * 0.001)));
    render();
  }, {passive: false});
  new ResizeObserver(render).observe(canvas); render();
})();
</script>"""
    return viewer.replace("__STL_NAME__", stl_name).replace("__STL_DATA__", encoded)


def _write_html(path: Path, title: str, figure: go.Figure,
                runs: list[dict[str, Any]], diagnostics: dict[str, Any] | None = None,
                comparison: bool = False,
                surface_results: dict[str, Any] | None = None) -> Path:
    if diagnostics is None:
        diagnostics = {run["name"]: coverage_diagnostics(run) for run in runs}
    if surface_results is None:
        surface_results = {run["name"]: surface_diagnostics(run) for run in runs}
    figure.update_layout(template="plotly_dark", paper_bgcolor="#121820",
                         plot_bgcolor="#161f29", font={"color": "#e5edf2"})
    plot = figure.to_html(full_html=False, include_plotlyjs=True,
                          config={"displaylogo": False, "scrollZoom": True,
                                  "responsive": True})
    surface_plot = _surface_diagnostic_plot(runs, surface_results)
    stl_viewer = _embedded_stl_viewer(path)
    document = f"""<!doctype html><html><head><meta charset='utf-8'><!-- report-schema: canonical-v8 -->
<title>{html.escape(title)}</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#4db6a8;--accent-strong:#69d6c8}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
main{{width:100%;padding:18px}} h1{{margin:0 0 12px}}
.plot,.parameters{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:16px}}
.model-viewer{{width:min(460px,100%);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:16px}}
.model-viewer-heading{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}}.model-viewer h2{{margin:0 0 3px}}.model-viewer .hint{{margin:0}}.stl-canvas{{display:block;width:100%;height:280px;margin-top:10px;border-radius:7px;background:#0a0f13;cursor:grab;touch-action:none}}.stl-canvas:active{{cursor:grabbing}}
table{{border-collapse:collapse;width:100%;min-width:max-content}} th,td{{padding:7px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}
th{{background:var(--panel-2);position:sticky;top:0}} .hint{{color:var(--muted);margin:0 0 12px}}
.parameters{{overflow-x:auto}}.plotly-graph-div{{width:100%!important}}
.diagnostic-band{{font-size:1.05rem}} .diagnostic-grid{{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:14px}}.surface-summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}}
.diagnostic-card{{border:1px solid var(--line);border-radius:8px;padding:0 10px 10px}} .diagnostic-card h3{{margin:10px 0}}
.score{{position:relative;min-width:85px}} .score span{{position:relative;z-index:1;font-variant-numeric:tabular-nums}}
.score i{{position:absolute;left:0;bottom:2px;height:4px;border-radius:2px;background:#64748b}}
.score.strong i{{background:#16856b}} .score.moderate i{{background:#b7791f}} .score.weak i{{background:#b45353}}
.plotly-graph-div.wheel-armed{{outline:2px solid var(--accent);outline-offset:2px}}
@media(max-width:950px){{.diagnostic-grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>{html.escape(title)}</h1>
<p class='hint'>Hover for exact coordinates. Click a chart to enable mouse-wheel zoom; click outside it to restore page scrolling. Drag to zoom; double-click to reset; use the legend to hide traces.</p>
{stl_viewer}
<section class='plot'>{plot}</section><section class='parameters'><h2>Horn acoustic parameters</h2>
{_parameter_table(runs)}</section><section class='parameters'><h2>Surface diagnostics</h2>
{_surface_diagnostic_tables(runs, surface_results)}
<p class='hint'>The final surface score weights profile RMS error 30%, slice-energy departure 25%, mean containment 20%, outward-rise violation 15%, and the secondary −6 dB line 10%. Containment integrates relative power inside the intended coverage half-angle. Profile error compares the in-window surface with a straight 0 to −6 dB angular falloff.</p>
</section><section class='plot'>{surface_plot}</section></main><script>
(() => {{
  let armed = null;
  const disarm = () => {{
    if (armed) armed.classList.remove("wheel-armed");
    armed = null;
  }};
  document.querySelectorAll(".plotly-graph-div").forEach((plot) => {{
    plot.addEventListener("click", () => {{
      if (armed !== plot) {{
        disarm();
        armed = plot;
        armed.classList.add("wheel-armed");
      }}
    }}, true);
  }});
  document.addEventListener("click", (event) => {{
    if (armed && !armed.contains(event.target)) disarm();
  }}, true);
  document.addEventListener("wheel", (event) => {{
    const plot = event.target.closest?.(".plotly-graph-div");
    if (plot && plot !== armed) event.stopImmediatePropagation();
  }}, {{capture: true, passive: true}});
}})();
</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document)
    diagnostics_path = path.with_name("coverage_diagnostics.json")
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
    surface_path = path.with_name("surface_diagnostics.json")
    surface_path.write_text(json.dumps(surface_results, indent=2) + "\n")
    return path


def single_report(run_dir: Path, output: Path | None = None,
                  title: str | None = None,
                  evaluation_frequencies: np.ndarray | None = None,
                  fixed_band: bool = False,
                  name: str | None = None) -> Path:
    run = load_run(run_dir, name)
    figure = make_subplots(rows=2, cols=2,
                           specs=[[{}, {}], [{"colspan": 2}, None]],
                           subplot_titles=("Horizontal coverage", "Vertical coverage",
                                           "Normalized throat impedance magnitude"),
                           vertical_spacing=.12)
    for column, key in enumerate(("horizontal", "vertical"), 1):
        figure.add_trace(go.Heatmap(
            x=run["frequencies"], y=run["angles"], z=run[key].T,
            coloraxis="coloraxis",
            hovertemplate="%{x:.1f} Hz<br>%{y:.1f}°<br>%{z:.2f} dB<extra></extra>"),
            row=1, col=column)
        figure.add_trace(go.Contour(
            x=run["frequencies"], y=run["angles"], z=run[key].T,
            contours={"start": -6, "end": -6, "size": 1, "coloring": "lines",
                      "showlabels": True, "labelfont": {"color": "white"}},
            line={"color": "white", "width": 3}, showscale=False,
            name=f"{key.title()} −6 dB", showlegend=True,
            hoverinfo="skip"),
            row=1, col=column)
        intended = run["intended_coverages"].get(key)
        if intended:
            start, stop = run["frequencies"][[0, -1]]
            figure.add_trace(go.Scatter(
                x=[start, stop, None, start, stop],
                y=[intended, intended, None, -intended, -intended],
                mode="lines", name=f"{key.title()} intended coverage ±{intended:g}°",
                line={"color": "#00ffff", "width": 3, "dash": "dash"},
                hoverinfo="skip"),
                row=1, col=column)
    if run["normalized_impedance"] is not None:
        figure.add_trace(go.Scatter(
            x=run["frequencies"], y=np.abs(run["normalized_impedance"]), mode="lines",
            name="|Z throat| / (ρc/Sₜ)", line={"width": 2.5},
            hovertemplate="%{x:.1f} Hz<br>%{y:.4g}<extra></extra>"),
            row=2, col=1)
    major_frequencies, fine_frequencies = _frequency_grid_values(run["frequencies"])
    for column in (1, 2):
        for frequency in fine_frequencies:
            figure.add_vline(
                x=frequency, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.30)", "width": .8,
                      "dash": "dot"})
        for frequency in major_frequencies:
            figure.add_vline(
                x=frequency, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.52)", "width": 1.2})
        for angle in (-90, -60, -30, 0, 30, 60, 90):
            figure.add_hline(
                y=angle, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.48)",
                      "width": 1.4 if angle == 0 else 1.0})
    figure.update_xaxes(**_frequency_axis(run["frequencies"]))
    figure.update_yaxes(
        title_text="Off-axis angle (degrees)", row=1,
        tickmode="array", tickvals=[-90, -60, -30, 0, 30, 60, 90],
        ticks="outside", ticklen=6, showgrid=True,
        gridcolor="rgba(70,85,110,0.30)", gridwidth=1.2, zeroline=True,
        zerolinecolor="rgba(30,45,70,0.55)", zerolinewidth=1.5)
    figure.update_yaxes(title_text="|Z| / (ρc/Sₜ)", row=2, col=1)
    figure.update_layout(
        height=1000, hovermode="closest",
        coloraxis={"cmin": -30, "cmax": 0, "colorscale": "Turbo",
                   "colorbar": {"title": "dB", "x": 1.015, "y": .78,
                                "len": .42, "thickness": 16}},
        legend={"orientation": "h", "x": 0, "xanchor": "left",
                "y": 1.12, "yanchor": "bottom"},
        margin={"t": 145, "r": 95, "b": 75, "l": 80})
    diagnostics = None
    if evaluation_frequencies is not None:
        diagnostics = {run["name"]: coverage_diagnostics(
            run, evaluation_frequencies, fixed_band=fixed_band)}
    surface_results = {run["name"]: surface_diagnostics(
        run, evaluation_frequencies, fixed_band=fixed_band)}
    return _write_html(output or run_dir / "interactive_report.html",
                       title or run["name"], figure, [run], diagnostics,
                       surface_results=surface_results)


def comparison_report(run_dirs: list[Path], output: Path,
                      names: list[str] | None = None,
                      title: str = "Horn comparison",
                      evaluation_frequencies: np.ndarray | None = None,
                      fixed_band: bool = False) -> Path:
    if not 2 <= len(run_dirs) <= 4:
        raise ValueError("comparison requires two to four runs")
    if names is not None and len(names) != len(run_dirs):
        raise ValueError("--names must contain one name per run")
    runs = [load_run(path, names[i] if names else None)
            for i, path in enumerate(run_dirs)]
    figure = make_subplots(rows=1, cols=3,
                           subplot_titles=("Horizontal −6 dB half-angle",
                                           "Vertical −6 dB half-angle",
                                           "Normalized throat impedance magnitude"))
    for index, run in enumerate(runs):
        color = COLORS[index]
        for column, key in enumerate(("horizontal", "vertical"), 1):
            figure.add_trace(go.Scatter(
                x=run["frequencies"],
                y=_positive_half_angle(run["angles"], run[key]),
                mode="lines+markers", name=run["name"], legendgroup=run["name"],
                showlegend=column == 1, line={"color": color, "width": 2.5},
                hovertemplate="%{x:.1f} Hz<br>%{y:.2f}°<extra>" +
                              html.escape(run["name"]) + "</extra>"), row=1, col=column)
        if run["normalized_impedance"] is not None:
            figure.add_trace(go.Scatter(
                x=run["frequencies"], y=np.abs(run["normalized_impedance"]), mode="lines",
                name=run["name"], legendgroup=run["name"], showlegend=False,
                line={"color": color, "width": 2.5},
                hovertemplate="%{x:.1f} Hz<br>%{y:.4g}<extra>" +
                              html.escape(run["name"]) + "</extra>"), row=1, col=3)
    all_frequencies = np.concatenate([run["frequencies"] for run in runs])
    figure.update_xaxes(**_frequency_axis(all_frequencies))
    figure.update_yaxes(title_text="Half-angle (degrees)", range=[0, 90], row=1, col=1)
    figure.update_yaxes(title_text="Half-angle (degrees)", range=[0, 90], row=1, col=2)
    figure.update_yaxes(title_text="|Z| / (ρc/Sₜ)", row=1, col=3)
    figure.update_layout(height=620, hovermode="closest", legend={"orientation": "h"})
    if evaluation_frequencies is None:
        diagnostics, _ = comparison_diagnostics(runs)
    else:
        diagnostics = {run["name"]: coverage_diagnostics(
            run, evaluation_frequencies, fixed_band=fixed_band) for run in runs}
    surface_results = {run["name"]: surface_diagnostics(
        run, evaluation_frequencies, fixed_band=fixed_band) for run in runs}
    return _write_html(output, title, figure, runs, diagnostics, comparison=True,
                       surface_results=surface_results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("run_dir", type=Path)
    report.add_argument("--output", type=Path)
    report.add_argument("--title")
    compare = subparsers.add_parser("compare")
    compare.add_argument("run_dirs", nargs="+", type=Path)
    compare.add_argument("--output", required=True, type=Path)
    compare.add_argument("--names", nargs="+")
    compare.add_argument("--title", default="Horn comparison")
    args = parser.parse_args()
    if args.command == "report":
        print(single_report(args.run_dir, args.output, args.title))
    else:
        print(comparison_report(args.run_dirs, args.output, args.names, args.title))


if __name__ == "__main__":
    main()
