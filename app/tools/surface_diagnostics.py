"""Raw angle-frequency surface diagnostics for HornCAD BEM results."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np


OCTAVE_WINDOWS = (1 / 12, 1 / 6, 1 / 3, 2 / 3)


def _band_mean(x: np.ndarray, values: np.ndarray) -> float:
    if len(values) == 1 or x[-1] <= x[0]:
        return float(values[0])
    return float(np.trapezoid(values, x) / (x[-1] - x[0]))


def _band_rms(x: np.ndarray, values: np.ndarray) -> float:
    return float(np.sqrt(max(0.0, _band_mean(x, np.asarray(values) ** 2))))


def _interval_mean(x: np.ndarray, values: np.ndarray,
                   lower: float, upper: float) -> float:
    if upper <= lower:
        return float(np.interp(lower, x, values))
    interior = (x > lower) & (x < upper)
    sample_x = np.concatenate(([lower], x[interior], [upper]))
    sample_y = np.interp(sample_x, x, values)
    return float(np.trapezoid(sample_y, sample_x) / (upper - lower))


def _moving_trace(x: np.ndarray, values: np.ndarray,
                  width_octaves: float) -> tuple[np.ndarray, np.ndarray]:
    """Return centered moving means on a log2-frequency coordinate."""
    if x[-1] - x[0] <= width_octaves:
        return np.asarray([(x[0] + x[-1]) / 2]), np.asarray([
            _band_mean(x, values)
        ])
    half = width_octaves / 2
    centers = x[(x >= x[0] + half) & (x <= x[-1] - half)]
    if len(centers) == 0:
        centers = np.asarray([(x[0] + x[-1]) / 2])
    means = np.asarray([
        _interval_mean(x, values, center - half, center + half)
        for center in centers
    ])
    return centers, means


def _window_key(width: float) -> str:
    fraction = Fraction(width).limit_denominator(12)
    return f"{fraction.numerator}/{fraction.denominator} octave"


def _worst_window_summaries(x: np.ndarray, values: np.ndarray) -> dict[str, Any]:
    output: dict[str, Any] = {
        "raw": {
            "minimum": float(np.min(values)),
            "frequency_hz": float(2 ** x[int(np.argmin(values))]),
        }
    }
    for width in OCTAVE_WINDOWS:
        centers, means = _moving_trace(x, values, width)
        index = int(np.argmin(means))
        output[_window_key(width)] = {
            "minimum": float(means[index]),
            "center_frequency_hz": float(2 ** centers[index]),
        }
    return output


def _multiscale_rms(x: np.ndarray, values: np.ndarray) -> dict[str, float]:
    output = {"raw": _band_rms(x, values)}
    for width in OCTAVE_WINDOWS:
        centers, means = _moving_trace(x, values, width)
        output[_window_key(width)] = _band_rms(centers, means)
    return output


def _frequency_grid(run: dict[str, Any],
                    evaluation_frequencies: np.ndarray | None,
                    fixed_band: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    order = np.argsort(np.asarray(run["frequencies"], dtype=float))
    source_frequencies = np.asarray(run["frequencies"], dtype=float)[order]
    if np.any(source_frequencies <= 0) or np.any(np.diff(source_frequencies) <= 0):
        raise ValueError("frequencies must be positive and unique")
    crossover = float(run.get("crossover_hz") or source_frequencies[0])
    lower = max(crossover, float(source_frequencies[0]))
    upper = float(source_frequencies[-1])
    if lower >= upper:
        raise ValueError("crossover must be below the upper sweep frequency")
    if evaluation_frequencies is None:
        selected = source_frequencies[(source_frequencies >= lower) &
                                      (source_frequencies <= upper)]
        target = np.unique(np.concatenate(([lower], selected, [upper])))
    else:
        target = np.asarray(evaluation_frequencies, dtype=float)
        if (target.ndim != 1 or len(target) < 2 or np.any(np.diff(target) <= 0)
                or np.any(target <= 0)):
            raise ValueError("evaluation frequencies must be increasing and positive")
        tolerance = 1e-10
        if (target[0] < lower * (1 - tolerance)
                or target[-1] > upper * (1 + tolerance)):
            if fixed_band:
                raise ValueError("evaluation frequencies are outside crossover-to-sweep band")
            raise ValueError("evaluation frequencies are outside available response data")
    return source_frequencies, order, target


def _interpolate_frequency(source_frequencies: np.ndarray, surface: np.ndarray,
                           target_frequencies: np.ndarray) -> np.ndarray:
    source_log = np.log(source_frequencies)
    target_log = np.log(target_frequencies)
    return np.column_stack([
        np.interp(target_log, source_log, surface[:, index])
        for index in range(surface.shape[1])
    ])


def _angular_grid(angles: np.ndarray, upper: float) -> np.ndarray:
    interior = angles[(angles > 0) & (angles < upper)]
    return np.unique(np.concatenate(([0.0], interior, [upper])))


def _first_minus_six_crossing(angles: np.ndarray, row: np.ndarray) -> float:
    for index in range(len(angles) - 1):
        left, right = row[index], row[index + 1]
        if left >= -6.0 and right < -6.0:
            return float(angles[index] + (-6.0 - left) /
                         (right - left) * (angles[index + 1] - angles[index]))
    return float("nan")


def _plane_diagnostics(frequencies: np.ndarray, angles: np.ndarray,
                       levels: np.ndarray, coverage: float) -> dict[str, Any]:
    if not 0 < coverage <= 90:
        raise ValueError("coverage half-angle must be between 0 and 90 degrees")
    if angles[0] > 0 or angles[-1] < 90:
        raise ValueError("surface diagnostics require angles spanning 0 through 90 degrees")
    log_frequency = np.log2(frequencies)
    full_angles = _angular_grid(angles, 90.0)
    window_angles = _angular_grid(angles, coverage)
    full_levels = np.asarray([
        np.interp(full_angles, angles, row) for row in levels
    ])
    window_levels = np.asarray([
        np.interp(window_angles, angles, row) for row in levels
    ])
    full_power = np.power(10.0, full_levels / 10.0)
    window_power = np.power(10.0, window_levels / 10.0)
    total_energy = 2.0 * np.trapezoid(full_power, full_angles, axis=1)
    inside_energy = 2.0 * np.trapezoid(window_power, window_angles, axis=1)
    containment = np.divide(inside_energy, total_energy,
                            out=np.zeros_like(inside_energy), where=total_energy > 0)

    ideal = -6.0 * window_angles / coverage
    profile_error = window_levels - ideal[None, :]
    profile_rms = np.sqrt(np.maximum(
        0.0, np.trapezoid(profile_error ** 2, window_angles, axis=1) / coverage))
    profile_peak = np.max(np.abs(profile_error), axis=1)
    gradient = np.gradient(window_levels, window_angles, axis=1)
    positive_gradient = np.maximum(gradient, 0.0)
    outward_rise = coverage * np.sqrt(np.maximum(
        0.0, np.trapezoid(positive_gradient ** 2, window_angles, axis=1) / coverage))

    mean_log_energy = _band_mean(log_frequency, np.log(total_energy))
    energy_departure_db = (10.0 / np.log(10.0)) * (
        np.log(total_energy) - mean_log_energy)

    crossings = np.asarray([
        _first_minus_six_crossing(full_angles, row) for row in full_levels
    ])
    crossing_valid = np.isfinite(crossings)
    coverage_error = np.where(crossing_valid, crossings - coverage, np.nan)
    movement = np.full_like(crossings, np.nan)
    for index in range(1, len(crossings)):
        if crossing_valid[index - 1] and crossing_valid[index]:
            octave_step = log_frequency[index] - log_frequency[index - 1]
            if octave_step > 0:
                movement[index] = ((crossings[index] - crossings[index - 1]) /
                                   octave_step)
    valid_error = coverage_error[np.isfinite(coverage_error)]
    valid_movement = movement[np.isfinite(movement)]
    worst_error_index = (int(np.nanargmax(np.abs(coverage_error)))
                         if len(valid_error) else None)
    high_index = int(np.argmax(energy_departure_db))
    low_index = int(np.argmin(energy_departure_db))

    return {
        "coverage_half_angle_deg": coverage,
        "traces": {
            "frequencies_hz": frequencies.tolist(),
            "containment_fraction": containment.tolist(),
            "profile_rms_error_db": profile_rms.tolist(),
            "profile_peak_error_db": profile_peak.tolist(),
            "outward_rise_violation_db": outward_rise.tolist(),
            "slice_energy": total_energy.tolist(),
            "slice_energy_departure_db": energy_departure_db.tolist(),
            "minus_six_half_angle_deg": crossings.tolist(),
            "minus_six_error_deg": coverage_error.tolist(),
        },
        "containment": {
            "mean_fraction": _band_mean(log_frequency, containment),
            "mean_deficit_fraction": _band_mean(log_frequency, 1.0 - containment),
            "worst_windows": _worst_window_summaries(
                log_frequency, containment),
        },
        "distribution": {
            "rms_profile_error_db": _band_rms(log_frequency, profile_rms),
            "worst_profile_error_db": float(np.max(profile_peak)),
            "worst_profile_error_frequency_hz": float(
                frequencies[int(np.argmax(profile_peak))]),
            "rms_outward_rise_violation_db": _band_rms(
                log_frequency, outward_rise),
            "worst_outward_rise_violation_db": float(np.max(outward_rise)),
            "worst_outward_rise_frequency_hz": float(
                frequencies[int(np.argmax(outward_rise))]),
        },
        "slice_energy_stability": {
            "rms_departure_db": _band_rms(log_frequency, energy_departure_db),
            "highest_departure_db": float(energy_departure_db[high_index]),
            "highest_departure_frequency_hz": float(frequencies[high_index]),
            "lowest_departure_db": float(energy_departure_db[low_index]),
            "lowest_departure_frequency_hz": float(frequencies[low_index]),
            "peak_to_peak_db": float(np.ptp(energy_departure_db)),
            "multiscale_rms_departure_db": _multiscale_rms(
                log_frequency, energy_departure_db),
        },
        "minus_six_line": {
            "missing_fraction": float(np.mean(~crossing_valid)),
            "rms_coverage_error_deg": (float(np.sqrt(np.mean(valid_error ** 2)))
                                       if len(valid_error) else None),
            "worst_coverage_error_deg": (float(coverage_error[worst_error_index])
                                         if worst_error_index is not None else None),
            "worst_coverage_error_frequency_hz": (
                float(frequencies[worst_error_index])
                if worst_error_index is not None else None),
            "rms_movement_deg_per_octave": (
                float(np.sqrt(np.mean(valid_movement ** 2)))
                if len(valid_movement) else None),
        },
    }


def surface_diagnostics(
        run: dict[str, Any], evaluation_frequencies: np.ndarray | None = None,
        fixed_band: bool = False,
) -> dict[str, Any]:
    """Measure raw heat-map behavior from crossover through the upper sweep."""
    source_frequencies, frequency_order, frequencies = _frequency_grid(
        run, evaluation_frequencies, fixed_band)
    all_angles = np.asarray(run["angles"], dtype=float)
    positive = all_angles >= 0
    angle_order = np.argsort(all_angles[positive])
    angles = all_angles[positive][angle_order]
    if len(angles) < 3:
        return {"status": "unavailable", "reason": "positive angle grid is incomplete"}
    targets = run.get("intended_coverages", {})
    planes = {}
    for key in ("horizontal", "vertical"):
        coverage = float(targets.get(key, 0))
        source_surface = np.asarray(run[key], dtype=float)[frequency_order][:, positive]
        source_surface = source_surface[:, angle_order]
        evaluated_surface = _interpolate_frequency(
            source_frequencies, source_surface, frequencies)
        try:
            planes[key] = _plane_diagnostics(
                frequencies, angles, evaluated_surface, coverage)
        except ValueError as error:
            return {"status": "unavailable", "reason": str(error)}
    return {
        "status": "available",
        "band_kind": "fixed shadow evaluation" if fixed_band else "shadow evaluation",
        "band_lower_hz": float(frequencies[0]),
        "band_upper_hz": float(frequencies[-1]),
        "horizontal": planes["horizontal"],
        "vertical": planes["vertical"],
    }
