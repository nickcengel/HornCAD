"""Raw angle-frequency surface diagnostics for HornCAD BEM results."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np


OCTAVE_WINDOWS = (1 / 12, 1 / 6, 1 / 3, 2 / 3)
CONTOUR_OCTAVE_WINDOWS = (1 / 12, 1 / 6, 1 / 3, 2 / 3, 1.0, 2.0)
CONTOUR_LEVELS_DB = (-3.0, -6.0, -9.0)
CONTOUR_SCORE_WEIGHTS = {-3.0: 0.25, -6.0: 0.50, -9.0: 0.25}
BEAMWIDTH_COMPONENT_WEIGHTS = {
    "multiscale_ripple": 0.30,
    "trend_complexity": 0.25,
    "local_narrowing": 0.30,
    "high_frequency_adequacy": 0.15,
}
BEAMWIDTH_BASE_ERROR_REFERENCES = {
    "multiscale_ripple": 0.04,
    "trend_complexity": 0.12,
    "local_narrowing": 0.06,
    "high_frequency_excess": 0.15,
}
BEAMWIDTH_REFERENCE_SCALE = 3.0
BEAMWIDTH_ERROR_REFERENCES = {
    key: value * BEAMWIDTH_REFERENCE_SCALE
    for key, value in BEAMWIDTH_BASE_ERROR_REFERENCES.items()
}
HIGH_FREQUENCY_TARGET_DEADBAND = 0.10
SURFACE_SCORE_WEIGHTS = {
    "profile_rms": 0.30,
    "slice_energy": 0.25,
    "mean_containment": 0.20,
    "outward_rise": 0.15,
    "minus_six_line": 0.10,
}
SURFACE_SCORE_V2_CANDIDATE_WEIGHTS = {
    "conservative": {
        "profile_rms": 0.30,
        "slice_energy": 0.25,
        "mean_containment": 0.15,
        "outward_rise": 0.10,
        "beamwidth_quality": 0.20,
    },
    "balanced": {
        "profile_rms": 0.30,
        "slice_energy": 0.25,
        "mean_containment": 0.10,
        "outward_rise": 0.10,
        "beamwidth_quality": 0.25,
    },
    "smoothness": {
        "profile_rms": 0.30,
        "slice_energy": 0.20,
        "mean_containment": 0.10,
        "outward_rise": 0.10,
        "beamwidth_quality": 0.30,
    },
    "contour_forward": {
        "profile_rms": 0.30,
        "slice_energy": 0.20,
        "mean_containment": 0.05,
        "outward_rise": 0.05,
        "beamwidth_quality": 0.40,
    },
}
ACTIVE_SURFACE_SCORE_VERSION = "v1"
ACTIVE_SURFACE_SCORE_V2_CANDIDATE = "contour_forward"
SURFACE_SCORE_V2_REVISION = "v2.2"
SURFACE_SCORE_V2_3_CORE_WEIGHTS = {
    "profile_rms": 0.4086081157134467,
    "slice_energy": 0.2939080731861326,
    "minus_six_line": 0.10722676459248746,
    "beamwidth_quality": 0.1902570465079333,
}
SURFACE_SCORE_V2_3_CORE_FRACTION = 0.20
SURFACE_SCORE_V2_3_CONTAINMENT_THRESHOLD = 75.0
SURFACE_SCORE_V2_3_OUTWARD_RISE_SCORE_THRESHOLD = 60.0
SURFACE_SCORE_V2_3_CONTAINMENT_EXPONENT = 1.0
SURFACE_SCORE_V2_3_OUTWARD_RISE_EXPONENT = 0.125
NARROW_COVERAGE_FULL_CORRECTION_DEG = 25.0
NARROW_COVERAGE_NO_CORRECTION_DEG = 30.0
NARROW_COVERAGE_MINIMUM_V2_FRACTION = 0.20
SURFACE_SCORE_V2_2_MINIMUM_COVERAGE_DEG = 25.0
SURFACE_SCORE_V2_2_MAXIMUM_COVERAGE_DEG = 50.0
SURFACE_SCORE_V2_2_MINIMUM_V2_FRACTION = 0.20
SURFACE_SCORE_V2_2_MAXIMUM_V2_FRACTION = 0.65
SURFACE_SCORE_V2_2_COVERAGE_EXPONENT = 2.0
SURFACE_SCORE_ERROR_REFERENCES = {
    "profile_rms": 3.0,
    "slice_energy": 2.0,
    "outward_rise": 2.0,
    "minus_six_line": 20.0,
}


def _inverse_error_score(error: float | None, reference: float) -> float:
    """Map zero error to 100 and the reference error to 50."""
    if error is None or not np.isfinite(error) or error < 0:
        return 0.0
    return float(100.0 / (1.0 + (float(error) / reference) ** 2))


def _axis_weights(
    mouth_dimensions_mm: dict[str, float] | None,
) -> np.ndarray:
    dimensions = mouth_dimensions_mm or {}
    raw = np.asarray([
        float(dimensions.get("horizontal", 1.0)),
        float(dimensions.get("vertical", 1.0)),
    ])
    if np.any(raw <= 0) or not np.all(np.isfinite(raw)):
        raw = np.ones(2)
    return raw / np.sum(raw)


def surface_score_v2_fraction(
    coverage_deg: float,
    revision: str,
) -> float:
    """Return the contour-forward fraction for a surface-score revision."""
    if revision == "v2":
        return 1.0
    if revision == "v2.1":
        return float(
            NARROW_COVERAGE_MINIMUM_V2_FRACTION
            + (1.0 - NARROW_COVERAGE_MINIMUM_V2_FRACTION) * np.clip(
                (
                    coverage_deg - NARROW_COVERAGE_FULL_CORRECTION_DEG
                ) / (
                    NARROW_COVERAGE_NO_CORRECTION_DEG
                    - NARROW_COVERAGE_FULL_CORRECTION_DEG
                ),
                0.0,
                1.0,
            )
        )
    if revision == "v2.2":
        position = float(np.clip(
            (
                coverage_deg - SURFACE_SCORE_V2_2_MINIMUM_COVERAGE_DEG
            ) / (
                SURFACE_SCORE_V2_2_MAXIMUM_COVERAGE_DEG
                - SURFACE_SCORE_V2_2_MINIMUM_COVERAGE_DEG
            ),
            0.0,
            1.0,
        ))
        return float(
            SURFACE_SCORE_V2_2_MINIMUM_V2_FRACTION
            + (
                SURFACE_SCORE_V2_2_MAXIMUM_V2_FRACTION
                - SURFACE_SCORE_V2_2_MINIMUM_V2_FRACTION
            ) * position ** SURFACE_SCORE_V2_2_COVERAGE_EXPONENT
        )
    raise ValueError(f"unknown surface-score revision: {revision}")


def surface_score_v1(
    result: dict[str, Any],
    mouth_dimensions_mm: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Return the legacy five-component surface score."""
    if result.get("status") != "available":
        return None
    axis_weights = _axis_weights(mouth_dimensions_mm)
    planes: dict[str, Any] = {}
    for plane_name in ("horizontal", "vertical"):
        plane = result[plane_name]
        line = plane["minus_six_line"]
        line_score = _inverse_error_score(
            line.get("rms_coverage_error_deg"),
            SURFACE_SCORE_ERROR_REFERENCES["minus_six_line"])
        line_score *= max(0.0, 1.0 - float(line.get("missing_fraction", 0.0)))
        components = {
            "profile_rms": _inverse_error_score(
                plane["distribution"]["rms_profile_error_db"],
                SURFACE_SCORE_ERROR_REFERENCES["profile_rms"]),
            "slice_energy": _inverse_error_score(
                plane["slice_energy_stability"]["rms_departure_db"],
                SURFACE_SCORE_ERROR_REFERENCES["slice_energy"]),
            "mean_containment": 100.0 * float(
                plane["containment"]["mean_fraction"]),
            "outward_rise": _inverse_error_score(
                plane["distribution"]["rms_outward_rise_violation_db"],
                SURFACE_SCORE_ERROR_REFERENCES["outward_rise"]),
            "minus_six_line": line_score,
        }
        planes[plane_name] = {
            "components": components,
            "overall_percent": float(sum(
                SURFACE_SCORE_WEIGHTS[key] * components[key]
                for key in SURFACE_SCORE_WEIGHTS)),
        }
    overall = float(sum(
        axis_weights[index] * planes[plane_name]["overall_percent"]
        for index, plane_name in enumerate(("horizontal", "vertical"))))
    return {
        "version": "v1",
        "overall_percent": overall,
        "horizontal": planes["horizontal"],
        "vertical": planes["vertical"],
        "axis_weights": {
            "horizontal": float(axis_weights[0]),
            "vertical": float(axis_weights[1]),
        },
        "component_weights": SURFACE_SCORE_WEIGHTS,
        "error_reference_values": SURFACE_SCORE_ERROR_REFERENCES,
    }


