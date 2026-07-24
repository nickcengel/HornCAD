#!/usr/bin/env python3
"""Run a resumable, constrained BEM candidate search from a search YAML."""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import multiprocessing
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import time
from typing import Any

import numpy as np
from scipy.stats import norm, qmc
import yaml

try:
    from .export_horncad import solved_s, termination_metrics
    from .generate_numcalc_review import generate_review
    from .interactive_results import coverage_diagnostics, load_run, single_report
    from .surface_diagnostics import surface_diagnostics, surface_score
    from .throat_impedance_diagnostics import (
        DIAGNOSTIC_VERSION,
        throat_impedance_diagnostics,
    )
    from .s_sensitivity_sampling import SPoint, interval_refinement_reason
    from .run_bem_suite import find_numcalc
    from .run_numcalc_sweep import ppo_frequency_grid, run_sweep
except ImportError:
    from export_horncad import solved_s, termination_metrics
    from generate_numcalc_review import generate_review
    from interactive_results import coverage_diagnostics, load_run, single_report
    from surface_diagnostics import surface_diagnostics, surface_score
    from throat_impedance_diagnostics import (
        DIAGNOSTIC_VERSION,
        throat_impedance_diagnostics,
    )
    from s_sensitivity_sampling import SPoint, interval_refinement_reason
    from run_bem_suite import find_numcalc
    from run_numcalc_sweep import ppo_frequency_grid, run_sweep


VARIABLES = ("length_mm", "extension_mm", "osse_coverage_h_deg",
             "osse_coverage_v_deg", "k_h", "k_v", "n_h", "n_v")
OBJECTIVES = ("coverage_match_percent", "coverage_smoothness_percent",
              "waist_stability_percent", "window_uniformity_percent")
OBJECTIVE_LABELS = ("Coverage Match", "Coverage Smoothness", "Waist Stability",
                    "Window Uniformity")
PRESET_BUDGETS = {"quick": 16, "normal": 36, "thorough": 60}
DEFAULT_MINIMUM_CANDIDATE_DISTANCE = 0.08
DEFAULT_INFERIOR_PROBABILITY = 0.97
DEFAULT_SAMPLING_STABILITY_POINTS = 2.0
DEFAULT_ADAPTIVE_PRUNING_MIN_EVALUATIONS = 5
DEFAULT_ADAPTIVE_PRUNING_MARGIN_POINTS = 3.0
DEFAULT_ADAPTIVE_PRUNING_CONFIDENCE_SIGMA = 2.0
DEFAULT_ADAPTIVE_PRUNING_UNCERTAINTY_FLOOR_POINTS = 1.5
MAX_FINAL_TENTH_RADIAL_GROWTH_FRACTION = 0.52
VARIABLE_LABELS = {
    "length_mm": "length", "extension_mm": "extension",
    "osse_coverage_h_deg": "horizontal OS-SE coverage",
    "osse_coverage_v_deg": "vertical OS-SE coverage",
    "k_h": "horizontal K", "k_v": "vertical K",
    "n_h": "horizontal N", "n_v": "vertical N",
}


def _artifact_number(value: float) -> str:
    """Format an authored value compactly and deterministically for filenames."""
    return f"{float(value):g}"


def candidate_artifact_stem(document: dict[str, Any]) -> str:
    """Return the canonical public artifact name for a candidate project."""
    config = document["horncad_config"]
    global_config = config["global"]
    horizontal = config["horizontal_basis"]
    vertical = config["vertical_basis"]
    dimensions = "x".join(_artifact_number(global_config[key]) for key in (
        "mouth_width", "mouth_height", "length"))
    extension = float(global_config.get("conical_extension_length", 0))
    if not math.isclose(extension, 0.0, abs_tol=1e-9):
        dimensions += f"_E{_artifact_number(extension)}"

    horizontal_values = (
        float(horizontal["coverage_deg"]), float(horizontal["k"]),
        float(horizontal["n"]),
    )
    vertical_values = (
        float(vertical["coverage_deg"]), float(vertical["k"]),
        float(vertical["n"]),
    )
    # Optimizer proposals can carry sub-display floating-point noise. Treat the
    # axes as equal when their canonical filename tokens are equal.
    if all(_artifact_number(h) == _artifact_number(v)
           for h, v in zip(horizontal_values, vertical_values)):
        coverage, k_value, n_value = horizontal_values
        profile = (f"{_artifact_number(coverage)}_K{_artifact_number(k_value)}"
                   f"_N{_artifact_number(n_value)}")
    else:
        h_coverage, h_k, h_n = horizontal_values
        v_coverage, v_k, v_n = vertical_values
        profile = (
            f"H{_artifact_number(h_coverage)}_K{_artifact_number(h_k)}"
            f"_N{_artifact_number(h_n)}_V{_artifact_number(v_coverage)}"
            f"_K{_artifact_number(v_k)}_N{_artifact_number(v_n)}"
        )
    return f"{dimensions}_{profile}"


def _axis_pair(horizontal: str, vertical: str) -> str:
    """Keep the slash with the horizontal value while permitting a line break."""
    return f"{horizontal}&nbsp;/<wbr> {vertical}"


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping in {path}")
    return data


def load_search(path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    document = _read_yaml(path)
    search = document.get("bem_candidate_search")
    if not isinstance(search, dict) or int(search.get("version", 0)) != 1:
        raise ValueError("expected bem_candidate_search version 1")
    seed_path = Path(str(search.get("seed_yaml", "")))
    if not seed_path.is_absolute():
        seed_path = path.parent / seed_path
    seed_path = seed_path.resolve()
    seed = _read_yaml(seed_path)
    if not isinstance(seed.get("horncad_config"), dict):
        raise ValueError(f"seed is not a HornCAD project: {seed_path}")
    config = seed["horncad_config"]
    intent = config.get("operating_intent", {})
    crossover = float(search.get("crossover_hz", intent.get("crossover_hz", 0)))
    upper = float(search.get("upper_frequency_hz",
                             intent.get("upper_frequency_hz", 0)))
    lower = float(search.get("lower_frequency_hz",
                             intent.get("lower_frequency_hz", crossover)))
    if not 0 < lower <= crossover < upper:
        raise ValueError("search requires 0 < lower_frequency_hz <= "
                         "crossover_hz < upper_frequency_hz")
    if upper < crossover * 2 ** (1 / 6):
        raise ValueError("upper frequency must include the crossover-centered "
                         "one-third-octave impedance window")
    bounds = search.get("bounds", {})
    for name in VARIABLES:
        values = bounds.get(name)
        if not (isinstance(values, list) and len(values) == 2
                and float(values[0]) < float(values[1])):
            raise ValueError(f"bounds.{name} must be [minimum, maximum]")
        bounds[name] = [float(values[0]), float(values[1])]
    search["bounds"] = bounds
    s_bounds = search.get("derived_s_bounds", [0.0, 3.0])
    if not (isinstance(s_bounds, list) and len(s_bounds) == 2 and
            0 <= float(s_bounds[0]) < float(s_bounds[1])):
        raise ValueError("derived_s_bounds must be [nonnegative minimum, maximum]")
    search["derived_s_bounds"] = [float(s_bounds[0]), float(s_bounds[1])]
    search["lower_frequency_hz"] = lower
    search["crossover_hz"] = crossover
    search["upper_frequency_hz"] = upper
    preset = str(search.get("search_size", "normal"))
    search["max_evaluations"] = int(
        search.get("max_evaluations", PRESET_BUDGETS.get(preset, 36)))
    search["initial_candidates"] = min(
        int(search.get("initial_candidates", 12)), search["max_evaluations"] - 1)
    search["minimum_candidate_distance"] = float(search.get(
        "minimum_candidate_distance", DEFAULT_MINIMUM_CANDIDATE_DISTANCE))
    search["inferior_screen_probability"] = float(search.get(
        "inferior_screen_probability", DEFAULT_INFERIOR_PROBABILITY))
    search["sampling_stability_points"] = float(search.get(
        "sampling_stability_points", DEFAULT_SAMPLING_STABILITY_POINTS))
    search["confirmation_points_per_octave"] = float(search.get(
        "confirmation_points_per_octave", 16))
    initial_pool = search.get("initial_pool")
    if initial_pool is not None:
        if not isinstance(initial_pool, list) or not initial_pool:
            raise ValueError("initial_pool must be a non-empty list")
        validated_pool = []
        for index, item in enumerate(initial_pool):
            if not isinstance(item, dict) or not str(item.get("label", "")).strip():
                raise ValueError(f"initial_pool[{index}] requires a label")
            values = item.get("values")
            if not isinstance(values, dict):
                raise ValueError(f"initial_pool[{index}] requires values")
            candidate = {}
            for name in VARIABLES:
                if name not in values:
                    raise ValueError(f"initial_pool[{index}].values requires {name}")
                value = float(values[name])
                lower, upper = bounds[name]
                if not lower <= value <= upper:
                    raise ValueError(
                        f"initial_pool[{index}].values.{name} is outside bounds")
                candidate[name] = value
            validated_pool.append({"label": str(item["label"]).strip(),
                                   "values": candidate})
        search["initial_pool"] = validated_pool
        search["initial_candidates"] = min(len(validated_pool),
                                           search["max_evaluations"] - 1)
    if not 0.5 < search["inferior_screen_probability"] < 1:
        raise ValueError("inferior_screen_probability must be between 0.5 and 1")
    if search["sampling_stability_points"] <= 0:
        raise ValueError("sampling_stability_points must be positive")
    if search["max_evaluations"] < 1:
        raise ValueError("search requires at least one evaluation")
    if (search["max_evaluations"] > 1 and
            search["initial_candidates"] < 1 and
            not search.get("adaptive_kn_closure", {}).get("enabled", False)):
        raise ValueError("multi-candidate search requires an initial candidate")
    return search, seed_path, seed


def seed_values(seed: dict[str, Any]) -> dict[str, float]:
    config = seed["horncad_config"]
    global_config = config["global"]
    h = config["horizontal_basis"]
    v = config["vertical_basis"]
    return {
        "length_mm": float(global_config["length"]),
        "extension_mm": float(global_config.get("conical_extension_length", 0)),
        "osse_coverage_h_deg": float(h["coverage_deg"]),
        "osse_coverage_v_deg": float(v["coverage_deg"]),
        "k_h": float(h["k"]), "k_v": float(v["k"]),
        "n_h": float(h["n"]), "n_v": float(v["n"]),
    }


def normalized_vector(values: dict[str, float], bounds: dict[str, list[float]]) -> np.ndarray:
    return np.asarray([(values[name] - bounds[name][0]) /
                       (bounds[name][1] - bounds[name][0]) for name in VARIABLES])


def values_from_vector(vector: np.ndarray,
                       bounds: dict[str, list[float]]) -> dict[str, float]:
    return {name: float(bounds[name][0] + vector[index] *
                        (bounds[name][1] - bounds[name][0]))
            for index, name in enumerate(VARIABLES)}


def materialize_candidate(seed: dict[str, Any], values: dict[str, float],
                          search: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    document = copy.deepcopy(seed)
    config = document["horncad_config"]
    g = config["global"]
    h = config["horizontal_basis"]
    v = config["vertical_basis"]
    g["length"] = values["length_mm"]
    g["conical_extension_length"] = values["extension_mm"]
    effective_radius = (float(g["throat_radius"]) + values["extension_mm"] *
                        math.tan(math.radians(float(g["throat_angle_deg"]))))
    g["effective_throat_radius"] = effective_radius
    g["measured_total_length"] = values["length_mm"] + values["extension_mm"]
    h["coverage_deg"] = values["osse_coverage_h_deg"]
    v["coverage_deg"] = values["osse_coverage_v_deg"]
    h["k"] = values["k_h"]
    v["k"] = values["k_v"]
    h["n"] = values["n_h"]
    v["n"] = values["n_v"]
    s_h = solved_s(values["length_mm"], effective_radius, h["coverage_deg"],
                   h["k"], float(h["n"]), float(g["mouth_width"]) / 2,
                   float(g["throat_angle_deg"]))
    s_v = solved_s(values["length_mm"], effective_radius, v["coverage_deg"],
                   v["k"], float(v["n"]), float(g["mouth_height"]) / 2,
                   float(g["throat_angle_deg"]))
    h["solved_s"] = s_h
    v["solved_s"] = s_v
    intent = config.setdefault("operating_intent", {})
    intent["horizontal_coverage_deg"] = float(search["intended_coverage_h_deg"])
    intent["vertical_coverage_deg"] = float(search["intended_coverage_v_deg"])
    intent["lower_frequency_hz"] = float(search["lower_frequency_hz"])
    intent["crossover_hz"] = float(search["crossover_hz"])
    intent["upper_frequency_hz"] = float(search["upper_frequency_hz"])
    h_termination = termination_metrics(
        values["length_mm"], effective_radius, h["coverage_deg"], h["k"],
        float(h["n"]), float(g["mouth_width"]) / 2, float(g["throat_angle_deg"]))
    v_termination = termination_metrics(
        values["length_mm"], effective_radius, v["coverage_deg"], v["k"],
        float(v["n"]), float(g["mouth_height"]) / 2, float(g["throat_angle_deg"]))
    h["mouth_exit_angle_deg"] = h_termination["exit_angle_deg"]
    h["mouth_curvature_radius_mm"] = h_termination["curvature_radius_mm"]
    h["normalized_mouth_curvature_radius"] = h_termination["normalized_curvature_radius"]
    v["mouth_exit_angle_deg"] = v_termination["exit_angle_deg"]
    v["mouth_curvature_radius_mm"] = v_termination["curvature_radius_mm"]
    v["normalized_mouth_curvature_radius"] = v_termination["normalized_curvature_radius"]
    return document, {
        "s_h": float(s_h), "s_v": float(s_v),
        "mouth_exit_angle_h_deg": h_termination["exit_angle_deg"],
        "mouth_exit_angle_v_deg": v_termination["exit_angle_deg"],
        "mouth_curvature_radius_h_mm": h_termination["curvature_radius_mm"],
        "mouth_curvature_radius_v_mm": v_termination["curvature_radius_mm"],
        "normalized_mouth_curvature_h": h_termination["normalized_curvature_radius"],
        "normalized_mouth_curvature_v": v_termination["normalized_curvature_radius"],
        "final_tenth_radial_growth_h": h_termination[
            "final_tenth_radial_growth_fraction"],
        "final_tenth_radial_growth_v": v_termination[
            "final_tenth_radial_growth_fraction"],
    }


def geometry_feasibility(derived: dict[str, float]) -> tuple[bool, str | None]:
    if not all(math.isfinite(value) for value in derived.values()):
        return False, "derived geometry is not finite"
    if derived["s_h"] < 0:
        return False, "horizontal s is negative"
    if derived["s_v"] < 0:
        return False, "vertical s is negative"
    for axis in ("h", "v"):
        growth = derived.get(f"final_tenth_radial_growth_{axis}")
        if (growth is not None and
                growth > MAX_FINAL_TENTH_RADIAL_GROWTH_FRACTION):
            return False, (
                f"{axis.upper()} profile puts {growth:.1%} of radial growth in "
                f"the final 10% of horn length (maximum "
                f"{MAX_FINAL_TENTH_RADIAL_GROWTH_FRACTION:.0%})")
    return True, None


def export_candidate_stl(project_path: Path, candidate_dir: Path,
                         artifact_stem: str | None = None) -> Path:
    """Retain an inspectable acoustic-surface STL for every proposed candidate."""
    document = _read_yaml(project_path)
    stem = artifact_stem or candidate_artifact_stem(document)
    target = candidate_dir / f"{stem}_Surface.STL"
    if target.is_file():
        return target
    existing = list(candidate_dir.glob("*.STL"))
    if existing:
        existing[0].replace(target)
        return target
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("export_horncad.py")),
         str(project_path), "--mode", "acoustic_surface", "--output-dir",
         str(candidate_dir)], check=True, capture_output=True, text=True)
    path = Path(result.stdout.splitlines()[0])
    path.replace(target)
    return target


