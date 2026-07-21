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
    from .run_bem_suite import find_numcalc
    from .run_numcalc_sweep import ppo_frequency_grid, run_sweep
except ImportError:
    from export_horncad import solved_s, termination_metrics
    from generate_numcalc_review import generate_review
    from interactive_results import coverage_diagnostics, load_run, single_report
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
    if search["max_evaluations"] < 2 or search["initial_candidates"] < 1:
        raise ValueError("search requires at least two evaluations")
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
    }


def geometry_feasibility(derived: dict[str, float]) -> tuple[bool, str | None]:
    if not all(math.isfinite(value) for value in derived.values()):
        return False, "derived geometry is not finite"
    if derived["s_h"] < 0:
        return False, "horizontal s is negative"
    if derived["s_v"] < 0:
        return False, "vertical s is negative"
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
    pareto = pareto_indices(records)
    for index, record in enumerate(records):
        record["pareto"] = index in pareto
    extrema: dict[str, tuple[float, float]] = {}
    if state["status"] == "complete":
        completed_diagnostics = [record.get("diagnostics", {}).get("combined", {})
                                 for record in records
                                 if record.get("status") == "complete"]
        for key in OBJECTIVES:
            values = []
            for item in completed_diagnostics:
                try:
                    values.append(objective_score(item, key))
                except KeyError:
                    pass
            if values:
                extrema[key] = (min(values), max(values))

    def diagnostic_cell(diagnostic: dict[str, Any], key: str) -> str:
        if not diagnostic:
            return "<td data-sort=''>—</td>"
        try:
            value = objective_score(diagnostic, key)
        except KeyError:
            return "<td data-sort=''>—</td>"
        css_class = ""
        if key in extrema:
            minimum, maximum = extrema[key]
            if math.isclose(value, maximum, abs_tol=1e-9):
                css_class = " class='best'"
            elif math.isclose(value, minimum, abs_tol=1e-9):
                css_class = " class='worst'"
        return f"<td{css_class} data-sort='{value:.6f}'>{value:.1f}%</td>"

    traits = candidate_traits(records, seed, search["bounds"])
    rows = []
    for record, fallback_trait in zip(records, traits):
        trait = record.get("experiment_label", fallback_trait)
        diagnostic = record.get("diagnostics", {}).get("combined", {})
        candidate_dir = f"candidates/{record['id']}"
        artifact_stem = record.get("artifact_stem", record["id"])
        stl_link = (f" · <a href='{candidate_dir}/{html.escape(record['stl_file'])}'>STL</a>"
                    if record.get("stl_file") else "")
        report_link = (f" · <a href='{html.escape(record['report_file'])}'>report</a>"
                       if record.get("report_file") else "")
        status = "Pareto" if record.get("pareto") else record["status"].title()
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
        rows.append("<tr>" + "".join((
            f"<td data-sort='{html.escape(artifact_stem)}'><a href='{candidate_dir}/project.yaml'>{html.escape(artifact_stem)}</a>"
            f"{stl_link}{report_link}</td>",
            f"<td data-sort='{html.escape(status)}'>{html.escape(status)}</td>",
            "".join(diagnostic_cell(diagnostic, key) for key in OBJECTIVES),
            f"<td data-sort='{record['values']['length_mm']:.6f}'>{record['values']['length_mm']:.1f}</td>",
            f"<td data-sort='{record['values']['extension_mm']:.6f}'>{record['values']['extension_mm']:.1f}</td>",
            f"<td class='axis-pair' data-sort='{record['values']['osse_coverage_h_deg']:.6f}'>"
            f"{coverage_pair}</td>",
            f"<td class='axis-pair' data-sort='{record['values']['k_h']:.6f}'>"
            f"{k_pair}</td>",
            f"<td class='axis-pair' data-sort='{record['derived'].get('s_h', float('nan')):.6f}'>"
            f"{s_pair}</td>",
            f"<td class='axis-pair' data-sort='{record['values']['n_h']:.6f}'>"
            f"{n_pair}</td>",
            f"<td data-sort='{html.escape(trait)}'>{html.escape(trait)}</td>",
        )) + "</tr>")
    objective_headers = "".join(
        f"<th class='sortable' data-sort='number'>{label}</th>"
        for label in OBJECTIVE_LABELS)
    refresh = "<meta http-equiv='refresh' content='10'>" if state["status"] == "running" else ""
    document = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}
