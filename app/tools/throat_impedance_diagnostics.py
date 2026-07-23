"""Experimental diagnostics for normalized throat impedance."""
from __future__ import annotations

from typing import Any

import numpy as np


POINTS_PER_OCTAVE = 48
CROSSOVER_TARGET_RATIO = 0.5
SCORE_WEIGHTS = {
    "crossover_loading": 0.40,
    "ripple": 0.30,
    "excess_variation": 0.20,
    "shelf_stability": 0.10,
}
ERROR_REFERENCES = {
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

    shelf_width_octaves = span_octaves / 2.0
    shelf_mask = log_frequency >= log_frequency[-1] - shelf_width_octaves
    shelf_reference_db = _trimmed_mean(magnitude_db[shelf_mask])
    shelf_reference = float(10.0 ** (shelf_reference_db / 20.0))
    crossover_magnitude = float(10.0 ** (magnitude_db[0] / 20.0))
    crossover_ratio = crossover_magnitude / shelf_reference
    crossover_fraction = min(1.0, crossover_ratio / CROSSOVER_TARGET_RATIO)
    crossover_score = 100.0 * crossover_fraction ** 2

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
        "status": "experimental",
        "overall_percent": overall,
        "components": components,
        "crossover": {
            "frequency_hz": crossover,
            "magnitude": crossover_magnitude,
            "shelf_ratio": crossover_ratio,
            "target_ratio": CROSSOVER_TARGET_RATIO,
            "passes_target": crossover_ratio >= CROSSOVER_TARGET_RATIO,
        },
        "shelf": {
            "reference_magnitude": shelf_reference,
            "reference_method": (
                "10% trimmed geometric mean of upper half of logarithmic band"),
            "lower_frequency_hz": float(2.0 ** (log_frequency[-1] - shelf_width_octaves)),
            "upper_frequency_hz": upper,
            "rms_deviation_db": shelf_rms_db,
            "slope_db_per_octave": shelf_slope,
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