def candidate_distance(values: dict[str, float], records: list[dict[str, Any]],
                       bounds: dict[str, list[float]]) -> float:
    """Return normalized distance to the nearest retained candidate."""
    if not records:
        return math.inf
    vector = normalized_vector(values, bounds)
    existing = np.asarray([normalized_vector(record["values"], bounds)
                           for record in records])
    return float(np.min(np.linalg.norm(existing - vector, axis=1)))


def candidate_trait(values: dict[str, float], seed: dict[str, float],
                    bounds: dict[str, list[float]]) -> str:
    """Describe the candidate's largest normalized departure from the seed."""
    offsets = {name: (values[name] - seed[name]) /
               (bounds[name][1] - bounds[name][0]) for name in VARIABLES}
    name = max(VARIABLES, key=lambda item: abs(offsets[item]))
    if abs(offsets[name]) < 1e-9:
        return "Seed design"
    return f"{'High' if offsets[name] > 0 else 'Low'} {VARIABLE_LABELS[name]}"


def candidate_traits(records: list[dict[str, Any]], seed: dict[str, float],
                     bounds: dict[str, list[float]]) -> list[str]:
    """Return progressively detailed trait labels that are unique in the report."""
    ranked: list[list[str]] = []
    for record in records:
        values = record["values"]
        offsets = {name: (values[name] - seed[name]) /
                   (bounds[name][1] - bounds[name][0]) for name in VARIABLES}
        if max(abs(value) for value in offsets.values()) < 1e-9:
            ranked.append(["Seed design"])
            continue
        names = sorted(VARIABLES, key=lambda name: abs(offsets[name]), reverse=True)
        ranked.append([
            f"{'High' if offsets[name] > 0 else 'Low'} {VARIABLE_LABELS[name]}"
            for name in names if abs(offsets[name]) >= 1e-9
        ])
    depths = [1] * len(records)
    while True:
        labels = [" · ".join(traits[:depths[index]])
                  for index, traits in enumerate(ranked)]
        groups: dict[str, list[int]] = {}
        for index, label in enumerate(labels):
            groups.setdefault(label, []).append(index)
        collisions = [indices for indices in groups.values() if len(indices) > 1]
        if not collisions:
            return labels
        advanced = False
        for indices in collisions:
            for index in indices:
                if depths[index] < len(ranked[index]):
                    depths[index] += 1
                    advanced = True
        if not advanced:
            # If every high/low direction is identical, include parameter values;
            # the minimum-distance filter prevents identical retained profiles.
            detailed = []
            for index, label in enumerate(labels):
                if len(groups[label]) == 1:
                    detailed.append(label)
                    continue
                values = records[index]["values"]
                details = [f"{trait} ({values[name]:g})"
                           for trait, name in zip(ranked[index],
                                                  sorted(VARIABLES, key=lambda item: abs(
                                                      (values[item] - seed[item]) /
                                                      (bounds[item][1] - bounds[item][0])),
                                                         reverse=True))]
                detailed.append(" · ".join(details))
            return detailed


def objective_score(values: dict[str, Any], key: str) -> float:
    """Read a current headline objective."""
    return float(values[key])


def _objective_values(record: dict[str, Any]) -> np.ndarray:
    values = record["diagnostics"]["combined"]
    return np.asarray([objective_score(values, key) for key in OBJECTIVES])


def _training_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("status") == "complete" and
            record.get("sampling_stability", {}).get("status", "stable") == "stable"]


def _record_surface_score(record: dict[str, Any],
                          search: dict[str, Any]) -> float | None:
    result = record.get("surface_diagnostics", {})
    dimensions = search.get("geometry_context", {})
    score = result.get("score") or surface_score(result, {
        "horizontal": dimensions.get("mouth_width_mm", 0),
        "vertical": dimensions.get("mouth_height_mm", 0),
    })
    if not score:
        return None
    value = float(score["overall_percent"])
    return value if math.isfinite(value) else None


def _uniform_s_sweep(search: dict[str, Any]) -> bool:
    """Identify the fixed, symmetric S grids generated for the coverage study."""
    pool = search.get("initial_pool", [])
    if not pool or search.get("initial_candidates") != len(pool):
        return False
    return all("S=" in str(item.get("label", "")) for item in pool)


def required_initial_probe(search: dict[str, Any], proposal_index: int,
                           source: str) -> bool:
    """Return whether an authored initial point must bypass adaptive pruning."""
    if source != "initial-curated" or proposal_index <= 0:
        return False
    pool = search.get("initial_pool", [])
    index = proposal_index - 1
    return index < len(pool) and bool(pool[index].get("required", False))


def adaptive_pruning_decision(search: dict[str, Any],
                              records: list[dict[str, Any]],
                              values: dict[str, float],
                              derived: dict[str, float]) -> dict[str, Any] | None:
    """Return evidence for skipping a confidently poor tail of a fixed S sweep.

    S-grid candidates arrive in ascending S order. Pruning is deliberately limited
    to extrapolating that tail after at least five real solves and three consecutive
    score declines. A quadratic regression supplies the trend and its prediction
    uncertainty; a configurable uncertainty floor prevents deterministic-looking
    curves from becoming overconfident.
    """
    policy = search.get("adaptive_pruning", {})
    if search.get("s_sensitivity_sampling", {}).get("enabled", False):
        return None
    # Pruning is opt-in. Short local/canonical S sets use compatible labels but
    # intentionally require every authored comparison point.
    enabled = policy.get("enabled", False)
    if not enabled or not _uniform_s_sweep(search):
        return None
    target_s_h = float(derived.get("s_h", math.nan))
    target_s_v = float(derived.get("s_v", math.nan))
    if (not math.isfinite(target_s_h) or not math.isfinite(target_s_v) or
            not math.isclose(target_s_h, target_s_v, rel_tol=0, abs_tol=0.01)):
        return None
    samples = []
    for record in records:
        if record.get("status") != "complete":
            continue
        score = _record_surface_score(record, search)
        s_h = float(record.get("derived", {}).get("s_h", math.nan))
        s_v = float(record.get("derived", {}).get("s_v", math.nan))
        if (score is not None and math.isfinite(s_h) and math.isfinite(s_v) and
                math.isclose(s_h, s_v, rel_tol=0, abs_tol=0.01)):
            samples.append(((s_h + s_v) / 2, score))
    samples.sort()
    minimum = int(policy.get(
        "minimum_evaluations", DEFAULT_ADAPTIVE_PRUNING_MIN_EVALUATIONS))
    if len(samples) < max(5, minimum):
        return None
    target_s = (target_s_h + target_s_v) / 2
    if target_s <= samples[-1][0] + 1e-6:
        return None
    decline_count = int(policy.get("required_consecutive_declines", 3))
    recent_scores = np.asarray([score for _, score in samples[-(decline_count + 1):]])
    if len(recent_scores) < decline_count + 1 or not np.all(np.diff(recent_scores) < 0):
        return None

    s_values = np.asarray([s for s, _ in samples])
    scores = np.asarray([score for _, score in samples])
    best_index = int(np.argmax(scores))
    if (0 < best_index < len(samples) - 1 and
            len(samples) - best_index - 1 >= decline_count):
        return {
            "reason": "winner is bracketed and the measured tail keeps declining",
            "target_s": target_s,
            "best_observed_score": float(scores[best_index]),
            "best_observed_s": float(s_values[best_index]),
            "consecutive_declines": decline_count,
            "observed_points": len(samples),
            "values": values,
        }
    design = np.column_stack((np.ones(len(samples)), s_values, s_values ** 2))
    coefficients, _, _, _ = np.linalg.lstsq(design, scores, rcond=None)
    target = np.asarray([1.0, target_s, target_s ** 2])
    predicted = float(target @ coefficients)
    residuals = scores - design @ coefficients
    degrees_of_freedom = max(1, len(samples) - design.shape[1])
    residual_sigma = math.sqrt(float(residuals @ residuals) / degrees_of_freedom)
    leverage = float(target @ np.linalg.pinv(design.T @ design) @ target)
    uncertainty_floor = float(policy.get(
        "uncertainty_floor_points",
        DEFAULT_ADAPTIVE_PRUNING_UNCERTAINTY_FLOOR_POINTS))
    prediction_sigma = max(uncertainty_floor,
                           residual_sigma * math.sqrt(1 + leverage))
    confidence_sigma = float(policy.get(
        "confidence_sigma", DEFAULT_ADAPTIVE_PRUNING_CONFIDENCE_SIGMA))
    optimistic_score = predicted + confidence_sigma * prediction_sigma
    best_score = float(np.max(scores))
    margin = float(policy.get(
        "margin_points", DEFAULT_ADAPTIVE_PRUNING_MARGIN_POINTS))
    threshold = best_score - margin
    if optimistic_score >= threshold:
        return None
    return {
        "reason": "optimistic predicted score is below the useful tail threshold",
        "target_s": target_s,
        "predicted_score": predicted,
        "prediction_sigma": prediction_sigma,
        "optimistic_score": optimistic_score,
        "best_observed_score": best_score,
        "threshold_score": threshold,
        "confidence_sigma": confidence_sigma,
        "observed_points": len(samples),
        "values": values,
    }