<title>BEM candidate search</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#4db6a8;--accent-strong:#69d6c8}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}
a{{color:var(--accent-strong)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:max-content}}
th,td{{padding:8px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}td.best{{background:#173c39;color:#9af0df;font-weight:700}}td.worst{{background:#482321;color:#ffaaa3;font-weight:700}}.summary{{display:flex;gap:30px;flex-wrap:wrap}}.summary p{{color:var(--muted)}}.summary strong{{color:var(--ink)}}
.axis-pair{{white-space:normal}}.sortable{{cursor:pointer;user-select:none}}
</style></head><body><main><h1>BEM candidate search</h1><section class='summary'>
<p><strong>Status</strong><br>{html.escape(state['status'])}</p><p><strong>Phase</strong><br>{html.escape(state.get('phase', ''))}</p>
<p><strong>Progress</strong><br>{sum(r['status']=='complete' for r in records)}&nbsp;/<wbr> {state['max_evaluations']} evaluated</p>
<p><strong>Rejected proposals</strong><br>{state.get('rejected_count', 0)}</p>
<p><strong>Confidently inferior</strong><br>{state.get('surrogate_screened_count', 0)}</p>
<p><strong>Sweep band</strong><br>{lower_frequency:g}–{upper_frequency:g} Hz</p>
<p><strong>Crossover</strong><br>{crossover_frequency:g} Hz</p>
<p><strong>Diagnostic band</strong><br>{crossover_frequency:g}–{upper_frequency:g} Hz</p></section>
<section><p><strong>Sampling policy:</strong> training uses {search.get('solver', {}).get('points_per_octave', 12):g} PPO. Each completed run is compared with a factor-two decimation and excluded from surrogate training when any headline diagnostic moves by more than {search.get('sampling_stability_points', DEFAULT_SAMPLING_STABILITY_POINTS):g} points. Seed, representative probes, and finalists require {search.get('confirmation_points_per_octave', 20):g}-PPO confirmation before final selection.</p></section>
<section><h2>Candidates</h2><table class='sortable-table'><thead><tr><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-sort='text'>Status</th>{objective_headers}<th class='sortable' data-sort='number'>Length mm</th><th class='sortable' data-sort='number'>Extension mm</th><th class='sortable' data-sort='number'>OS-SE H&nbsp;/ V</th><th class='sortable' data-sort='number'>K H&nbsp;/ V</th><th class='sortable' data-sort='number'>S H&nbsp;/ V</th><th class='sortable' data-sort='number'>N H&nbsp;/ V</th><th class='sortable' data-sort='text'>Distinguishing trait</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><p>100% is best for all acoustic diagnostics. Combined H/V scores are weighted in proportion to mouth width and height. The sweep band controls solved frequencies; the fixed diagnostic band starts at crossover and ends at the upper operating frequency. Proposals closer than normalized distance {state['search'].get('minimum_candidate_distance', DEFAULT_MINIMUM_CANDIDATE_DISTANCE):g} to a retained candidate are rejected without retaining their data. After the initial coupled-geometry round, proposals modeled as worse than the seed on all objectives with probability at least {100 * state['search'].get('inferior_screen_probability', DEFAULT_INFERIOR_PROBABILITY):g}% are also screened without retaining individual data.</p></section>
<script>
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
            memory_limit_gib=solver.get("memory_limit_gib"), resume=True)
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
        run = load_run(run_dir, artifact_stem)
        diagnostics = coverage_diagnostics(run, fixed_grid, fixed_band=True)
        report_path = candidate_dir / "bem" / f"{artifact_stem}_Report.html"
        single_report(run_dir, report_path, title=title,
                      evaluation_frequencies=fixed_grid, fixed_band=True,
                      name=artifact_stem)
        stability = sampling_stability(
            run, fixed_grid, search["crossover_hz"],
            search.get("sampling_stability_points", DEFAULT_SAMPLING_STABILITY_POINTS))
        loading_percent, loading_minimum = crossover_loading(
            run, search["crossover_hz"])
        record.update(
            status="complete", run_dir=str(run_dir.relative_to(output_dir)),
            report_file=str(report_path.relative_to(output_dir)),
            diagnostics=diagnostics,
            sampling_stability=stability,
            crossover_loading_percent=loading_percent,
            crossover_minimum_normalized_impedance=loading_minimum,
            elapsed_s=record.get("elapsed_s", 0) + time.perf_counter() - started,
            mesh_quadrant_panels=manifest["mesh_quadrant_panels"])
    except Exception as error:  # retain failure and continue the search
        record.update(status="failed", reason=f"{type(error).__name__}: {error}",
                      elapsed_s=record.get("elapsed_s", 0) + time.perf_counter() - started)


def run_search(search_path: Path, output_dir: Path, binary: Path | None,
               dry_run: bool = False) -> dict[str, Any]:
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
            "surrogate_screened_count": 0,
            "started_at_unix": time.time(),
        }
        save_state(output_dir, state)
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
    executable = None if dry_run else find_numcalc(binary)
    solver = search.get("solver", {})
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
    while (sum(record["status"] == "complete" for record in state["candidates"])
           < search["max_evaluations"] and state["proposal_count"] < max_proposals):
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
            vector, source = propose_vector(search, state["candidates"], proposal_index)
            values = values_from_vector(vector, search["bounds"])
            if proposal_index == 0:
                values = search["seed_values"]
            # Coupled proposals are evaluated as authored. Silent K repair would
            # change the experiment and corrupt learned parameter effects.
            document, derived = materialize_candidate(seed, values, search)
            feasible, reason = geometry_feasibility(derived)
            distance = candidate_distance(values, state["candidates"], search["bounds"])
            if (not feasible or
                    (source != "initial-curated" and
                     distance < search["minimum_candidate_distance"])):
                state["rejected_count"] += 1
                save_state(output_dir, state)
                continue
            if proposal_index > search["initial_candidates"]:
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
    if dry_run:
        state.update(status="preflight", phase="initial candidates materialized")
    elif complete >= search["max_evaluations"]:
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
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    state = run_search(args.search_yaml, args.output_dir, args.binary, args.dry_run)
    print(f"search report: {args.output_dir / 'search_report.html'}")
    print(f"status: {state['status']}")


if __name__ == "__main__":
    main()
