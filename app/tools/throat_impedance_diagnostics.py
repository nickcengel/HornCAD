"""Experimental diagnostics for normalized throat impedance."""
from __future__ import annotations

from typing import Any

import numpy as np


POINTS_PER_OCTAVE = 48
DIAGNOSTIC_VERSION = "2.3.0"
CROSSOVER_TARGET_RATIO = 0.5
CROSSOVER_FULL_CREDIT_RATIO = 0.75
CROSSOVER_BAND_UPPER_RATIO = 2.0
CROSSOVER_LOADING_WEIGHTS = {
    "at_crossover": 0.50,
    "crossover_band": 0.50,
}
PEAK_PROMINENCE_ALLOWANCE_DB = 1.5
LOCAL_PEAK_WINDOW_OCTAVES = 1.0
SCORE_WEIGHTS = {
    "crossover_loading": 0.60,
    "peak_prominence": 0.20,
    "ripple": 0.10,
    "excess_variation": 0.07,
    "shelf_stability": 0.03,
}
ERROR_REFERENCES = {
    "peak_prominence_excess_db": 1.5,
    "ripple_rms_db": 1.0,
    "excess_variation_db_per_octave": 3.0,
    "shelf_rms_db": 1.0,
    "shelf_slope_db_per_octave": 1.0,
}


def _inverse_error_score(error: float, reference: float) -> float:
    return float(100.0 / (1.0 + (error / reference) ** 2))