def sensitivity_sampling_decision(search: dict[str, Any],
                                  records: list[dict[str, Any]],
                                  values: dict[str, float],
                                  derived: dict[str, float]) -> dict[str, Any] | None:
    """Skip an insensitive authored S point after the common skeleton is known."""
    policy = search.get("s_sensitivity_sampling", {})
    if not policy.get("enabled", False) or not _uniform_s_sweep(search):
        return None
    target_h = float(derived.get("s_h", math.nan))
    target_v = float(derived.get("s_v", math.nan))
    if (not math.isfinite(target_h) or not math.isfinite(target_v) or
            not math.isclose(target_h, target_v, rel_tol=0, abs_tol=0.01)):
        return None
    points = []
    for record in records:
        if record.get("status") != "complete":
            continue
        score = _record_surface_score(record, search)
        s_h = float(record.get("derived", {}).get("s_h", math.nan))
        s_v = float(record.get("derived", {}).get("s_v", math.nan))
        if (score is not None and math.isfinite(s_h) and math.isfinite(s_v) and
                math.isclose(s_h, s_v, rel_tol=0, abs_tol=0.01)):
            points.append(SPoint((s_h + s_v) / 2, score))
    skeleton = [float(value) for value in policy.get("mandatory_s", [])]
    if any(not any(abs(point.s - required) <= 0.02 for point in points)
           for required in skeleton):
        return None
    target_s = (target_h + target_v) / 2
    reason = interval_refinement_reason(
        points, target_s,
        float(policy.get("variation_points", 0.75)),
        float(policy.get("winner_resolution", 0.3)))
    if reason is not None:
        return None
    measured = sorted(points, key=lambda point: point.s)
    lower = max((point for point in measured if point.s < target_s),
                key=lambda point: point.s)
    upper = min((point for point in measured if point.s > target_s),
                key=lambda point: point.s)
    return {
        "reason": "measured interval is insensitive and already resolved",
        "target_s": target_s,
        "interval_s": [lower.s, upper.s],
        "interval_scores": [lower.score, upper.score],
        "score_variation": abs(upper.score - lower.score),
        "variation_threshold": float(policy.get("variation_points", 0.75)),
        "values": values,
    }


def adaptive_kn_pruning_decision(search: dict[str, Any],
                                 records: list[dict[str, Any]],
                                 values: dict[str, float]) -> dict[str, Any] | None:
    """Screen K/N extremes and interactions after measuring the local cross."""
    policy = search.get("adaptive_kn", {})
    if not policy.get("enabled", False):
        return None
    k_h, k_v = float(values["k_h"]), float(values["k_v"])
    n_h, n_v = float(values["n_h"]), float(values["n_v"])
    if (not math.isclose(k_h, k_v, abs_tol=1e-6) or
            not math.isclose(n_h, n_v, abs_tol=1e-6)):
        return None
    target = (round(k_h, 6), round(n_h, 6))
    always_measure = {(4.0, 10.0), (3.5, 10.0), (4.5, 10.0),
                      (4.0, 5.0), (4.0, 15.0)}
    if target in always_measure:
        return None
    measured: dict[tuple[float, float], float] = {}
    for record in records:
        if record.get("status") != "complete":
            continue
        record_values = record.get("values", {})
        key = (round(float(record_values.get("k_h", math.nan)), 6),
               round(float(record_values.get("n_h", math.nan)), 6))
        score = _record_surface_score(record, search)
        if score is not None:
            measured[key] = score
    baseline = measured.get((4.0, 10.0))
    if baseline is None:
        return None
    best = max(measured.values())
    margin = float(policy.get("margin_points", 3.0))
    uncertainty = float(policy.get("uncertainty_points", 1.5))
    threshold = best - margin
    adjacent = {
        (3.0, 10.0): (3.5, 10.0),
        (5.0, 10.0): (4.5, 10.0),
        (4.0, 2.0): (4.0, 5.0),
        (4.0, 20.0): (4.0, 15.0),
    }
    if target in adjacent:
        neighbor = measured.get(adjacent[target])
        if neighbor is None:
            return None
        optimistic = neighbor + uncertainty
        if optimistic >= threshold:
            return None
        return {
            "reason": "adjacent K/N trend is confidently below the useful range",
            "target_k": target[0], "target_n": target[1],
            "predicted_score": neighbor,
            "optimistic_score": optimistic,
            "best_observed_score": best, "threshold_score": threshold,
            "evidence_point": {"k": adjacent[target][0],
                               "n": adjacent[target][1], "score": neighbor},
            "values": values,
        }
    if target[0] in (3.5, 4.5) and target[1] in (5.0, 15.0):
        k_score = measured.get((target[0], 10.0))
        n_score = measured.get((4.0, target[1]))
        if k_score is None or n_score is None:
            return None
        predicted = baseline + (k_score - baseline) + (n_score - baseline)
        optimistic = predicted + uncertainty * math.sqrt(2)
        if optimistic >= threshold:
            return None
        return {
            "reason": "K/N main effects predict an inferior interaction",
            "target_k": target[0], "target_n": target[1],
            "predicted_score": predicted,
            "optimistic_score": optimistic,
            "best_observed_score": best, "threshold_score": threshold,
            "k_axis_score": k_score, "n_axis_score": n_score,
            "values": values,
        }
    return None