def surface_score_v2(
    result: dict[str, Any],
    mouth_dimensions_mm: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
    candidate_name: str = "balanced",
    adapt_narrow_coverage: bool = True,
    revision: str | None = None,
) -> dict[str, Any] | None:
    """Return a reproducible revision of the experimental v2 surface score."""
    if result.get("status") != "available":
        return None
    selected_weights = (
        dict(weights)
        if weights is not None
        else dict(SURFACE_SCORE_V2_CANDIDATE_WEIGHTS[candidate_name])
    )
    if set(selected_weights) != {
        "profile_rms",
        "slice_energy",
        "mean_containment",
        "outward_rise",
        "beamwidth_quality",
    }:
        raise ValueError("v2 surface-score weights have invalid components")
    if not np.isclose(sum(selected_weights.values()), 1.0):
        raise ValueError("v2 surface-score weights must sum to one")
    axis_weights = _axis_weights(mouth_dimensions_mm)
    planes: dict[str, Any] = {}
    for plane_name in ("horizontal", "vertical"):
        plane = result[plane_name]
        beamwidth = plane.get("beamwidth_quality")
        if not beamwidth:
            return None
        line = plane["minus_six_line"]
        line_score = _inverse_error_score(
            line.get("rms_coverage_error_deg"),
            SURFACE_SCORE_ERROR_REFERENCES["minus_six_line"],
        )
        line_score *= max(
            0.0, 1.0 - float(line.get("missing_fraction", 0.0))
        )
        components = {
            "profile_rms": _inverse_error_score(
                plane["distribution"]["rms_profile_error_db"],
                SURFACE_SCORE_ERROR_REFERENCES["profile_rms"],
            ),
            "slice_energy": _inverse_error_score(
                plane["slice_energy_stability"]["rms_departure_db"],
                SURFACE_SCORE_ERROR_REFERENCES["slice_energy"],
            ),
            "mean_containment": 100.0 * float(
                plane["containment"]["mean_fraction"]
            ),
            "outward_rise": _inverse_error_score(
                plane["distribution"]["rms_outward_rise_violation_db"],
                SURFACE_SCORE_ERROR_REFERENCES["outward_rise"],
            ),
            "beamwidth_quality": float(beamwidth["overall_percent"]),
            "minus_six_line": line_score,
        }
        coverage = float(plane["coverage_half_angle_deg"])
        selected_revision = (
            "v2" if not adapt_narrow_coverage
            else revision or SURFACE_SCORE_V2_REVISION
        )
        v2_fraction = surface_score_v2_fraction(
            coverage, selected_revision
        )
        effective_keys = (
            "profile_rms",
            "slice_energy",
            "mean_containment",
            "outward_rise",
            "minus_six_line",
            "beamwidth_quality",
        )
        effective_weights = {
            key: v2_fraction * selected_weights.get(key, 0.0)
            + (1.0 - v2_fraction) * SURFACE_SCORE_WEIGHTS.get(key, 0.0)
            for key in effective_keys
        }
        planes[plane_name] = {
            "components": components,
            "overall_percent": float(sum(
                effective_weights[key] * components[key]
                for key in effective_weights
            )),
            "component_weights": effective_weights,
            "v2_fraction": v2_fraction,
        }
    overall = float(sum(
        axis_weights[index] * planes[plane_name]["overall_percent"]
        for index, plane_name in enumerate(("horizontal", "vertical"))
    ))
    return {
        "version": selected_revision,
        "candidate_name": candidate_name,
        "overall_percent": overall,
        "horizontal": planes["horizontal"],
        "vertical": planes["vertical"],
        "axis_weights": {
            "horizontal": float(axis_weights[0]),
            "vertical": float(axis_weights[1]),
        },
        "component_weights": selected_weights,
        "narrow_coverage_adaptation": {
            "enabled": selected_revision == "v2.1",
            "full_correction_through_deg":
                NARROW_COVERAGE_FULL_CORRECTION_DEG,
            "no_correction_from_deg": NARROW_COVERAGE_NO_CORRECTION_DEG,
            "minimum_v2_fraction": NARROW_COVERAGE_MINIMUM_V2_FRACTION,
        },
        "coverage_adaptation": {
            "enabled": selected_revision == "v2.2",
            "minimum_coverage_deg":
                SURFACE_SCORE_V2_2_MINIMUM_COVERAGE_DEG,
            "maximum_coverage_deg":
                SURFACE_SCORE_V2_2_MAXIMUM_COVERAGE_DEG,
            "minimum_v2_fraction":
                SURFACE_SCORE_V2_2_MINIMUM_V2_FRACTION,
            "maximum_v2_fraction":
                SURFACE_SCORE_V2_2_MAXIMUM_V2_FRACTION,
            "coverage_exponent":
                SURFACE_SCORE_V2_2_COVERAGE_EXPONENT,
        },
        "error_reference_values": {
            **SURFACE_SCORE_ERROR_REFERENCES,
            **BEAMWIDTH_ERROR_REFERENCES,
        },
    }