def _trimmed_mean(values: np.ndarray, fraction: float = 0.10) -> float:
    ordered = np.sort(np.asarray(values, dtype=float))
    trim = min(int(np.floor(len(ordered) * fraction)), (len(ordered) - 1) // 2)
    retained = ordered[trim:len(ordered) - trim] if trim else ordered
    return float(np.mean(retained))


def _isotonic_non_decreasing(values: np.ndarray) -> np.ndarray:
    """Least-squares non-decreasing fit using pooled adjacent violators."""
    levels: list[float] = []
    weights: list[int] = []
    for value in np.asarray(values, dtype=float):
        levels.append(float(value))
        weights.append(1)
        while len(levels) >= 2 and levels[-2] > levels[-1]:
            weight = weights[-2] + weights[-1]
            level = (levels[-2] * weights[-2] + levels[-1] * weights[-1]) / weight
            levels[-2:] = [level]
            weights[-2:] = [weight]
    return np.concatenate([
        np.full(weight, level, dtype=float)
        for level, weight in zip(levels, weights)
    ])


def _short_smooth(values: np.ndarray, points_per_octave: int) -> np.ndarray:
    width = max(3, int(round(points_per_octave / 12)))
    if width % 2 == 0:
        width += 1
    width = min(width, len(values) if len(values) % 2 else len(values) - 1)
    if width < 3:
        return np.asarray(values, dtype=float)
    half = width // 2
    padded = np.pad(values, (half, half), mode="edge")
    return np.convolve(padded, np.ones(width) / width, mode="valid")


def _local_peak_prominence(
        frequencies: np.ndarray,
        magnitude: np.ndarray,
        upper_frequency_hz: float,
        points_per_octave: int) -> dict[str, float]:
    """Measure the strongest interior peak against its higher local shoulder."""
    span_octaves = float(np.log2(upper_frequency_hz / frequencies[0]))
    count = max(3, int(np.ceil(span_octaves * points_per_octave)) + 1)
    log_frequency = np.linspace(
        np.log2(frequencies[0]), np.log2(upper_frequency_hz), count)
    magnitude_db = np.interp(
        log_frequency,
        np.log2(frequencies),
        20.0 * np.log10(magnitude),
    )
    smoothed_db = _short_smooth(magnitude_db, points_per_octave)
    window = max(
        1, int(round(LOCAL_PEAK_WINDOW_OCTAVES * points_per_octave)))
    strongest = 0.0
    strongest_frequency = 0.0
    for index in range(1, len(smoothed_db) - 1):
        if not (
                smoothed_db[index] >= smoothed_db[index - 1]
                and smoothed_db[index] > smoothed_db[index + 1]):
            continue
        left_minimum = float(np.min(
            smoothed_db[max(0, index - window):index + 1]))
        right_minimum = float(np.min(
            smoothed_db[index:min(len(smoothed_db), index + window + 1)]))
        prominence = float(
            smoothed_db[index] - max(left_minimum, right_minimum))
        if prominence > strongest:
            strongest = prominence
            strongest_frequency = float(2.0 ** log_frequency[index])
    return {
        "maximum_db": strongest,
        "frequency_hz": strongest_frequency,
        "window_octaves": LOCAL_PEAK_WINDOW_OCTAVES,
    }


def throat_impedance_diagnostics(
        frequencies_hz: np.ndarray,
        normalized_impedance: np.ndarray,
        crossover_hz: float,
        upper_frequency_hz: float | None = None,
        points_per_octave: int = POINTS_PER_OCTAVE) -> dict[str, Any]:
    """Score magnitude loading and smoothness without assuming a filter slope.

    This diagnostic is displayed in reports but remains disconnected from
    candidate ranking and surface score. It evaluates only the
    crossover-to-high-sweep band. Complex impedance is accepted, but this
    provisional diagnostic operates on its magnitude.
    """
    frequencies = np.asarray(frequencies_hz, dtype=float)
    impedance = np.asarray(normalized_impedance)
    if frequencies.ndim != 1 or impedance.ndim != 1 or len(frequencies) != len(impedance):
        raise ValueError("frequency and impedance arrays must be one-dimensional and equal length")
    if len(frequencies) < 3 or np.any(~np.isfinite(frequencies)) or np.any(frequencies <= 0):
        raise ValueError("at least three positive finite frequencies are required")
    order = np.argsort(frequencies)
    frequencies = frequencies[order]
    impedance = impedance[order]
    if np.any(np.diff(frequencies) <= 0):
        raise ValueError("frequencies must be unique")
    magnitude = np.abs(impedance).astype(float)
    if np.any(~np.isfinite(magnitude)) or np.any(magnitude <= 0):
        raise ValueError("impedance magnitude must be positive and finite")
    upper = float(upper_frequency_hz or frequencies[-1])
    crossover = float(crossover_hz)
    if crossover < frequencies[0] or upper > frequencies[-1] or crossover >= upper:
        raise ValueError("crossover-to-upper band must lie inside the available frequencies")
    if points_per_octave < 12:
        raise ValueError("points_per_octave must be at least 12")

    span_octaves = float(np.log2(upper / crossover))
    count = max(3, int(np.ceil(span_octaves * points_per_octave)) + 1)
    log_frequency = np.linspace(np.log2(crossover), np.log2(upper), count)
    magnitude_db = np.interp(
        log_frequency, np.log2(frequencies), 20.0 * np.log10(magnitude))

    peak_magnitude = float(np.max(magnitude[frequencies <= upper]))
    crossover_magnitude = float(np.interp(
        np.log2(crossover), np.log2(frequencies), magnitude))
    crossover_peak_ratio = crossover_magnitude / peak_magnitude
    loading_band_lower = float(frequencies[0])
    loading_band_upper = min(upper, crossover * CROSSOVER_BAND_UPPER_RATIO)
    loading_band_octaves = float(
        np.log2(loading_band_upper / loading_band_lower))
    loading_count = max(
        3, int(np.ceil(loading_band_octaves * points_per_octave)) + 1)
    loading_log_frequency = np.linspace(
        np.log2(loading_band_lower),
        np.log2(loading_band_upper),
        loading_count,
    )
    loading_magnitude = np.interp(
        loading_log_frequency, np.log2(frequencies), magnitude)
    loading_band_peak_ratio = float(
        np.mean(loading_magnitude / peak_magnitude))
    crossover_point_score = min(
        crossover_peak_ratio / CROSSOVER_FULL_CREDIT_RATIO, 1.0)
    crossover_band_score = min(
        loading_band_peak_ratio / CROSSOVER_FULL_CREDIT_RATIO, 1.0)
    crossover_score = 100.0 * (
        CROSSOVER_LOADING_WEIGHTS["at_crossover"] * crossover_point_score
        + CROSSOVER_LOADING_WEIGHTS["crossover_band"]
        * crossover_band_score
    )

    shelf_width_octaves = span_octaves / 2.0
    shelf_mask = log_frequency >= log_frequency[-1] - shelf_width_octaves
    shelf_reference_db = _trimmed_mean(magnitude_db[shelf_mask])
    shelf_reference = float(10.0 ** (shelf_reference_db / 20.0))
    crossover_ratio = crossover_magnitude / shelf_reference
    peak_to_shelf_db = float(
        20.0 * np.log10(peak_magnitude / shelf_reference))
    local_peak = _local_peak_prominence(
        frequencies, magnitude, upper, points_per_octave)
    effective_peak_prominence_db = max(
        peak_to_shelf_db, local_peak["maximum_db"])
    peak_prominence_excess_db = max(
        0.0,
        effective_peak_prominence_db - PEAK_PROMINENCE_ALLOWANCE_DB,
    )

    monotone_baseline_db = _isotonic_non_decreasing(magnitude_db)
    ripple_db = magnitude_db - monotone_baseline_db
    ripple_rms_db = float(np.sqrt(np.mean(ripple_db ** 2)))
    ripple_p95_db = float(np.percentile(np.abs(ripple_db), 95))

    short = _short_smooth(magnitude_db, points_per_octave)
    total_variation_db = float(np.sum(np.abs(np.diff(short))))
    monotone_rise_db = max(0.0, float(short[-1] - short[0]))
    excess_variation = max(0.0, total_variation_db - monotone_rise_db)
    excess_variation_per_octave = excess_variation / span_octaves
    derivative = np.diff(short)
    signs = np.sign(np.where(np.abs(derivative) >= 0.02, derivative, 0.0))
    signs = signs[signs != 0]
    reversal_count = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0

    shelf_error_db = magnitude_db[shelf_mask] - shelf_reference_db
    shelf_rms_db = float(np.sqrt(np.mean(shelf_error_db ** 2)))
    shelf_x = log_frequency[shelf_mask]
    shelf_slope = float(np.polyfit(shelf_x, magnitude_db[shelf_mask], 1)[0])

    components = {
        "crossover_loading": crossover_score,
        "peak_prominence": _inverse_error_score(
            peak_prominence_excess_db,
            ERROR_REFERENCES["peak_prominence_excess_db"]),
        "ripple": _inverse_error_score(
            ripple_rms_db, ERROR_REFERENCES["ripple_rms_db"]),
        "excess_variation": _inverse_error_score(
            excess_variation_per_octave,
            ERROR_REFERENCES["excess_variation_db_per_octave"]),
        "shelf_stability": 0.5 * (
            _inverse_error_score(shelf_rms_db, ERROR_REFERENCES["shelf_rms_db"]) +
            _inverse_error_score(abs(shelf_slope),
                                 ERROR_REFERENCES["shelf_slope_db_per_octave"])
        ),
    }
    overall = float(sum(SCORE_WEIGHTS[name] * score
                        for name, score in components.items()))
    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "status": "experimental",
        "overall_percent": overall,
        "components": components,
        "crossover": {
            "frequency_hz": crossover,
            "magnitude": crossover_magnitude,
            "shelf_ratio": crossover_ratio,
            "peak_magnitude": peak_magnitude,
            "peak_normalized_magnitude": crossover_peak_ratio,
            "band": {
                "lower_frequency_hz": loading_band_lower,
                "upper_frequency_hz": loading_band_upper,
                "peak_normalized_mean_magnitude": loading_band_peak_ratio,
                "samples_per_octave": points_per_octave,
            },
            "component_weights": CROSSOVER_LOADING_WEIGHTS,
            "full_credit_ratio": CROSSOVER_FULL_CREDIT_RATIO,
            "subscores": {
                "at_crossover_percent": 100.0 * crossover_point_score,
                "crossover_band_percent": 100.0 * crossover_band_score,
            },
            "target_ratio": CROSSOVER_TARGET_RATIO,
            "passes_target": crossover_ratio >= CROSSOVER_TARGET_RATIO,
        },
        "shelf": {
            "role": "upper-band stability only; not crossover bandwidth",
            "reference_magnitude": shelf_reference,
            "reference_method": (
                "10% trimmed geometric mean of upper half of logarithmic band"),
            "lower_frequency_hz": float(2.0 ** (log_frequency[-1] - shelf_width_octaves)),
            "upper_frequency_hz": upper,
            "rms_deviation_db": shelf_rms_db,
            "slope_db_per_octave": shelf_slope,
        },
        "peak_prominence": {
            "peak_to_shelf_db": peak_to_shelf_db,
            "maximum_local_db": local_peak["maximum_db"],
            "local_peak_frequency_hz": local_peak["frequency_hz"],
            "local_window_octaves": local_peak["window_octaves"],
            "effective_db": effective_peak_prominence_db,
            "allowance_db": PEAK_PROMINENCE_ALLOWANCE_DB,
            "excess_db": peak_prominence_excess_db,
        },
        "smoothness": {
            "ripple_rms_db": ripple_rms_db,
            "ripple_p95_db": ripple_p95_db,
            "excess_variation_db_per_octave": excess_variation_per_octave,
            "reversal_count": reversal_count,
        },
        "score_weights": SCORE_WEIGHTS,
        "error_references": ERROR_REFERENCES,
        "samples_per_octave": points_per_octave,
    }