def next_kn_closure_candidate(search: dict[str, Any],
                              records: list[dict[str, Any]],
                              closure: dict[str, Any]) -> tuple[dict[str, float], str] | None:
    """Return the next probe needed to bracket the measured K/N optimum.

    A closure search follows the best measured point rather than assuming K and
    N are additive.  It measures the full local 3x3 neighborhood, then either
    stops when that neighborhood is a score plateau or halves the spacing until
    the authored resolution is reached.
    """
    policy = search.get("adaptive_kn_closure", {})
    if not policy.get("enabled", False):
        return None
    measured: dict[tuple[float, float], tuple[float, dict[str, float]]] = {}
    for record in records:
        if record.get("status") != "complete":
            continue
        values = record.get("values", {})
        if not (math.isclose(float(values.get("k_h", math.nan)),
                             float(values.get("k_v", math.nan)), abs_tol=1e-6) and
                math.isclose(float(values.get("n_h", math.nan)),
                             float(values.get("n_v", math.nan)), abs_tol=1e-6)):
            continue
        score = _record_surface_score(record, search)
        if score is not None:
            key = (round(float(values["k_h"]), 6),
                   round(float(values["n_h"]), 6))
            measured[key] = (score, values)
    if not measured:
        closure.update(status="unresolved", reason="no completed symmetric K/N points")
        return None

    best_key, (best_score, best_values) = max(
        measured.items(), key=lambda item: item[1][0])
    k_min = float(policy.get("minimum_k", 1.0))
    k_max = float(policy.get("maximum_k", 7.0))
    n_min = float(policy.get("minimum_n", 2.0))
    n_max = float(policy.get("maximum_n", 40.0))
    min_k_step = float(policy.get("minimum_k_step", 0.5))
    min_n_step = float(policy.get("minimum_n_step", 1.0))
    k_step = max(min_k_step, float(closure.setdefault(
        "k_step", policy.get("initial_k_step", 0.5))))
    n_step = max(min_n_step, float(closure.setdefault(
        "n_step", policy.get("initial_n_step", 5.0))))
    closure.update(k_step=k_step, n_step=n_step)
    closure.update(status="running", incumbent_k=best_key[0],
                   incumbent_n=best_key[1], incumbent_score=best_score)

    # A poor high-N result at high S does not establish that its K is poor.
    # Test the same length and K with lower N before leaving that K region.
    rescue_enabled = bool(policy.get("high_s_low_n_rescue", True))
    rescue_min_s = float(policy.get("rescue_minimum_s", 2.0))
    rescue_min_n = float(policy.get("rescue_minimum_n", 8.0))
    rescue_n_step = float(policy.get("rescue_n_step", 2.0))
    rescue_margin = float(policy.get("rescue_score_margin_points", 3.0))
    rescue_candidates = []
    if rescue_enabled:
        for record in records:
            if record.get("status") != "complete":
                continue
            values = record.get("values", {})
            derived = record.get("derived", {})
            k_h, k_v = float(values.get("k_h", math.nan)), float(
                values.get("k_v", math.nan))
            n_h, n_v = float(values.get("n_h", math.nan)), float(
                values.get("n_v", math.nan))
            s_h, s_v = float(derived.get("s_h", math.nan)), float(
                derived.get("s_v", math.nan))
            score = _record_surface_score(record, search)
            if (score is None or not all(math.isfinite(item) for item in
                    (k_h, k_v, n_h, n_v, s_h, s_v)) or
                    not math.isclose(k_h, k_v, abs_tol=1e-6) or
                    not math.isclose(n_h, n_v, abs_tol=1e-6) or
                    min(s_h, s_v) < rescue_min_s or n_h < rescue_min_n or
                    score > best_score - rescue_margin):
                continue
            lower_n = round(max(n_min, n_h - rescue_n_step), 6)
            if lower_n >= n_h - 1e-6 or (round(k_h, 6), lower_n) in measured:
                continue
            rescue_candidates.append((score, n_h, k_h, lower_n, values))
    if rescue_candidates:
        score, source_n, k, lower_n, source_values = max(
            rescue_candidates, key=lambda item: (item[0], -item[1]))
        values = dict(source_values)
        values.update(k_h=k, k_v=k, n_h=lower_n, n_v=lower_n)
        closure["last_rescue"] = {
            "k": k, "from_n": source_n, "to_n": lower_n,
            "source_score": score, "best_score": best_score,
            "minimum_s": rescue_min_s, "score_margin_points": rescue_margin,
        }
        return values, (
            f"high-S low-N rescue K={k:g}, N={source_n:g}→{lower_n:g}")

    axial_offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    diagonal_offsets = ((-1, -1), (-1, 1), (1, -1), (1, 1))
    neighborhood = [(best_key, best_score)]
    for dk, dn in axial_offsets:
        k = round(best_key[0] + dk * k_step, 6)
        n = round(best_key[1] + dn * n_step, 6)
        if not (k_min <= k <= k_max and n_min <= n <= n_max):
            continue
        if (k, n) not in measured:
            values = dict(best_values)
            values.update(k_h=k, k_v=k, n_h=n, n_v=n)
            return values, f"K/N closure K={k:g}, N={n:g}"
        neighborhood.append(((k, n), measured[(k, n)][0]))

    plateau_tolerance = float(policy.get(
        "plateau_score_tolerance_points", 0.5))
    initial_k_step = float(policy.get("initial_k_step", 0.5))
    initial_n_step = float(policy.get("initial_n_step", 5.0))
    refinement_stage = (k_step < initial_k_step - 1e-9 or
                        n_step < initial_n_step - 1e-9)
    axial_spread = best_score - min(score for _, score in neighborhood)
    best_at_upper_limit = (
        math.isclose(best_key[0], k_max, abs_tol=1e-6) or
        math.isclose(best_key[1], n_max, abs_tol=1e-6))
    if (plateau_tolerance > 0 and refinement_stage and
            not best_at_upper_limit and
            axial_spread <= plateau_tolerance + 1e-9):
        keys = [key for key, _ in neighborhood]
        closure.update(
            status="closed",
            reason=(f"refined axial K/N score asymptote: neighborhood is "
                    f"within {axial_spread:.3f} points; fine diagonals omitted"),
            closure_method="refined-axial-score-asymptote",
            plateau_score_tolerance_points=plateau_tolerance,
            plateau_score_spread_points=axial_spread,
            plateau_k_bounds=[min(key[0] for key in keys),
                              max(key[0] for key in keys)],
            plateau_n_bounds=[min(key[1] for key in keys),
                              max(key[1] for key in keys)],
            plateau_points=[
                {"k": key[0], "n": key[1], "score": score}
                for key, score in sorted(neighborhood)
            ],
            resolution_k=k_step,
            resolution_n=n_step,
        )
        return None

    for dk, dn in diagonal_offsets:
        k = round(best_key[0] + dk * k_step, 6)
        n = round(best_key[1] + dn * n_step, 6)
        if not (k_min <= k <= k_max and n_min <= n <= n_max):
            continue
        if (k, n) not in measured:
            values = dict(best_values)
            values.update(k_h=k, k_v=k, n_h=n, n_v=n)
            return values, f"K/N closure K={k:g}, N={n:g}"
        neighborhood.append(((k, n), measured[(k, n)][0]))

    # Once the complete local neighborhood is effectively flat, more precise
    # K/N coordinates are false precision. Preserve the measured plateau and
    # hand the coupled program to its local S/length stage.
    plateau_floor = min(score for _, score in neighborhood)
    plateau_spread = best_score - plateau_floor
    if (plateau_tolerance > 0 and not best_at_upper_limit and
            plateau_spread <= plateau_tolerance + 1e-9):
        keys = [key for key, _ in neighborhood]
        closure.update(
            status="closed",
            reason=(f"local K/N score asymptote: complete neighborhood is "
                    f"within {plateau_spread:.3f} points"),
            closure_method="score-asymptote",
            plateau_score_tolerance_points=plateau_tolerance,
            plateau_score_spread_points=plateau_spread,
            plateau_k_bounds=[min(key[0] for key in keys),
                              max(key[0] for key in keys)],
            plateau_n_bounds=[min(key[1] for key in keys),
                              max(key[1] for key in keys)],
            plateau_points=[
                {"k": key[0], "n": key[1], "score": score}
                for key, score in sorted(neighborhood)
            ],
            resolution_k=k_step,
            resolution_n=n_step,
        )
        return None

    next_k_step = max(min_k_step, k_step / 2)
    next_n_step = max(min_n_step, n_step / 2)
    if next_k_step < k_step - 1e-9 or next_n_step < n_step - 1e-9:
        closure.update(k_step=next_k_step, n_step=next_n_step)
        return next_kn_closure_candidate(search, records, closure)

    upper_limits = []
    if math.isclose(best_key[0], k_max, abs_tol=1e-6):
        upper_limits.append("K maximum")
    if math.isclose(best_key[1], n_max, abs_tol=1e-6):
        upper_limits.append("N maximum")
    if upper_limits:
        closure.update(status="boundary-limited",
                       reason=f"best point reached {' and '.join(upper_limits)}")
    else:
        closure.update(status="closed", reason="all axial and diagonal neighbors measured",
                       resolution_k=min_k_step, resolution_n=min_n_step)
    return None


def pareto_indices(records: list[dict[str, Any]]) -> set[int]:
    feasible = [(index, record) for index, record in enumerate(records)
                if record.get("status") == "complete" and
                record.get("sampling_stability", {}).get("status", "stable") == "stable" and
                all(key in record.get("diagnostics", {}).get("combined", {})
                    for key in OBJECTIVES)]
    output: set[int] = set()
    for index, record in feasible:
        values = _objective_values(record)
        dominated = False
        for other_index, other in feasible:
            if other_index == index:
                continue
            other_values = _objective_values(other)
            if np.all(other_values >= values) and np.any(other_values > values):
                dominated = True
                break
        if not dominated:
            output.add(index)
    return output