def _surface_score_v2_3_guard_factor(
    value: float, threshold: float, exponent: float
) -> float:
    ratio = min(1.0, max(0.0, float(value) / threshold))
    return float(ratio ** exponent)


def surface_score_v2_3(
    result: dict[str, Any],
    mouth_dimensions_mm: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Blend v2.2 broad discrimination with a guarded local-ranking core."""
    if result.get("status") != "available":
        return None
    baseline = surface_score_v2(
        result,
        mouth_dimensions_mm,
        candidate_name="contour_forward",
        revision="v2.2",
    )
    if baseline is None:
        return None
    axis_weights = _axis_weights(mouth_dimensions_mm)
    planes: dict[str, Any] = {}
    for plane_name in ("horizontal", "vertical"):
        baseline_plane = baseline[plane_name]
        components = baseline_plane["components"]
        core_score = float(sum(
            weight * components[key]
            for key, weight in SURFACE_SCORE_V2_3_CORE_WEIGHTS.items()
        ))
        containment_factor = _surface_score_v2_3_guard_factor(
            components["mean_containment"],
            SURFACE_SCORE_V2_3_CONTAINMENT_THRESHOLD,
            SURFACE_SCORE_V2_3_CONTAINMENT_EXPONENT,
        )
        outward_rise_factor = _surface_score_v2_3_guard_factor(
            components["outward_rise"],
            SURFACE_SCORE_V2_3_OUTWARD_RISE_SCORE_THRESHOLD,
            SURFACE_SCORE_V2_3_OUTWARD_RISE_EXPONENT,
        )
        guard_factor = containment_factor * outward_rise_factor
        guarded_core_score = core_score * guard_factor
        overall = (
            (1.0 - SURFACE_SCORE_V2_3_CORE_FRACTION)
            * baseline_plane["overall_percent"]
            + SURFACE_SCORE_V2_3_CORE_FRACTION * guarded_core_score
        )
        triggered = []
        if containment_factor < 1.0:
            triggered.append("mean_containment")
        if outward_rise_factor < 1.0:
            triggered.append("outward_rise")
        planes[plane_name] = {
            "overall_percent": float(overall),
            "baseline_v2_2_percent": float(
                baseline_plane["overall_percent"]
            ),
            "core_percent": core_score,
            "guarded_core_percent": guarded_core_score,
            "guard_factor": guard_factor,
            "guardrail_status": (
                "within_guardrails" if not triggered else "penalized"
            ),
            "triggered_guardrails": triggered,
            "containment_factor": containment_factor,
            "outward_rise_factor": outward_rise_factor,
            "components": components,
        }
    overall = float(sum(
        axis_weights[index] * planes[plane_name]["overall_percent"]
        for index, plane_name in enumerate(("horizontal", "vertical"))
    ))
    return {
        "version": "v2.3",
        "status": "experimental_calibrated_not_independently_validated",
        "overall_percent": overall,
        "horizontal": planes["horizontal"],
        "vertical": planes["vertical"],
        "axis_weights": {
            "horizontal": float(axis_weights[0]),
            "vertical": float(axis_weights[1]),
        },
        "baseline_version": "v2.2",
        "baseline_fraction": 1.0 - SURFACE_SCORE_V2_3_CORE_FRACTION,
        "core_fraction": SURFACE_SCORE_V2_3_CORE_FRACTION,
        "core_weights": SURFACE_SCORE_V2_3_CORE_WEIGHTS,
        "guardrails": {
            "containment_threshold_percent":
                SURFACE_SCORE_V2_3_CONTAINMENT_THRESHOLD,
            "containment_exponent":
                SURFACE_SCORE_V2_3_CONTAINMENT_EXPONENT,
            "outward_rise_score_threshold_percent":
                SURFACE_SCORE_V2_3_OUTWARD_RISE_SCORE_THRESHOLD,
            "outward_rise_exponent":
                SURFACE_SCORE_V2_3_OUTWARD_RISE_EXPONENT,
        },
    }


def surface_score(
    result: dict[str, Any],
    mouth_dimensions_mm: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Return the active v1 score; v2 remains experimental side-by-side."""
    return surface_score_v1(result, mouth_dimensions_mm)


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


def _first_level_crossing(
    angles: np.ndarray, row: np.ndarray, level_db: float
) -> float:
    for index in range(len(angles) - 1):
        left, right = row[index], row[index + 1]
        if left >= level_db and right < level_db:
            return float(angles[index] + (level_db - left) /
                         (right - left) * (angles[index + 1] - angles[index]))
    return float("nan")


def _first_minus_six_crossing(angles: np.ndarray, row: np.ndarray) -> float:
    """Compatibility wrapper for the legacy retained-line diagnostic."""
    return _first_level_crossing(angles, row, -6.0)


def _weighted_geometric_score(
    components: dict[Any, float], weights: dict[Any, float]
) -> float:
    if any(float(components[key]) <= 0 for key in weights):
        return 0.0
    total_weight = float(sum(weights.values()))
    return float(np.exp(sum(
        (float(weights[key]) / total_weight) * np.log(float(components[key]))
        for key in weights
    )))


def _longest_missing_span(x: np.ndarray, valid: np.ndarray) -> float:
    if np.all(valid):
        return 0.0
    longest = 0.0
    start: int | None = None
    for index, is_valid in enumerate(np.append(valid, True)):
        if not is_valid and start is None:
            start = index
        elif is_valid and start is not None:
            stop = index - 1
            left = x[start] if start == 0 else (x[start - 1] + x[start]) / 2
            right = (
                x[stop]
                if stop == len(x) - 1
                else (x[stop] + x[stop + 1]) / 2
            )
            longest = max(longest, float(max(0.0, right - left)))
            start = None
    return longest


def _fill_isolated_missing(x: np.ndarray, values: np.ndarray) -> np.ndarray:
    filled = np.asarray(values, dtype=float).copy()
    for index in range(1, len(filled) - 1):
        if (
            not np.isfinite(filled[index])
            and np.isfinite(filled[index - 1])
            and np.isfinite(filled[index + 1])
        ):
            filled[index] = float(np.interp(
                x[index],
                x[[index - 1, index + 1]],
                filled[[index - 1, index + 1]],
            ))
    return filled


def _moving_residuals(
    x: np.ndarray,
    values: np.ndarray,
    original_valid: np.ndarray,
    width_octaves: float,
) -> tuple[np.ndarray, np.ndarray]:
    half = width_octaves / 2
    if x[-1] - x[0] < width_octaves:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    finite = np.isfinite(values)
    finite_x = x[finite]
    finite_values = values[finite]
    centers = []
    residuals = []
    for index in np.flatnonzero(finite):
        if x[index] < x[0] + half or x[index] > x[-1] - half:
            continue
        support = (x >= x[index] - half) & (x <= x[index] + half)
        if np.mean(original_valid[support]) < 0.80:
            continue
        mean = _interval_mean(
            finite_x,
            finite_values,
            float(x[index] - half),
            float(x[index] + half),
        )
        centers.append(x[index])
        residuals.append(float(values[index] - mean))
    return np.asarray(centers), np.asarray(residuals)


def _contour_diagnostics(
    frequencies: np.ndarray,
    angles: np.ndarray,
    levels: np.ndarray,
    coverage: float,
    level_db: float,
) -> dict[str, Any]:
    log_frequency = np.log2(frequencies)
    target_angle = coverage * abs(level_db) / 6.0
    crossings = np.asarray([
        _first_level_crossing(angles, row, level_db) for row in levels
    ])
    original_valid = np.isfinite(crossings)
    normalized = crossings / target_angle
    filled = _fill_isolated_missing(log_frequency, normalized)
    residuals_by_scale: dict[str, float | None] = {}
    narrowing_by_scale: dict[str, float | None] = {}
    aggregate_ripple = []
    for width in CONTOUR_OCTAVE_WINDOWS:
        _, residuals = _moving_residuals(
            log_frequency, filled, original_valid, width
        )
        key = _window_key(width)
        if len(residuals):
            rms = float(np.sqrt(np.mean(residuals ** 2)))
            narrowing = float(np.quantile(np.maximum(0.0, -residuals), 0.95))
            residuals_by_scale[key] = rms
            narrowing_by_scale[key] = narrowing
            aggregate_ripple.append(rms)
        else:
            residuals_by_scale[key] = None
            narrowing_by_scale[key] = None
    ripple = (
        float(np.sqrt(np.mean(np.asarray(aggregate_ripple) ** 2)))
        if aggregate_ripple
        else float("inf")
    )
    narrowing_values = [
        value for value in narrowing_by_scale.values() if value is not None
    ]
    local_narrowing = max(narrowing_values, default=float("inf"))

    trend_x, trend_residual = _moving_residuals(
        log_frequency, filled, original_valid, 1 / 3
    )
    trend_values = np.asarray([
        filled[int(np.argmin(np.abs(log_frequency - center)))] - residual
        for center, residual in zip(trend_x, trend_residual, strict=True)
    ])
    if len(trend_x) >= 3 and trend_x[-1] > trend_x[0]:
        slope = np.gradient(trend_values, trend_x)
        net_slope = float(
            (trend_values[-1] - trend_values[0]) / (trend_x[-1] - trend_x[0])
        )
        complexity = float(np.mean(np.abs(slope - net_slope)))
        threshold = 0.02
        meaningful = np.sign(slope[np.abs(slope) >= threshold])
        reversals = int(np.count_nonzero(np.diff(meaningful) != 0))
    else:
        net_slope = None
        complexity = float("inf")
        reversals = 0

    upper_start = log_frequency[-1] - min(
        1 / 3, log_frequency[-1] - log_frequency[0]
    )
    high = (log_frequency >= upper_start) & np.isfinite(filled)
    if np.count_nonzero(high) >= 2:
        high_width = _band_mean(log_frequency[high], filled[high])
    elif np.count_nonzero(high) == 1:
        high_width = float(filled[high][0])
    else:
        high_width = float("nan")
    high_error = (
        abs(high_width - 1.0) if np.isfinite(high_width) else float("inf")
    )
    high_excess = max(0.0, high_error - HIGH_FREQUENCY_TARGET_DEADBAND)
    completeness = float(np.mean(original_valid))

    component_scores = {
        "multiscale_ripple": _inverse_error_score(
            ripple, BEAMWIDTH_ERROR_REFERENCES["multiscale_ripple"]
        ),
        "trend_complexity": _inverse_error_score(
            complexity, BEAMWIDTH_ERROR_REFERENCES["trend_complexity"]
        ),
        "local_narrowing": _inverse_error_score(
            local_narrowing, BEAMWIDTH_ERROR_REFERENCES["local_narrowing"]
        ),
        "high_frequency_adequacy": _inverse_error_score(
            high_excess, BEAMWIDTH_ERROR_REFERENCES["high_frequency_excess"]
        ),
    }
    shape_score = _weighted_geometric_score(
        component_scores, BEAMWIDTH_COMPONENT_WEIGHTS
    )
    overall = completeness * shape_score

    raw_movement = np.full_like(crossings, np.nan)
    for index in range(1, len(crossings)):
        if original_valid[index - 1] and original_valid[index]:
            step = log_frequency[index] - log_frequency[index - 1]
            if step > 0:
                raw_movement[index] = (
                    crossings[index] - crossings[index - 1]
                ) / step
    valid_movement = raw_movement[np.isfinite(raw_movement)]
    angle_error = crossings - target_angle
    valid_error = angle_error[np.isfinite(angle_error)]
    worst_index = (
        int(np.nanargmax(np.abs(angle_error))) if len(valid_error) else None
    )
    return {
        "level_db": level_db,
        "target_half_angle_deg": target_angle,
        "traces": {
            "frequencies_hz": frequencies.tolist(),
            "half_angle_deg": crossings.tolist(),
            "normalized_width": normalized.tolist(),
            "target_error_deg": angle_error.tolist(),
        },
        "missing_fraction": 1.0 - completeness,
        "longest_missing_span_octaves": _longest_missing_span(
            log_frequency, original_valid
        ),
        "multiscale_ripple_rms_fraction": residuals_by_scale,
        "aggregate_ripple_rms_fraction": ripple,
        "trend_complexity_fraction_per_octave": complexity,
        "net_trend_fraction_per_octave": net_slope,
        "slope_reversal_count": reversals,
        "multiscale_local_narrowing_fraction": narrowing_by_scale,
        "local_narrowing_fraction": local_narrowing,
        "high_frequency_mean_normalized_width": high_width,
        "high_frequency_target_error_fraction": high_error,
        "high_frequency_excess_fraction": high_excess,
        "rms_target_error_deg": (
            float(np.sqrt(np.mean(valid_error ** 2))) if len(valid_error) else None
        ),
        "worst_target_error_deg": (
            float(angle_error[worst_index]) if worst_index is not None else None
        ),
        "worst_target_error_frequency_hz": (
            float(frequencies[worst_index]) if worst_index is not None else None
        ),
        "rms_raw_movement_deg_per_octave": (
            float(np.sqrt(np.mean(valid_movement ** 2)))
            if len(valid_movement)
            else None
        ),
        "component_scores": component_scores,
        "shape_score_before_completeness": shape_score,
        "overall_percent": overall,
    }


def _beamwidth_quality(contours: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return beamwidth_quality_at_reference_scale(
        contours, BEAMWIDTH_REFERENCE_SCALE
    )


def beamwidth_quality_at_reference_scale(
    contours: dict[str, dict[str, Any]],
    reference_scale: float,
) -> dict[str, Any]:
    """Rescore retained raw contour metrics at a documented reference scale."""
    if not np.isfinite(reference_scale) or reference_scale <= 0:
        raise ValueError("beamwidth reference scale must be positive")
    contour_results = {}
    for key, contour in contours.items():
        references = {
            name: value * reference_scale
            for name, value in BEAMWIDTH_BASE_ERROR_REFERENCES.items()
        }
        component_scores = {
            "multiscale_ripple": _inverse_error_score(
                contour["aggregate_ripple_rms_fraction"],
                references["multiscale_ripple"],
            ),
            "trend_complexity": _inverse_error_score(
                contour["trend_complexity_fraction_per_octave"],
                references["trend_complexity"],
            ),
            "local_narrowing": _inverse_error_score(
                contour["local_narrowing_fraction"],
                references["local_narrowing"],
            ),
            "high_frequency_adequacy": _inverse_error_score(
                contour["high_frequency_excess_fraction"],
                references["high_frequency_excess"],
            ),
        }
        shape_score = _weighted_geometric_score(
            component_scores, BEAMWIDTH_COMPONENT_WEIGHTS
        )
        contour_results[key] = {
            "component_scores": component_scores,
            "shape_score_before_completeness": shape_score,
            "overall_percent": (
                shape_score * (1.0 - float(contour["missing_fraction"]))
            ),
        }
    scores = {
        float(contours[key]["level_db"]): float(value["overall_percent"])
        for key, value in contour_results.items()
    }
    return {
        "overall_percent": _weighted_geometric_score(
            scores, CONTOUR_SCORE_WEIGHTS
        ),
        "contour_scores": {
            key: float(value["overall_percent"])
            for key, value in contour_results.items()
        },
        "contour_weights": {
            f"minus_{abs(int(level))}_db": weight
            for level, weight in CONTOUR_SCORE_WEIGHTS.items()
        },
        "component_weights": BEAMWIDTH_COMPONENT_WEIGHTS,
        "error_reference_values": {
            name: value * reference_scale
            for name, value in BEAMWIDTH_BASE_ERROR_REFERENCES.items()
        },
        "reference_scale": reference_scale,
        "high_frequency_target_deadband": HIGH_FREQUENCY_TARGET_DEADBAND,
    }


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

    contours = {
        f"minus_{abs(int(level_db))}_db": _contour_diagnostics(
            frequencies, full_angles, full_levels, coverage, level_db
        )
        for level_db in CONTOUR_LEVELS_DB
    }
    beamwidth_quality = _beamwidth_quality(contours)
    minus_six = contours["minus_6_db"]
    minus_six_trace = minus_six["traces"]
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
            "minus_six_half_angle_deg": minus_six_trace["half_angle_deg"],
            "minus_six_error_deg": minus_six_trace["target_error_deg"],
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
            "missing_fraction": minus_six["missing_fraction"],
            "rms_coverage_error_deg": minus_six["rms_target_error_deg"],
            "worst_coverage_error_deg": minus_six["worst_target_error_deg"],
            "worst_coverage_error_frequency_hz": (
                minus_six["worst_target_error_frequency_hz"]
            ),
            "rms_movement_deg_per_octave": (
                minus_six["rms_raw_movement_deg_per_octave"]
            ),
        },
        "contours": contours,
        "beamwidth_quality": beamwidth_quality,
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
    result = {
        "status": "available",
        "band_kind": "fixed shadow evaluation" if fixed_band else "shadow evaluation",
        "band_lower_hz": float(frequencies[0]),
        "band_upper_hz": float(frequencies[-1]),
        "horizontal": planes["horizontal"],
        "vertical": planes["vertical"],
    }
    result["score_v1"] = surface_score_v1(
        result, run.get("mouth_dimensions_mm")
    )
    result["score_v2_candidates"] = {
        name: surface_score_v2(
            result,
            run.get("mouth_dimensions_mm"),
            weights=weights,
            candidate_name=name,
        )
        for name, weights in SURFACE_SCORE_V2_CANDIDATE_WEIGHTS.items()
    }
    result["score_v2_3"] = surface_score_v2_3(
        result, run.get("mouth_dimensions_mm")
    )
    result["score"] = surface_score(result, run.get("mouth_dimensions_mm"))
    return result