def _gp_predict(x: np.ndarray, y: np.ndarray,
                candidates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    length_scale = 0.28
    delta = x[:, None, :] - x[None, :, :]
    kernel = np.exp(-np.sum(delta * delta, axis=2) / (2 * length_scale ** 2))
    kernel.flat[::len(x) + 1] += 1e-6
    inverse_y = np.linalg.solve(kernel, y)
    cross_delta = candidates[:, None, :] - x[None, :, :]
    cross = np.exp(-np.sum(cross_delta * cross_delta, axis=2) /
                   (2 * length_scale ** 2))
    mean = cross @ inverse_y
    solved = np.linalg.solve(kernel, cross.T)
    variance = np.maximum(1e-9, 1 - np.sum(cross * solved.T, axis=1))
    return mean, np.sqrt(variance)


def geometry_feature_vector(search: dict[str, Any], values: dict[str, float]) -> np.ndarray | None:
    """Map authored inputs to realized, symmetric H/V termination geometry."""
    context = search["geometry_context"]
    effective_radius = (context["throat_radius_mm"] + values["extension_mm"] *
                        math.tan(math.radians(context["throat_angle_deg"])))
    features = []
    for axis, coverage_key, k_key, mouth_key, n_key in (
            ("h", "osse_coverage_h_deg", "k_h", "mouth_width_mm", "n_h"),
            ("v", "osse_coverage_v_deg", "k_v", "mouth_height_mm", "n_v")):
        end_radius = context[mouth_key] / 2
        metrics = termination_metrics(
            values["length_mm"], effective_radius, values[coverage_key], values[k_key],
            values[n_key], end_radius, context["throat_angle_deg"])
        s_lower, s_upper = search["derived_s_bounds"]
        if (not s_lower <= metrics["s"] <= s_upper or
                metrics["final_tenth_radial_growth_fraction"] >
                MAX_FINAL_TENTH_RADIAL_GROWTH_FRACTION or
                not all(math.isfinite(item) for item in metrics.values())):
            return None
        features.extend((metrics["s"] / (1 + metrics["s"]),
                         metrics["exit_angle_deg"] / 90,
                         math.log1p(metrics["normalized_curvature_radius"])))
    return np.asarray(features)


def geometry_space_filling_probe(search: dict[str, Any],
                                 records: list[dict[str, Any]]) -> np.ndarray:
    """Choose a feasible coupled proposal farthest apart in realized geometry."""
    sampler = qmc.LatinHypercube(d=len(VARIABLES),
                                 seed=int(search.get("random_seed", 17)))
    pool = sampler.random(4096)
    feasible_vectors = []
    feasible_features = []
    for vector in pool:
        values = values_from_vector(vector, search["bounds"])
        features = geometry_feature_vector(search, values)
        if features is not None:
            feasible_vectors.append(vector)
            feasible_features.append(features)
    if not feasible_vectors:
        raise RuntimeError("initial candidate pool contains no nonnegative-S geometry")
    vectors = np.asarray(feasible_vectors)
    features = np.asarray(feasible_features)
    existing_values = [search["seed_values"]] + [record["values"] for record in records]
    existing_features = np.asarray([
        geometry_feature_vector(search, values) for values in existing_values])
    feature_distance = np.min(np.linalg.norm(
        features[:, None, :] - existing_features[None, :, :], axis=2), axis=1)
    raw_existing = np.asarray([normalized_vector(values, search["bounds"])
                               for values in existing_values])
    raw_distance = np.min(np.linalg.norm(
        vectors[:, None, :] - raw_existing[None, :, :], axis=2), axis=1)
    score = feature_distance + 0.25 * raw_distance
    score[raw_distance < search["minimum_candidate_distance"]] = -math.inf
    return vectors[int(np.argmax(score))]


def inferior_to_seed_probability(search: dict[str, Any],
                                 records: list[dict[str, Any]],
                                 vector: np.ndarray) -> float:
    """Probability that a proposal is worse than the seed on every objective."""
    completed = _training_records(records)
    seed_record = next((record for record in completed
                        if record.get("proposal_source") == "seed"), None)
    if seed_record is None or len(completed) < 7:
        return 0.0
    x = np.asarray([normalized_vector(record["values"], search["bounds"])
                    for record in completed])
    probabilities = []
    for column in range(len(OBJECTIVES)):
        seed_score = _objective_values(seed_record)[column] / 100
        deltas = np.asarray([(_objective_values(record)[column] / 100) - seed_score
                             for record in completed])
        mean, std = _gp_predict(x, deltas, vector[None, :])
        probabilities.append(float(norm.cdf(-mean[0] / max(std[0], 1e-6))))
    return float(np.prod(probabilities))


def learned_lever_effects(search: dict[str, Any],
                          records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Estimate diagnostic-point changes for +10% of each configured range."""
    completed = _training_records(records)
    seed_record = next((record for record in completed
                        if record.get("proposal_source") == "seed"), None)
    if seed_record is None or len(completed) < 4:
        return {}
    seed_vector = normalized_vector(search["seed_values"], search["bounds"])
    x = np.asarray([normalized_vector(record["values"], search["bounds"])
                    - seed_vector for record in completed])
    design = np.column_stack((np.ones(len(x)), x))
    regularizer = np.eye(design.shape[1]) * 0.05
    regularizer[0, 0] = 0
    outputs = list(OBJECTIVES)
    effects = {name: {} for name in VARIABLES}
    for output in outputs:
        seed_score = objective_score(seed_record["diagnostics"]["combined"], output)
        y = np.asarray([objective_score(record["diagnostics"]["combined"], output) -
                        seed_score
                        for record in completed])
        coefficients = np.linalg.solve(design.T @ design + regularizer,
                                       design.T @ y)[1:]
        for index, name in enumerate(VARIABLES):
            effects[name][output] = float(coefficients[index] * 0.10)
    return effects


def _coupled_axis_controls(search: dict[str, Any], length_mm: float,
                           axis: str, target_s: float, family: int) -> tuple[float, float]:
    """Select one coverage/K pair shared by a matched low/mid/high-N family."""
    context = search["geometry_context"]
    coverage_key = f"osse_coverage_{axis}_deg"
    k_key = f"k_{axis}"
    n_key = f"n_{axis}"
    mouth_key = "mouth_width_mm" if axis == "h" else "mouth_height_mm"
    sampler = qmc.LatinHypercube(d=2, seed=1000 + family * 2 + (axis == "v"))
    pool = sampler.random(4096)
    coverage_bounds = search["bounds"][coverage_key]
    k_bounds = search["bounds"][k_key]
    n_bounds = search["bounds"][n_key]
    seed_n = search["seed_values"][n_key]
    n_levels = (n_bounds[0], min(max(seed_n, n_bounds[0]), n_bounds[1]), n_bounds[1])
    effective_radius = context["throat_radius_mm"] + search["seed_values"]["extension_mm"] * math.tan(
        math.radians(context["throat_angle_deg"]))
    best: tuple[float, float, float] | None = None
    intended = search[f"intended_coverage_{axis}_deg"]
    for unit_coverage, unit_k in pool:
        coverage = coverage_bounds[0] + unit_coverage * (coverage_bounds[1] - coverage_bounds[0])
        k = k_bounds[0] + unit_k * (k_bounds[1] - k_bounds[0])
        metrics = [termination_metrics(
            length_mm, effective_radius, coverage, k, n,
            context[mouth_key] / 2, context["throat_angle_deg"])
            for n in n_levels]
        s_values = [item["s"] for item in metrics]
        if not all(search["derived_s_bounds"][0] <= s <= search["derived_s_bounds"][1]
                   for s in s_values):
            continue
        # Target the middle-N geometry while mildly preferring authored coverage;
        # K is selected jointly rather than repaired after proposal.
        score = abs(s_values[1] - target_s) + 0.08 * abs(coverage - intended) / (
            coverage_bounds[1] - coverage_bounds[0])
        if best is None or score < best[0]:
            best = (score, coverage, k)
    if best is None:
        raise RuntimeError(f"no feasible matched N family for {axis} at {length_mm:g} mm")
    return best[1], best[2]


def structured_initial_values(search: dict[str, Any], proposal_index: int) -> dict[str, float]:
    """Return one member of four length families crossed with three N levels."""
    if search.get("initial_pool"):
        return dict(search["initial_pool"][proposal_index - 1]["values"])
    family = (proposal_index - 1) // 3
    n_level = (proposal_index - 1) % 3
    if not 0 <= family < 4:
        raise ValueError("structured initial proposal index exceeds 12 candidates")
    length_bounds = search["bounds"]["length_mm"]
    length = float(np.linspace(length_bounds[0], length_bounds[1], 4)[family])
    target_s = (0.05, 0.30, 0.80, 1.50)[family]
    h_coverage, h_k = _coupled_axis_controls(search, length, "h", target_s, family)
    v_coverage, v_k = _coupled_axis_controls(search, length, "v", target_s, family)
    values = dict(search["seed_values"])
    values.update(length_mm=length,
                  extension_mm=search["seed_values"]["extension_mm"],
                  osse_coverage_h_deg=h_coverage,
                  osse_coverage_v_deg=v_coverage,
                  k_h=h_k, k_v=v_k)
    for axis in ("h", "v"):
        lower, upper = search["bounds"][f"n_{axis}"]
        seed_n = search["seed_values"][f"n_{axis}"]
        values[f"n_{axis}"] = (lower, min(max(seed_n, lower), upper), upper)[n_level]
    return values


def propose_vector(search: dict[str, Any], records: list[dict[str, Any]],
                   proposal_index: int) -> tuple[np.ndarray, str]:
    bounds = search["bounds"]
    if proposal_index == 0:
        return np.clip(normalized_vector(search["seed_values"], bounds), 0, 1), "seed"
    initial = int(search["initial_candidates"])
    if proposal_index <= initial:
        values = structured_initial_values(search, proposal_index)
        source = "initial-curated" if search.get("initial_pool") else "initial-length-N-family"
        return normalized_vector(values, bounds), source

    completed = _training_records(records)
    if len(completed) < 3:
        rng = np.random.default_rng(int(search.get("random_seed", 17)) + proposal_index)
        vector = rng.random(len(VARIABLES))
        vector[VARIABLES.index("extension_mm")] = normalized_vector(
            search["seed_values"], bounds)[VARIABLES.index("extension_mm")]
        return vector, "fallback-exploration"
    x = np.asarray([normalized_vector(record["values"], bounds) for record in completed])
    y = np.asarray([_objective_values(record) / 100 for record in completed])
    rng = np.random.default_rng(int(search.get("random_seed", 17)) + proposal_index)
    pool = rng.random((4096, len(VARIABLES)))
    # Extension and impedance/loading are reserved for a separate study.
    extension_index = VARIABLES.index("extension_mm")
    pool[:, extension_index] = normalized_vector(
        search["seed_values"], bounds)[extension_index]
    distance = np.min(np.linalg.norm(pool[:, None, :] - x[None, :, :], axis=2), axis=1)
    pool = pool[distance > search["minimum_candidate_distance"]]
    weights = rng.dirichlet(np.ones(len(OBJECTIVES)))
    objective = np.zeros(len(pool))
    uncertainty = np.zeros(len(pool))
    for column in range(len(OBJECTIVES)):
        mean, std = _gp_predict(x, y[:, column], pool)
        objective += weights[column] * mean
        uncertainty += weights[column] * std
    acquisition = objective + 0.35 * uncertainty
    return pool[int(np.argmax(acquisition))], "pareto-surrogate"


def crossover_loading(run: dict[str, Any], crossover_hz: float) -> tuple[float, float]:
    impedance = run.get("normalized_impedance")
    if impedance is None:
        return 0.0, 0.0
    lower = crossover_hz / 2 ** (1 / 6)
    upper = crossover_hz * 2 ** (1 / 6)
    grid = np.geomspace(lower, upper, 17)
    frequencies = np.asarray(run["frequencies"])
    magnitude = np.abs(impedance)
    interpolated = np.interp(np.log(grid), np.log(frequencies), magnitude)
    minimum = float(np.min(interpolated))
    return min(100.0, 100.0 * minimum / 0.7), minimum


def sampling_stability(run: dict[str, Any], fixed_grid: np.ndarray,
                       crossover_hz: float, threshold_points: float) -> dict[str, Any]:
    """Compare full diagnostics with a factor-two decimation of solved frequencies."""
    count = len(run["frequencies"])
    indices = np.arange(0, count, 2)
    if indices[-1] != count - 1:
        indices = np.append(indices, count - 1)
    decimated = dict(run)
    for key in ("frequencies", "horizontal", "vertical", "impedance",
                "normalized_impedance"):
        if run.get(key) is not None:
            decimated[key] = np.asarray(run[key])[indices]
    full = coverage_diagnostics(run, fixed_grid, fixed_band=True)
    coarse = coverage_diagnostics(decimated, fixed_grid, fixed_band=True)
    if full.get("status") != "available" or coarse.get("status") != "available":
        return {"status": "unstable", "reason": "diagnostics unavailable after decimation"}
    deltas = {key: float(coarse["combined"][key] - full["combined"][key])
              for key in OBJECTIVES}
    maximum = max(abs(value) for value in deltas.values())
    return {"status": "stable" if maximum <= threshold_points else "unstable",
            "maximum_delta_points": maximum, "decimated_ppo_fraction": 0.5,
            "deltas": deltas, "threshold_points": threshold_points}


def write_report(output_dir: Path, state: dict[str, Any]) -> Path:
    records = state["candidates"]
    search = state["search"]
    seed = search["seed_values"]
    lower_frequency = float(search.get("lower_frequency_hz", search["crossover_hz"]))
    crossover_frequency = float(search["crossover_hz"])
    upper_frequency = float(search["upper_frequency_hz"])
    geometry = search.get("geometry_context", {})
    mouth_width = float(geometry.get("mouth_width_mm", 0))
    mouth_height = float(geometry.get("mouth_height_mm", 0))
    kn_study = bool(
        search.get("adaptive_kn", {}).get("enabled", False) or
        search.get("adaptive_kn_closure", {}).get("enabled", False))
    default_visible_columns = (
        {"surface-score", "beamwidth-score", "impedance-score", "k", "n"}
        if kn_study else {
            "surface-score", "beamwidth-score", "impedance-score", "containment-mean",
            "profile-rms", "slice-rms",
        })

    def hidden_attribute(column: str) -> str:
        return "" if column in default_visible_columns else " hidden"

    pareto = pareto_indices(records)
    for index, record in enumerate(records):
        record["pareto"] = index in pareto
    def final_score_cell(record: dict[str, Any]) -> str:
        result = record.get("surface_diagnostics", {})
        score = result.get("score") or surface_score(result, {
            "horizontal": mouth_width, "vertical": mouth_height})
        if not score:
            return "<td data-column='surface-score' data-sort=''>—</td>"
        value = float(score["overall_percent"])
        version = html.escape(str(score.get("version", "v1")))
        return (f"<td data-column='surface-score' data-sort='{value:.6f}'>"
                f"{value:.1f}% <small>{version}</small></td>")

    def impedance_score_cell(record: dict[str, Any]) -> str:
        result = record.get("throat_impedance_diagnostics", {})
        value = result.get("overall_percent")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return "<td data-column='impedance-score' data-sort=''>—</td>"
        return (
            f"<td data-column='impedance-score' data-sort='{float(value):.6f}'>"
            f"{float(value):.1f}%</td>"
        )

    def surface_cell(record: dict[str, Any], column: str,
                     path: tuple[str, ...], suffix: str = "",
                     scale: float = 1.0, hidden: bool = False) -> str:
        result = record.get("surface_diagnostics", {})
        values = []
        if result.get("status") == "available":
            for plane_name in ("horizontal", "vertical"):
                selected: Any = result.get(plane_name, {})
                for key in path:
                    selected = selected.get(key, {}) if isinstance(selected, dict) else {}
                if isinstance(selected, (int, float)) and math.isfinite(selected):
                    values.append(float(selected) * scale)
        hidden_attribute = " hidden" if hidden else ""
        if len(values) != 2:
            return (f"<td class='axis-pair' data-column='{column}'{hidden_attribute} "
                    "data-sort=''>—</td>")
        display = _axis_pair(f"{values[0]:.3g}{suffix}", f"{values[1]:.3g}{suffix}")
        sort_value = sum(values) / 2
        return (f"<td class='axis-pair' data-column='{column}'{hidden_attribute} "
                f"data-sort='{sort_value:.6f}'>{display}</td>")

    traits = candidate_traits(records, seed, search["bounds"])
    rows = []
    for record, fallback_trait in zip(records, traits):
        trait = record.get("experiment_label", fallback_trait)
        candidate_dir = f"candidates/{record['id']}"
        artifact_stem = record.get("artifact_stem", record["id"])
        stl_link = (f" · <a href='{candidate_dir}/{html.escape(record['stl_file'])}'>STL</a>"
                    if record.get("stl_file") else "")
        report_link = (f" · <a href='{html.escape(record['report_file'])}'>report</a>"
                       if record.get("report_file") else "")
        status = record["status"].title()
        coverage_pair = _axis_pair(
            f"{record['values']['osse_coverage_h_deg']:.1f}",
            f"{record['values']['osse_coverage_v_deg']:.1f}")
        k_pair = _axis_pair(f"{record['values']['k_h']:.2f}",
                            f"{record['values']['k_v']:.2f}")
        s_pair = _axis_pair(
            f"{record['derived'].get('s_h', float('nan')):.3f}",
            f"{record['derived'].get('s_v', float('nan')):.3f}")
        n_pair = _axis_pair(f"{record['values']['n_h']:g}",
                            f"{record['values']['n_v']:g}")
        length = float(record["values"]["length_mm"])
        length_mouth_ratio = mouth_width / length if length else float("nan")
        rows.append("<tr>" + "".join((
            f"<td data-sort='{html.escape(artifact_stem)}'><a href='{candidate_dir}/project.yaml'>{html.escape(artifact_stem)}</a>"
            f"{stl_link}{report_link}</td>",
            f"<td data-sort='{html.escape(status)}'>{html.escape(status)}</td>",
            final_score_cell(record),
            surface_cell(
                record,
                "beamwidth-score",
                ("beamwidth_quality", "overall_percent"),
                "%",
                hidden="beamwidth-score" not in default_visible_columns,
            ),
            impedance_score_cell(record),
            surface_cell(record, "containment-mean",
                         ("containment", "mean_fraction"), "%", 100,
                         hidden="containment-mean" not in default_visible_columns),
            surface_cell(record, "profile-rms",
                         ("distribution", "rms_profile_error_db"), " dB",
                         hidden="profile-rms" not in default_visible_columns),
            surface_cell(record, "outward-rise",
                         ("distribution", "rms_outward_rise_violation_db"),
                         " dB", hidden="outward-rise" not in default_visible_columns),
            surface_cell(record, "slice-rms",
                         ("slice_energy_stability", "rms_departure_db"), " dB",
                         hidden="slice-rms" not in default_visible_columns),
            surface_cell(record, "line-rms",
                         ("minus_six_line", "rms_coverage_error_deg"), "°",
                         hidden="line-rms" not in default_visible_columns),
            f"<td data-column='length' hidden data-sort='{length:.6f}'>{length:.1f}</td>",
            f"<td data-column='length-mouth-ratio' hidden data-sort='{length_mouth_ratio:.6f}'>{length_mouth_ratio:.3f}</td>",
            f"<td data-column='extension' hidden data-sort='{record['values']['extension_mm']:.6f}'>{record['values']['extension_mm']:.1f}</td>",
            f"<td class='axis-pair' data-column='osse' hidden data-sort='{record['values']['osse_coverage_h_deg']:.6f}'>"
            f"{coverage_pair}</td>",
            f"<td class='axis-pair' data-column='k'{hidden_attribute('k')} data-sort='{record['values']['k_h']:.6f}'>"
            f"{k_pair}</td>",
            f"<td class='axis-pair' data-column='s' hidden data-sort='{record['derived'].get('s_h', float('nan')):.6f}'>"
            f"{s_pair}</td>",
            f"<td class='axis-pair' data-column='n'{hidden_attribute('n')} data-sort='{record['values']['n_h']:.6f}'>"
            f"{n_pair}</td>",
            f"<td data-column='trait' hidden data-sort='{html.escape(trait)}'>{html.escape(trait)}</td>",
            f"<td data-column='mouth-height' hidden data-sort='{mouth_height:.6f}'>{mouth_height:g}</td>",
            f"<td data-column='mouth-width' hidden data-sort='{mouth_width:.6f}'>{mouth_width:g}</td>",
        )) + "</tr>")

    toggle_columns = tuple(
        (column, label, column in default_visible_columns) for column, label in (
        ("surface-score", "Final surface score"),
        ("beamwidth-score", "Three-contour beamwidth quality H / V"),
        ("impedance-score",
         f"Throat-impedance score v{DIAGNOSTIC_VERSION}"),
        ("containment-mean", "Mean containment H / V"),
        ("profile-rms", "Profile RMS error H / V"),
        ("outward-rise", "Outward-rise violation H / V"),
        ("slice-rms", "Slice-energy RMS departure H / V"),
        ("line-rms", "−6 dB RMS error H / V"),
        ("length", "Length mm"),
        ("length-mouth-ratio", "Length-mouth ratio"),
        ("extension", "Extension mm"),
        ("osse", "OS-SE H / V"),
        ("k", "K H / V"),
        ("s", "S H / V"),
        ("n", "N H / V"),
        ("trait", "Distinguishing trait"),
        ("mouth-height", "Mouth height"),
        ("mouth-width", "Mouth width"),
        )
    )
    column_toggles = "".join(
        f"<button type='button' class='column-toggle' data-column-toggle='{column}' "
        f"aria-pressed='{'true' if visible else 'false'}'>{html.escape(label)}</button>"
        for column, label, visible in toggle_columns)
    sensitivity_policy = search.get("s_sensitivity_sampling", {})
    sensitivity_text = ("Disabled" if not sensitivity_policy.get("enabled") else
                        "Mandatory S " + ", ".join(
                            f"{float(value):g}" for value in
                            sensitivity_policy.get("mandatory_s", [])) +
                        f"; refine above {float(sensitivity_policy.get('variation_points', 0.75)):g} score points; "
                        f"winner resolution S={float(sensitivity_policy.get('winner_resolution', 0.3)):g}")
    refresh = "<meta http-equiv='refresh' content='10'>" if state["status"] == "running" else ""
    document = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}
<title>BEM candidate search</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#4db6a8;--accent-strong:#69d6c8}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}
a{{color:var(--accent-strong)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:max-content}}
th,td{{padding:8px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}td.best{{background:#173c39;color:#9af0df;font-weight:700}}td.worst{{background:#482321;color:#ffaaa3;font-weight:700}}.summary{{display:flex;gap:30px;flex-wrap:wrap}}.summary p{{color:var(--muted)}}.summary strong{{color:var(--ink)}}
.axis-pair{{white-space:normal}}.sortable{{cursor:pointer;user-select:none}}[hidden]{{display:none!important}}
.column-controls{{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 12px}}.column-toggle{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}
</style></head><body><main><h1>BEM candidate search</h1><section class='summary'>
<p><strong>Status</strong><br>{html.escape(state['status'])}</p><p><strong>Phase</strong><br>{html.escape(state.get('phase', ''))}</p>
<p><strong>Progress</strong><br>{sum(r['status']=='complete' for r in records)}&nbsp;/<wbr> {state['max_evaluations']} evaluated</p>
<p><strong>Rejected proposals</strong><br>{state.get('rejected_count', 0)}</p>
<p><strong>Confidently inferior</strong><br>{state.get('surrogate_screened_count', 0)}</p>
<p><strong>Adaptive skips</strong><br>{state.get('adaptive_pruned_count', 0)}</p>
<p><strong>S sensitivity policy</strong><br>{html.escape(sensitivity_text)}</p>
<p><strong>K/N closure</strong><br>{html.escape(state.get('kn_closure', {}).get('status', 'not requested'))}</p>
<p><strong>Sweep band</strong><br>{lower_frequency:g}–{upper_frequency:g} Hz</p>
<p><strong>Crossover</strong><br>{crossover_frequency:g} Hz</p>
<p><strong>Diagnostic band</strong><br>{crossover_frequency:g}–{upper_frequency:g} Hz</p></section>
<section><p><strong>Sampling policy:</strong> training uses {search.get('solver', {}).get('points_per_octave', 12):g} PPO. Seed, representative probes, and finalists require {search.get('confirmation_points_per_octave', 20):g}-PPO confirmation before final selection.</p></section>
<section><h2>Candidates</h2><div class='column-controls' aria-label='Candidate table columns'>{column_toggles}</div><table class='sortable-table'><thead><tr><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-column='surface-score' data-sort='number'>Final surface score</th><th class='sortable' data-column='beamwidth-score'{hidden_attribute('beamwidth-score')} data-sort='number'>Three-contour beamwidth quality H&nbsp;/ V</th><th class='sortable' data-column='impedance-score' data-sort='number'>Throat-impedance score v{DIAGNOSTIC_VERSION}</th><th class='sortable' data-column='containment-mean'{hidden_attribute('containment-mean')} data-sort='number'>Mean containment H&nbsp;/ V</th><th class='sortable' data-column='profile-rms'{hidden_attribute('profile-rms')} data-sort='number'>Profile RMS error H&nbsp;/ V</th><th class='sortable' data-column='outward-rise'{hidden_attribute('outward-rise')} data-sort='number'>Outward-rise violation H&nbsp;/ V</th><th class='sortable' data-column='slice-rms'{hidden_attribute('slice-rms')} data-sort='number'>Slice-energy RMS departure H&nbsp;/ V</th><th class='sortable' data-column='line-rms'{hidden_attribute('line-rms')} data-sort='number'>−6 dB RMS error H&nbsp;/ V</th><th class='sortable' data-column='length' hidden data-sort='number'>Length mm</th><th class='sortable' data-column='length-mouth-ratio' hidden data-sort='number'>Length-mouth ratio</th><th class='sortable' data-column='extension' hidden data-sort='number'>Extension mm</th><th class='sortable' data-column='osse' hidden data-sort='number'>OS-SE H&nbsp;/ V</th><th class='sortable' data-column='k'{hidden_attribute('k')} data-sort='number'>K H&nbsp;/ V</th><th class='sortable' data-column='s' hidden data-sort='number'>S H&nbsp;/ V</th><th class='sortable' data-column='n'{hidden_attribute('n')} data-sort='number'>N H&nbsp;/ V</th><th class='sortable' data-column='trait' hidden data-sort='text'>Distinguishing trait</th><th class='sortable' data-column='mouth-height' hidden data-sort='number'>Mouth height</th><th class='sortable' data-column='mouth-width' hidden data-sort='number'>Mouth width</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><p>Surface score v1 remains the primary score and candidate-ranking basis. Experimental surface score v2.2 and its multiscale −3/−6/−9 dB beamwidth quality are retained only for side-by-side study. Proposals closer than normalized distance {state['search'].get('minimum_candidate_distance', DEFAULT_MINIMUM_CANDIDATE_DISTANCE):g} to a retained candidate are rejected without retaining their data. Uniform S sweeps may skip a declining tail only after five measured points. Adaptive K/N studies first measure the coarse field, then test axial and diagonal neighbors around each new winner. K/N is reported closed only after the winner is bracketed at the authored K and N resolution or reaches the accepted K=1 or N=2 lower limit.</p></section>
<script>
document.querySelectorAll('[data-column-toggle]').forEach((button) => {{
  button.addEventListener('click', () => {{
    const visible = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', String(visible));
    document.querySelectorAll(`[data-column="${{button.dataset.columnToggle}}"]`).forEach((cell) => {{
      cell.hidden = !visible;
    }});
  }});
}});
document.querySelectorAll('table.sortable-table').forEach((table) => {{
  const headers = Array.from(table.querySelectorAll('th[data-sort]'));
  let active = -1;
  let direction = 'desc';
  headers.forEach((header, index) => header.addEventListener('click', () => {{
    direction = active === index && direction === 'desc' ? 'asc' : 'desc';
    active = index;
    const multiplier = direction === 'asc' ? 1 : -1;
    const type = header.dataset.sort;
    const rows = Array.from(table.tBodies[0].rows);
    rows.sort((left, right) => {{
      const a = left.cells[index]?.dataset.sort ?? left.cells[index]?.textContent ?? '';
      const b = right.cells[index]?.dataset.sort ?? right.cells[index]?.textContent ?? '';
      if (type === 'number') {{
        const an = Number(a), bn = Number(b);
        return ((Number.isFinite(an) ? an : -Infinity) - (Number.isFinite(bn) ? bn : -Infinity)) * multiplier;
      }}
      return String(a).localeCompare(String(b), undefined, {{numeric:true, sensitivity:'base'}}) * multiplier;
    }});
    table.tBodies[0].replaceChildren(...rows);
    headers.forEach((item, itemIndex) => item.setAttribute('aria-sort', itemIndex === index ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'));
  }}));
}});
</script></main></body></html>"""
    path = output_dir / "search_report.html"
    temporary = path.with_suffix(".html.tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(path)
    return path


def save_state(output_dir: Path, state: dict[str, Any]) -> None:
    # Report generation refreshes the Pareto flags; persist that same snapshot.
    state.pop("finalist_comparison", None)
    write_report(output_dir, state)
    state_path = output_dir / "search_state.json"
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    temporary.replace(state_path)


def _isolated_sweep(result_queue: Any, project_path: Path, executable: Path,
                    run_root: Path, frequencies: np.ndarray,
                    solver: dict[str, Any]) -> None:
    """Run mesh generation and NumCalc where a native abort cannot kill search."""
    try:
        manifest = run_sweep(
            project_path, executable, run_root, frequencies,
            elements_per_wavelength=float(solver.get("elements_per_wavelength", 6)),
            angles=int(solver.get("angles", 91)),
            maximum_workers=int(solver.get("workers", 0)),
            memory_limit_gib=solver.get("memory_limit_gib"),
            max_iterations=int(solver.get("max_iterations", 250)),
            netgen_maxh_factor=float(solver.get("netgen_maxh_factor", 0.45)),
            geometry_side_samples=solver.get("geometry_side_samples"),
            geometry_axial_stations=solver.get("geometry_axial_stations"),
            quadrant_side_samples=solver.get("quadrant_side_samples"),
            quadrant_axial_stations=solver.get("quadrant_axial_stations"),
            resume=True)
        result_queue.put(("ok", manifest))
    except Exception as error:
        result_queue.put(("error", f"{type(error).__name__}: {error}"))


def isolated_sweep(project_path: Path, executable: Path, run_root: Path,
                   frequencies: np.ndarray, solver: dict[str, Any]) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_isolated_sweep,
                              args=(result_queue, project_path, executable, run_root,
                                    frequencies, solver))
    process.start()
    result = None
    while process.is_alive() and result is None:
        try:
            result = result_queue.get(timeout=0.25)
        except queue.Empty:
            pass
    if result is None:
        try:
            result = result_queue.get(timeout=2)
        except queue.Empty:
            result = None
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join()
        raise RuntimeError("mesh/sweep worker did not exit after returning its result")
    if process.exitcode != 0:
        raise RuntimeError(f"mesh/sweep worker exited abnormally ({process.exitcode})")
    result_queue.close()
    if result is None:
        raise RuntimeError("mesh/sweep worker returned no result")
    status, payload = result
    if status != "ok":
        raise RuntimeError(payload)
    return payload


def retain_diagnostic_archive(run_dir: Path, candidate_dir: Path) -> Path:
    """Keep the compact response surface needed to recompute diagnostics."""
    source = run_dir / "responses.npz"
    if not source.is_file():
        raise FileNotFoundError(source)
    target = candidate_dir / "bem" / "responses.npz"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(target)
    return target


def remove_solver_working_data(run_dir: Path, retained_archive: Path) -> None:
    """Delete a NumCalc work tree only after validating its retained archive."""
    if not run_dir.name.startswith("project-NumCalc-"):
        raise ValueError(f"refusing to remove unexpected solver directory: {run_dir}")
    if not retained_archive.is_file():
        raise FileNotFoundError(retained_archive)
    # Loading every array catches truncated ZIP members, not merely a readable
    # archive header. Diagnostics and reports can be regenerated from this file.
    with np.load(retained_archive, allow_pickle=False) as archive:
        if not archive.files:
            raise ValueError(f"empty retained response archive: {retained_archive}")
        for key in archive.files:
            np.asarray(archive[key])
    if run_dir.resolve() == retained_archive.parent.resolve():
        raise ValueError("retained archive must live outside solver work tree")
    shutil.rmtree(run_dir)


def evaluate_candidate(record: dict[str, Any], candidate_dir: Path,
                       executable: Path, frequencies: np.ndarray,
                       fixed_grid: np.ndarray, search: dict[str, Any],
                       solver: dict[str, Any], output_dir: Path) -> None:
    """Run or resume one candidate and update its ledger record in place."""
    started = time.perf_counter()
    try:
        manifest = isolated_sweep(candidate_dir / "project.yaml", executable,
                                  candidate_dir / "bem", frequencies, solver)
        run_dir = Path(manifest["run_dir"])
        artifact_stem = record["artifact_stem"]
        title = f"BEM {artifact_stem}"
        generate_review(run_dir, title=title, write_report=False)
        response_archive = retain_diagnostic_archive(run_dir, candidate_dir)
        run = load_run(run_dir, artifact_stem)
        diagnostics = coverage_diagnostics(run, fixed_grid, fixed_band=True)
        new_surface_diagnostics = surface_diagnostics(
            run, fixed_grid, fixed_band=True)
        new_impedance_diagnostics = throat_impedance_diagnostics(
            run["frequencies"],
            run["normalized_impedance"],
            search["crossover_hz"],
            search["upper_frequency_hz"],
        )
        report_path = candidate_dir / "bem" / f"{artifact_stem}_Report.html"
        single_report(run_dir, report_path, title=title,
                      evaluation_frequencies=fixed_grid, fixed_band=True,
                      name=artifact_stem)
        stability = sampling_stability(
            run, fixed_grid, search["crossover_hz"],
            search.get("sampling_stability_points", DEFAULT_SAMPLING_STABILITY_POINTS))
        loading_percent, loading_minimum = crossover_loading(
            run, search["crossover_hz"])
        remove_solver_working_data(run_dir, response_archive)
        record.update(
            status="complete",
            response_archive=str(response_archive.relative_to(output_dir)),
            report_file=str(report_path.relative_to(output_dir)),
            completed_at_unix=time.time(),
            diagnostics=diagnostics,
            surface_diagnostics=new_surface_diagnostics,
            throat_impedance_diagnostics=new_impedance_diagnostics,
            sampling_stability=stability,
            crossover_loading_percent=loading_percent,
            crossover_minimum_normalized_impedance=loading_minimum,
            elapsed_s=record.get("elapsed_s", 0) + time.perf_counter() - started,
            mesh_quadrant_panels=manifest["mesh_quadrant_panels"])
    except Exception as error:  # retain failure and continue the search
        record.update(status="failed", reason=f"{type(error).__name__}: {error}",
                      elapsed_s=record.get("elapsed_s", 0) + time.perf_counter() - started)


def requeue_failed_candidates(state: dict[str, Any]) -> int:
    """Queue failed retained candidates without creating new proposals."""
    count = 0
    for record in state.get("candidates", []):
        if record.get("status") == "failed":
            record["status"] = "queued"
            record["reason"] = "retrying previously failed BEM evaluation"
            count += 1
    return count


def run_search(search_path: Path, output_dir: Path, binary: Path | None,
               dry_run: bool = False, retry_failed: bool = False,
               retry_max_iterations: int | None = None) -> dict[str, Any]:
    search, seed_path, seed = load_search(search_path)
    config_hash = hashlib.sha256(search_path.read_bytes() + seed_path.read_bytes()).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "search_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state["configuration_hash"] != config_hash:
            raise ValueError("search or seed changed; use a new output directory")
    else:
        values = seed_values(seed)
        intent = seed["horncad_config"].get("operating_intent", {})
        search["intended_coverage_h_deg"] = float(search.get(
            "intended_coverage_h_deg", intent.get("horizontal_coverage_deg",
            seed["horncad_config"]["horizontal_basis"]["coverage_deg"])))
        search["intended_coverage_v_deg"] = float(search.get(
            "intended_coverage_v_deg", intent.get("vertical_coverage_deg",
            seed["horncad_config"]["vertical_basis"]["coverage_deg"])))
        search["seed_values"] = values
        search["fixed_parameters"] = {
            "n_h": float(seed["horncad_config"]["horizontal_basis"]["n"]),
            "n_v": float(seed["horncad_config"]["vertical_basis"]["n"]),
        }
        global_config = seed["horncad_config"]["global"]
        search["geometry_context"] = {
            "throat_radius_mm": float(global_config["throat_radius"]),
            "throat_angle_deg": float(global_config["throat_angle_deg"]),
            "mouth_width_mm": float(global_config["mouth_width"]),
            "mouth_height_mm": float(global_config["mouth_height"]),
            "n_h": float(seed["horncad_config"]["horizontal_basis"]["n"]),
            "n_v": float(seed["horncad_config"]["vertical_basis"]["n"]),
        }
        state = {
            "schema_version": 1, "status": "running", "phase": "initializing",
            "configuration_hash": config_hash, "search_yaml": str(search_path.resolve()),
            "seed_yaml": str(seed_path),
            "lower_frequency_hz": search["lower_frequency_hz"],
            "crossover_hz": search["crossover_hz"],
            "upper_frequency_hz": search["upper_frequency_hz"],
            "max_evaluations": search["max_evaluations"], "search": search,
            "candidates": [], "proposal_count": 0, "rejected_count": 0,
            "surrogate_screened_count": 0, "adaptive_pruned_count": 0,
            "adaptive_pruned_proposals": [],
            "started_at_unix": time.time(),
        }
        save_state(output_dir, state)
    retry_count = requeue_failed_candidates(state) if retry_failed else 0
    # Migrate early preflight ledgers: rejected proposals leave only aggregate
    # counts and no candidate directory, YAML, STL, or detailed rejection data.
    previous_rejected = [record for record in state["candidates"]
                         if record.get("status") == "rejected"]
    if "proposal_count" not in state:
        identifiers = [int(record["id"].rsplit("-", 1)[1])
                       for record in state["candidates"]]
        state["proposal_count"] = max(identifiers, default=-1) + 1
    state["rejected_count"] = int(state.get("rejected_count", 0)) + len(previous_rejected)
    state.setdefault("surrogate_screened_count", 0)
    if previous_rejected:
        for record in previous_rejected:
            shutil.rmtree(output_dir / "candidates" / record["id"], ignore_errors=True)
        state["candidates"] = [record for record in state["candidates"]
                               if record.get("status") != "rejected"]
    for record in state["candidates"]:
        if record.get("status") == "preflight" and record.get("reason") == "geometry feasible; BEM not run":
            record.pop("reason")
    for record in state["candidates"]:
        if record["status"] == "running":
            record["status"] = "queued"
            record["reason"] = "resuming interrupted BEM evaluation"
        elif record["status"] == "preflight" and not dry_run:
            record["status"] = "queued"
            record.pop("reason", None)
    search = state["search"]
    search.setdefault("lower_frequency_hz", search["crossover_hz"])
    state.setdefault("lower_frequency_hz", search["lower_frequency_hz"])
    search.setdefault("minimum_candidate_distance",
                      DEFAULT_MINIMUM_CANDIDATE_DISTANCE)
    search.setdefault("inferior_screen_probability", DEFAULT_INFERIOR_PROBABILITY)
    search.setdefault("sampling_stability_points", DEFAULT_SAMPLING_STABILITY_POINTS)
    search.setdefault("confirmation_points_per_octave", 16.0)
    search.setdefault("adaptive_pruning", {})
    state.setdefault("adaptive_pruned_count", 0)
    state.setdefault("adaptive_pruned_proposals", [])
    state.setdefault("kn_closure", {})
    search.setdefault("fixed_parameters", {
        "n_h": float(seed["horncad_config"]["horizontal_basis"]["n"]),
        "n_v": float(seed["horncad_config"]["vertical_basis"]["n"]),
    })
    global_config = seed["horncad_config"]["global"]
    search.setdefault("geometry_context", {
        "throat_radius_mm": float(global_config["throat_radius"]),
        "throat_angle_deg": float(global_config["throat_angle_deg"]),
        "mouth_width_mm": float(global_config["mouth_width"]),
        "mouth_height_mm": float(global_config["mouth_height"]),
        "n_h": float(seed["horncad_config"]["horizontal_basis"]["n"]),
        "n_v": float(seed["horncad_config"]["vertical_basis"]["n"]),
    })
    for record in state["candidates"]:
        if record.get("status") != "queued":
            continue
        _, refreshed_derived = materialize_candidate(
            seed, record["values"], search)
        record.setdefault("derived", {}).update(refreshed_derived)
        feasible, reason = geometry_feasibility(record["derived"])
        if feasible:
            continue
        record.update(status="geometry-rejected", reason=reason)
        state["rejected_count"] += 1
        if search["max_evaluations"] == 1:
            state["geometry_rejection"] = {
                "reason": reason,
                "values": record["values"],
                "derived": record["derived"],
                "rejected_at_unix": time.time(),
            }
            state.update(status="geometry-rejected",
                         phase=f"geometry rejected: {reason}")
            save_state(output_dir, state)
            return state
    executable = None if dry_run else find_numcalc(binary)
    solver = dict(search.get("solver", {}))
    if retry_failed:
        # A lower-density authored seed avoids native Netgen aborts at extreme
        # boundary geometries. Netgen still enforces the identical wavelength
        # edge limit on the final surface; only its faceted starting shell is
        # simplified for explicit recovery runs.
        solver["max_iterations"] = max(
            int(solver.get("max_iterations", 250)),
            int(retry_max_iterations or 500),
        )
        solver.setdefault("netgen_maxh_factor", 0.4)
        solver.setdefault("geometry_side_samples", 6)
        solver.setdefault("geometry_axial_stations", 8)
        solver.setdefault("quadrant_side_samples", 6)
        solver.setdefault("quadrant_axial_stations", 8)
    ppo = float(solver.get("points_per_octave", 12))
    epw = float(solver.get("elements_per_wavelength", 6))
    angles = int(solver.get("angles", 91))
    solve_start = search["lower_frequency_hz"]
    frequencies = ppo_frequency_grid(solve_start, search["upper_frequency_hz"], ppo)
    fixed_grid = np.geomspace(search["crossover_hz"], search["upper_frequency_hz"],
                              int(np.ceil(np.log2(search["upper_frequency_hz"] /
                                                   search["crossover_hz"]) * 48)) + 1)
    for record in state["candidates"]:
        candidate_dir = output_dir / "candidates" / record["id"]
        project_path = candidate_dir / "project.yaml"
        record["artifact_stem"] = candidate_artifact_stem(_read_yaml(project_path))
        stl = export_candidate_stl(project_path, candidate_dir,
                                   record["artifact_stem"])
        record["stl_file"] = stl.name
    if dry_run and state["proposal_count"] >= search["initial_candidates"] + 1:
        state.update(status="preflight", phase="initial candidates materialized")
        save_state(output_dir, state)
        return state
    max_proposals = search["max_evaluations"] * 10
    def work_remains() -> bool:
        if any(record["status"] == "queued" for record in state["candidates"]):
            return True
        if retry_failed:
            return False
        # A prescribed experiment records failed or rejected coordinates as
        # outcomes. It must never substitute an optimizer proposal merely to
        # reach a requested number of successful solves.
        if search.get("fixed_design", False):
            return state["proposal_count"] < search["max_evaluations"]
        closure_policy = search.get("adaptive_kn_closure", {})
        if (closure_policy.get("enabled", False) and
                state["proposal_count"] >= search["initial_candidates"] + 1):
            return (state["kn_closure"].get("status") not in
                    {"closed", "boundary-limited", "unresolved"} and
                    sum(record["status"] == "complete"
                        for record in state["candidates"]) < search["max_evaluations"])
        target_reached = (
            sum(record["status"] == "complete" for record in state["candidates"]) +
            state.get("adaptive_pruned_count", 0) >= search["max_evaluations"])
        return not target_reached and state["proposal_count"] < max_proposals

    while work_remains():
        queued = next((item for item in state["candidates"]
                       if item["status"] == "queued"), None)
        if queued is not None:
            record = queued
            candidate_id = record["id"]
            candidate_dir = output_dir / "candidates" / candidate_id
            proposal_index = int(record.get("proposal_index", 0))
        else:
            proposal_index = state["proposal_count"]
            state["proposal_count"] += 1
            closure_stage = (search.get("adaptive_kn_closure", {}).get("enabled", False) and
                             proposal_index >= search["initial_candidates"] + 1)
            closure_label = None
            if closure_stage:
                closure_proposal = next_kn_closure_candidate(
                    search, state["candidates"], state["kn_closure"])
                if closure_proposal is None:
                    state["proposal_count"] -= 1
                    save_state(output_dir, state)
                    break
                values, closure_label = closure_proposal
                source = "adaptive-kn-closure"
            else:
                vector, source = propose_vector(
                    search, state["candidates"], proposal_index)
                values = values_from_vector(vector, search["bounds"])
                if proposal_index == 0:
                    values = search["seed_values"]
            # Coupled proposals are evaluated as authored. Silent K repair would
            # change the experiment and corrupt learned parameter effects.
            document, derived = materialize_candidate(seed, values, search)
            feasible, reason = geometry_feasibility(derived)
            distance = candidate_distance(values, state["candidates"], search["bounds"])
            if not feasible:
                state["rejected_count"] += 1
                if search["max_evaluations"] == 1:
                    state["geometry_rejection"] = {
                        "reason": reason,
                        "values": values,
                        "derived": derived,
                        "rejected_at_unix": time.time(),
                    }
                    state.update(status="geometry-rejected",
                                 phase=f"geometry rejected: {reason}")
                    save_state(output_dir, state)
                    break
                save_state(output_dir, state)
                if (dry_run and proposal_index + 1 >=
                        min(search["max_evaluations"],
                            search["initial_candidates"] + 1)):
                    break
                continue
            if (source != "initial-curated" and
                    distance < search["minimum_candidate_distance"]):
                state["rejected_count"] += 1
                save_state(output_dir, state)
                continue
            curated_item = (search["initial_pool"][proposal_index - 1]
                            if source == "initial-curated" else None)
            required_probe = required_initial_probe(search, proposal_index, source)
            pruning = None if closure_stage or required_probe else (
                sensitivity_sampling_decision(
                    search, state["candidates"], values, derived) or
                adaptive_pruning_decision(
                    search, state["candidates"], values, derived) or
                adaptive_kn_pruning_decision(search, state["candidates"], values))
            if pruning is not None:
                pruning.update(proposal_index=proposal_index,
                               proposal_source=source,
                               experiment_label=(curated_item["label"]
                                                 if curated_item else None))
                state["adaptive_pruned_proposals"].append(pruning)
                state["adaptive_pruned_count"] += 1
                save_state(output_dir, state)
                continue
            if proposal_index > search["initial_candidates"] and not closure_stage:
                inferior_probability = inferior_to_seed_probability(
                    search, state["candidates"], normalized_vector(values, search["bounds"]))
                if inferior_probability >= search["inferior_screen_probability"]:
                    state["rejected_count"] += 1
                    state["surrogate_screened_count"] += 1
                    save_state(output_dir, state)
                    continue
            candidate_id = f"candidate-{len(state['candidates']):03d}"
            record = {"id": candidate_id, "status": "queued",
                      "proposal_index": proposal_index,
                      "proposal_source": source, "values": values,
                      "derived": derived,
                      "artifact_stem": candidate_artifact_stem(document),
                      "nearest_candidate_distance": distance}
            if source == "initial-curated":
                record["experiment_label"] = search["initial_pool"][
                    proposal_index - 1]["label"]
            elif closure_label:
                record["experiment_label"] = closure_label
            state["candidates"].append(record)
            candidate_dir = output_dir / "candidates" / candidate_id
            candidate_dir.mkdir(parents=True, exist_ok=True)
            project_path = candidate_dir / "project.yaml"
            project_path.write_text(
                yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            stl = export_candidate_stl(project_path, candidate_dir,
                                       record["artifact_stem"])
            record["stl_file"] = stl.name
        if dry_run:
            record.update(status="preflight")
            record.pop("reason", None)
            save_state(output_dir, state)
            if proposal_index + 1 >= min(search["max_evaluations"],
                                         search["initial_candidates"] + 1):
                break
            continue
        state["phase"] = f"BEM evaluation {candidate_id}"
        record["status"] = "running"
        save_state(output_dir, state)
        evaluate_candidate(record, candidate_dir, executable, frequencies, fixed_grid,
                           search, solver, output_dir)
        save_state(output_dir, state)
    complete = sum(record["status"] == "complete" for record in state["candidates"])
    remaining_failed = sum(
        record["status"] == "failed" for record in state["candidates"])
    if state.get("status") == "geometry-rejected":
        pass
    elif dry_run:
        state.update(status="preflight", phase="initial candidates materialized")
    elif retry_failed and remaining_failed:
        state.update(status="recovery-incomplete",
                     phase=(f"failed candidate recovery incomplete: "
                            f"{remaining_failed} still failed"),
                     retry_requested=retry_count)
    elif (search.get("adaptive_kn_closure", {}).get("enabled", False) and
          state["kn_closure"].get("status") in {"closed", "boundary-limited"}):
        state.update(status="complete", phase="K/N closure complete",
                     completed_at_unix=time.time())
    elif search.get("adaptive_kn_closure", {}).get("enabled", False):
        state.update(status="stopped", phase="K/N closure evaluation budget exhausted")
    elif complete + state.get("adaptive_pruned_count", 0) >= search["max_evaluations"]:
        state.update(status="complete", phase="candidate evaluation complete",
                     completed_at_unix=time.time())
    else:
        state.update(status="stopped", phase="proposal limit reached")
    save_state(output_dir, state)
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search_yaml", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="materialize and geometry-check the initial design set")
    parser.add_argument("--retry-failed", action="store_true",
                        help="retry retained failed candidates without new proposals")
    parser.add_argument(
        "--retry-max-iterations",
        type=int,
        help="NumCalc iteration ceiling for an explicit retained-candidate retry",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.dry_run and args.retry_failed:
        raise ValueError("--dry-run and --retry-failed cannot be combined")
    if args.retry_max_iterations is not None and not args.retry_failed:
        raise ValueError("--retry-max-iterations requires --retry-failed")
    state = run_search(args.search_yaml, args.output_dir, args.binary,
                       args.dry_run, args.retry_failed,
                       args.retry_max_iterations)
    print(f"search report: {args.output_dir / 'search_report.html'}")
    print(f"status: {state['status']}")


if __name__ == "__main__":
    main()
