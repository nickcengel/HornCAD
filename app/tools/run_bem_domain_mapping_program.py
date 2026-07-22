#!/usr/bin/env python3
"""Map remote zero-extension S/K/N geometry in two equal-opportunity batches."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterable

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import brentq
from scipy.stats import qmc
import yaml

from .analyze_bem_design_space import Candidate, load_candidates
from .bem_learning import merged_candidate_policy, nominal_candidate_rejections
from .export_horncad import osse_radius, solved_s, termination_metrics
from .generate_mouth_size_coverage_grid_report import generate_report
from .run_bem_search import (
    MAX_FINAL_TENTH_RADIAL_GROWTH_FRACTION, geometry_feasibility,
    materialize_candidate, run_search,
)
from .run_s_boundary_closure_program import (
    baseline_searches, close_baseline, materialize_probe,
)


INTERIOR_ANGLES = (30, 35, 40, 45, 50)
INTERIOR_MOUTHS = (250, 300, 350, 400, 450)
ANGLES = INTERIOR_ANGLES
MOUTHS = INTERIOR_MOUTHS
RETAINED_EDGE_CELLS: tuple[tuple[int, int], ...] = ()
S_BOUNDS = (0.05, 4.0)
K_BOUNDS = (1.0, 7.0)
N_BOUNDS = (2.0, 20.0)
SCORE_MATERIALITY = 1.0
SLOTS = {
    1: (("low", "low", "low"), ("high", "high", "high")),
    2: (("high", "low", "high"), ("low", "high", "low")),
}
RESPONSE_SURFACE_LEVELS = {
    "length": {-1: 0.85, 0: 1.0, 1: 1.15},
    "k": {-1: 3.0, 0: 4.0, 1: 5.0},
    "n": {-1: 6.0, 0: 10.0, 1: 14.0},
}
# Candidate pool for missing information only. Existing K4/N10 S-grid points
# supply the length axis; do not simulate that axis again.
RESPONSE_SURFACE_COORDINATES = (
    (0, -1, 0), (0, 1, 0),
    (0, 0, -1), (0, 0, 1),
    *((length, k, n) for length in (-1, 1)
      for k in (-1, 1) for n in (-1, 1)),
)
MODEL_CONDITION_LIMIT = 18.0
NEAR_EXISTING_DISTANCE = 0.18
PROFILE_SAMPLE_COUNT = 41


def snap_k_n(k: float, n: float) -> tuple[float, float]:
    """Return the only control grid allowed for newly materialized candidates."""
    return round(float(k) * 2) / 2, float(round(float(n)))


@dataclass(frozen=True)
class Proposal:
    coverage_deg: int
    mouth_mm: int
    batch: int
    slot: int
    s: float
    length_mm: float
    k: float
    n: float
    mouth_length_ratio: float
    exit_angle_deg: float
    normalized_curvature_radius: float
    acquisition: str
    nearest_distance: float
    matched_parameter: str | None = None
    anchor_length_mm: float | None = None
    anchor_k: float | None = None
    anchor_n: float | None = None
    anchor_s: float | None = None
    coordinate_label: str | None = None
    length_level: int | None = None
    k_level: int | None = None
    n_level: int | None = None
    predicted_score: float | None = None
    predicted_sigma: float | None = None
    hypothesis: str | None = None
    contrast_search: str | None = None
    contrast_candidate_id: str | None = None
    enforced_learning_rules: tuple[str, ...] = ()
    learning_round: int | None = None

    @property
    def values(self) -> dict[str, float]:
        return {
            "length_mm": self.length_mm, "extension_mm": 0.0,
            "osse_coverage_h_deg": float(self.coverage_deg),
            "osse_coverage_v_deg": float(self.coverage_deg),
            "k_h": self.k, "k_v": self.k,
            "n_h": self.n, "n_v": self.n,
        }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _baseline(root: Path, angle: int, mouth: int) -> Path:
    path = root / f"{angle}deg" / f"{mouth}x{mouth}-s-grid"
    if not (path / "search.yaml").exists():
        raise FileNotFoundError(path / "search.yaml")
    return path


def _source_search(baseline: Path) -> dict[str, Any]:
    return yaml.safe_load((baseline / "search.yaml").read_text(encoding="utf-8"))[
        "bem_candidate_search"]


def _source_project(baseline: Path) -> dict[str, Any]:
    return yaml.safe_load((baseline / "project.yaml").read_text(encoding="utf-8"))


def _length_for_controls(config: dict[str, Any], coverage: float, target_s: float,
                         k: float, n: float) -> float | None:
    global_config = config["global"]
    radius = float(global_config["mouth_width"]) / 2
    throat_radius = float(global_config["throat_radius"])
    throat_angle = float(global_config["throat_angle_deg"])

    def error(length: float) -> float:
        return solved_s(length, throat_radius, coverage, k, n, radius,
                        throat_angle) - target_s

    lower, upper = 1.0, max(100.0, float(global_config["mouth_width"]) * 5)
    try:
        if error(lower) < 0 or error(upper) > 0:
            return None
        return round(float(brentq(error, lower, upper)), 3)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _candidate_geometry(config: dict[str, Any], coverage: float, s: float,
                        k: float, n: float) -> tuple[float, dict[str, float]] | None:
    length = _length_for_controls(config, coverage, s, k, n)
    if length is None:
        return None
    result = _independent_control_geometry(config, coverage, length, k, n)
    return (length, result) if result is not None else None


def _independent_control_geometry(
        config: dict[str, Any], coverage: float, length: float,
        k: float, n: float) -> dict[str, float] | None:
    """Validate length/K/N controls and return their derived OS-SE geometry."""
    global_config = config["global"]
    try:
        metrics = termination_metrics(
            length, float(global_config["throat_radius"]), coverage, k, n,
            float(global_config["mouth_width"]) / 2,
            float(global_config["throat_angle_deg"]),
        )
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    derived = {
        "s_h": metrics["s"], "s_v": metrics["s"],
        "mouth_exit_angle_h_deg": metrics["exit_angle_deg"],
        "mouth_exit_angle_v_deg": metrics["exit_angle_deg"],
        "mouth_curvature_radius_h_mm": metrics["curvature_radius_mm"],
        "mouth_curvature_radius_v_mm": metrics["curvature_radius_mm"],
        "normalized_mouth_curvature_h": metrics["normalized_curvature_radius"],
        "normalized_mouth_curvature_v": metrics["normalized_curvature_radius"],
        "final_tenth_radial_growth_h": metrics["final_tenth_radial_growth_fraction"],
        "final_tenth_radial_growth_v": metrics["final_tenth_radial_growth_fraction"],
    }
    feasible, _ = geometry_feasibility(derived)
    if not feasible or not S_BOUNDS[0] <= float(metrics["s"]) <= S_BOUNDS[1]:
        return None
    return metrics


def _feature(mouth: float, length: float, s: float, k: float, n: float,
             metrics: dict[str, float]) -> np.ndarray:
    return np.asarray([
        (mouth / length - 0.5) / 5.5,
        (s - S_BOUNDS[0]) / (S_BOUNDS[1] - S_BOUNDS[0]),
        (k - K_BOUNDS[0]) / (K_BOUNDS[1] - K_BOUNDS[0]),
        (n - N_BOUNDS[0]) / (N_BOUNDS[1] - N_BOUNDS[0]),
        metrics["exit_angle_deg"] / 90,
        min(1.0, math.log1p(metrics["normalized_curvature_radius"]) / 8),
    ])


def _candidate_feature(candidate: Candidate, config: dict[str, Any]) -> np.ndarray:
    global_config = config["global"]
    metrics = termination_metrics(
        candidate.length_mm, float(global_config["throat_radius"]),
        candidate.coverage_deg, candidate.k, candidate.n,
        candidate.mouth_mm / 2, float(global_config["throat_angle_deg"]),
    )
    return _feature(candidate.mouth_mm, candidate.length_mm, candidate.s,
                    candidate.k, candidate.n, metrics)


class KernelScoreModel:
    """Small deterministic GP used only to separate mapping from exploitation."""

    def __init__(self, candidates: Iterable[Candidate]):
        items = list(candidates)
        self.x = np.asarray([[
            (item.coverage_deg - 25) / 25,
            (item.mouth_mm - 250) / 250,
            (item.mouth_mm / item.length_mm - 0.5) / 5.5,
            (item.k - 1) / 6,
            (item.n - 2) / 18,
        ] for item in items])
        y = np.asarray([item.score for item in items])
        self.y_mean = float(np.mean(y))
        self.y_scale = max(1.0, float(np.std(y)))
        normalized_y = (y - self.y_mean) / self.y_scale
        delta = self.x[:, None, :] - self.x[None, :, :]
        kernel = np.exp(-np.sum(delta * delta, axis=2) / (2 * 0.24 ** 2))
        kernel.flat[::len(items) + 1] += 2e-4
        self.factor = cho_factor(kernel, lower=True, check_finite=False)
        self.alpha = cho_solve(self.factor, normalized_y, check_finite=False)

    def predict(self, coverage: float, mouth: float,
                rows: list[tuple[float, float, float, float]]) -> tuple[np.ndarray, np.ndarray]:
        query = np.asarray([[
            (coverage - 25) / 25, (mouth - 250) / 250,
            (mouth / length - 0.5) / 5.5, (k - 1) / 6, (n - 2) / 18,
        ] for length, _s, k, n in rows])
        delta = query[:, None, :] - self.x[None, :, :]
        cross = np.exp(-np.sum(delta * delta, axis=2) / (2 * 0.24 ** 2))
        mean = self.y_mean + self.y_scale * (cross @ self.alpha)
        solved = cho_solve(self.factor, cross.T, check_finite=False)
        variance = np.maximum(1e-8, 1 - np.sum(cross * solved.T, axis=1))
        return mean, self.y_scale * np.sqrt(variance)


def _stratum_bounds(side: str, low: tuple[float, float],
                    high: tuple[float, float]) -> tuple[float, float]:
    return low if side == "low" else high


def _pool(config: dict[str, Any], coverage: int, mouth: int,
          incumbent_s: float, stratum: tuple[str, str, str], seed: int,
          size: int = 4096) -> list[tuple[float, float, float, float, dict[str, float], np.ndarray]]:
    s_side, k_side, n_side = stratum
    lower_s = (S_BOUNDS[0], max(S_BOUNDS[0], incumbent_s - 0.15))
    upper_s = (min(S_BOUNDS[1], incumbent_s + 0.15), S_BOUNDS[1])
    s_bounds = _stratum_bounds(s_side, lower_s, upper_s)
    if s_bounds[1] <= s_bounds[0] + 0.05:
        s_bounds = S_BOUNDS
    k_bounds = _stratum_bounds(k_side, (1.0, 3.5), (4.5, 7.0))
    n_bounds = _stratum_bounds(n_side, (2.0, 8.0), (12.0, 20.0))
    samples = qmc.LatinHypercube(d=3, seed=seed).random(size)
    unique: dict[tuple[float, float, float], tuple] = {}
    for unit_s, unit_k, unit_n in samples:
        s = round((s_bounds[0] + unit_s * (s_bounds[1] - s_bounds[0])) * 10) / 10
        s = max(S_BOUNDS[0], min(S_BOUNDS[1], s))
        k = round((k_bounds[0] + unit_k * (k_bounds[1] - k_bounds[0])) * 2) / 2
        n = round(n_bounds[0] + unit_n * (n_bounds[1] - n_bounds[0]))
        key = (s, k, float(n))
        if key in unique:
            continue
        geometry = _candidate_geometry(config, coverage, s, k, float(n))
        if geometry is None:
            continue
        length, metrics = geometry
        unique[key] = (s, k, float(n), length, metrics,
                       _feature(mouth, length, s, k, float(n), metrics))
    return list(unique.values())


def select_proposal(root: Path, coverage: int, mouth: int, batch: int,
                    slot: int, candidates: list[Candidate], selected: list[Proposal],
                    model: KernelScoreModel | None,
                    matched_target: Proposal | None = None) -> Proposal:
    baseline = _baseline(root, coverage, mouth)
    config = _source_project(baseline)["horncad_config"]
    cell = [item for item in candidates
            if item.coverage_deg == coverage and item.mouth_mm == mouth]
    incumbent = max(cell, key=lambda item: item.score)
    stratum = SLOTS[batch][slot]
    pool = _pool(config, coverage, mouth, incumbent.s, stratum,
                 seed=coverage * 10000 + mouth * 10 + batch * 2 + slot)
    if not pool:
        raise RuntimeError(f"no feasible domain-map pool for {coverage}°/{mouth} slot {slot}")
    existing_features = [_candidate_feature(item, config) for item in cell]
    existing_features.extend(_feature(
        mouth, item.length_mm, item.s, item.k, item.n,
        {"exit_angle_deg": item.exit_angle_deg,
         "normalized_curvature_radius": item.normalized_curvature_radius},
    ) for item in selected if item.coverage_deg == coverage and item.mouth_mm == mouth)
    features = np.asarray([item[5] for item in pool])
    reference = np.asarray(existing_features)
    distances = np.min(np.linalg.norm(
        features[:, None, :] - reference[None, :, :], axis=2), axis=1)
    if matched_target is not None:
        match = np.asarray([
            abs(mouth / item[3] - matched_target.mouth_length_ratio) / 2 +
            abs(item[1] - matched_target.k) / 6 +
            abs(item[2] - matched_target.n) / 18 for item in pool])
        acquisition = distances / max(float(np.max(distances)), 1e-9) - 2 * match
        reason = "matched 45°/50° cross-angle contrast"
        means = sigmas = None
    elif batch == 2 and model is not None:
        means, sigmas = model.predict(
            coverage, mouth, [(item[3], item[0], item[1], item[2]) for item in pool])
        normalized_distance = distances / max(float(np.max(distances)), 1e-9)
        normalized_sigma = sigmas / max(float(np.max(sigmas)), 1e-9)
        lower_gain = means - sigmas - incumbent.score
        if float(np.max(lower_gain)) >= SCORE_MATERIALITY:
            acquisition = lower_gain
            reason = "uncertainty-adjusted predicted gain >= 1 point"
        else:
            acquisition = 0.7 * normalized_distance + 0.3 * normalized_sigma
            reason = "70% remote coverage + 30% model uncertainty"
    else:
        means = sigmas = None
        acquisition = distances
        reason = "remote maximin coverage"
    index = int(np.argmax(acquisition))
    s, k, n, length, metrics, _ = pool[index]
    return Proposal(
        coverage_deg=coverage, mouth_mm=mouth, batch=batch, slot=slot,
        s=s, length_mm=length, k=k, n=n,
        mouth_length_ratio=mouth / length,
        exit_angle_deg=float(metrics["exit_angle_deg"]),
        normalized_curvature_radius=float(metrics["normalized_curvature_radius"]),
        acquisition=reason, nearest_distance=float(distances[index]),
        predicted_score=(float(means[index]) if means is not None else None),
        predicted_sigma=(float(sigmas[index]) if sigmas is not None else None),
    )


def _response_surface_anchor(candidates: list[Candidate], coverage: int,
                             mouth: int) -> Candidate:
    anchors = [item for item in candidates
               if item.coverage_deg == coverage and item.mouth_mm == mouth
               and abs(item.k - 4.0) <= 0.01 and abs(item.n - 10.0) <= 0.01]
    if not anchors:
        raise RuntimeError(f"no K4/N10 response-surface anchor for {coverage}°/{mouth}")
    return max(anchors, key=lambda item: item.score)


def _quadratic_feature(length: float, k: float, n: float,
                       anchor_length: float) -> np.ndarray:
    length_unit = (length / anchor_length - 1.0) / 0.15
    k_unit = k - 4.0
    n_unit = (n - 10.0) / 4.0
    return np.asarray([
        1.0, length_unit, k_unit, n_unit,
        length_unit ** 2, k_unit ** 2, n_unit ** 2,
        length_unit * k_unit, length_unit * n_unit, k_unit * n_unit,
    ])


def _normalized_profile(
        config: dict[str, Any], coverage: float, length: float,
        k: float, n: float) -> np.ndarray:
    """Return the dimensionless radial surface used to judge physical novelty."""
    global_config = config["global"]
    mouth_radius = float(global_config["mouth_width"]) / 2
    throat_radius = float(global_config["throat_radius"])
    throat_angle = float(global_config["throat_angle_deg"])
    metrics = termination_metrics(
        length, throat_radius, coverage, k, n, mouth_radius, throat_angle)
    stations = np.linspace(0.0, 1.0, PROFILE_SAMPLE_COUNT)
    return np.asarray([
        osse_radius(float(station * length), length, throat_radius, coverage,
                    k, n, float(metrics["s"]), throat_angle) / mouth_radius
        for station in stations
    ])


def _physical_distance(
        length: float, profile: np.ndarray, other_length: float,
        other_profile: np.ndarray, anchor_length: float,
        length_materiality: float, profile_materiality: float) -> tuple[float, float]:
    """Distance in physically observable geometry, not nominal K/N coordinates."""
    profile_rms = float(np.sqrt(np.mean((profile - other_profile) ** 2)))
    distance = math.hypot(
        (length - other_length) / (length_materiality * anchor_length),
        profile_rms / profile_materiality,
    )
    return distance, profile_rms


def _physical_quadratic_features(
        lengths: np.ndarray, profiles: np.ndarray, anchor_length: float,
        basis: np.ndarray | None = None,
        center: np.ndarray | None = None,
        score_scale: np.ndarray | None = None,
        ) -> tuple[np.ndarray, dict[str, Any]]:
    """Represent length plus two dominant radial-profile modes quadratically.

    Unlike raw K/N features, a parameter change that leaves the surface unchanged
    cannot create rank or improve the experimental design.
    """
    if center is None:
        center = np.mean(profiles, axis=0)
    centered = profiles - center
    if basis is None:
        singular, _, right = np.linalg.svd(centered, full_matrices=False)
        del singular
        basis = right[:2]
    scores = centered @ basis.T
    if score_scale is None:
        score_scale = np.maximum(np.std(scores, axis=0), 1e-6)
    scores = scores / score_scale
    length_unit = (lengths / anchor_length - 1.0) / 0.15
    x, y = scores[:, 0], scores[:, 1]
    matrix = np.column_stack([
        np.ones(len(lengths)), length_unit, x, y,
        length_unit ** 2, x ** 2, y ** 2,
        length_unit * x, length_unit * y, x * y,
    ])
    variance = np.var(centered, axis=0).sum()
    reconstructed = scores * score_scale @ basis
    captured = 1.0 - float(np.sum((centered - reconstructed) ** 2)) / max(
        float(np.sum(centered ** 2)), 1e-12)
    return matrix, {
        "center": center, "basis": basis, "score_scale": score_scale,
        "profile_variance_captured": captured if variance > 0 else 1.0,
    }


def _model_stats(matrix: np.ndarray) -> tuple[int, float]:
    if not len(matrix):
        return 0, math.inf
    singular = np.linalg.svd(matrix, compute_uv=False)
    rank = int(np.linalg.matrix_rank(matrix, tol=1e-7))
    condition = (float(singular[0] / singular[-1])
                 if rank == 10 and singular[-1] > 1e-9 else math.inf)
    return rank, condition


def _existing_symmetric_points(root: Path, coverage: int, mouth: int,
                               anchor_length: float,
                               config: dict[str, Any] | None = None
                               ) -> list[dict[str, Any]]:
    """Load reusable zero-extension evidence without averaging asymmetric runs."""
    points: list[dict[str, Any]] = []
    pattern = f"{coverage}deg/{mouth}x{mouth}*/search_state.json"
    for state_path in sorted(root.glob(pattern)):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            continue
        for record in state.get("candidates", []):
            if record.get("status") != "complete":
                continue
            values = record.get("values", {})
            try:
                if abs(float(values.get("extension_mm", 0.0))) > 0.01:
                    continue
                if abs(float(values["osse_coverage_h_deg"]) -
                       float(values["osse_coverage_v_deg"])) > 0.01:
                    continue
                if (abs(float(values["k_h"]) - float(values["k_v"])) > 0.01 or
                        abs(float(values["n_h"]) - float(values["n_v"])) > 0.01):
                    continue
                length = float(values["length_mm"])
                k = (float(values["k_h"]) + float(values["k_v"])) / 2
                n = (float(values["n_h"]) + float(values["n_v"])) / 2
            except (KeyError, TypeError, ValueError):
                continue
            if not (0.65 <= length / anchor_length <= 1.35 and
                    2.0 <= k <= 6.0 and 4.0 <= n <= 16.0):
                continue
            points.append({
                "length_mm": length, "k": k, "n": n,
                "search": str(state_path.relative_to(root)),
                "candidate_id": record.get("id"),
                **({"profile": _normalized_profile(
                    config, coverage, length, k, n)} if config is not None else {}),
            })
    # Dense local optimizer traces must not masquerade as independent volume.
    unique: dict[tuple[float, float, float], dict[str, Any]] = {}
    for point in points:
        key = (
            round((point["length_mm"] / anchor_length - 1.0) / 0.15, 2),
            round(point["k"] - 4.0, 2),
            round((point["n"] - 10.0) / 4.0, 2),
        )
        unique.setdefault(key, point)
    return list(unique.values())


def response_surface_design(
        root: Path, candidates: list[Candidate]
        ) -> tuple[list[dict[str, Any]], list[Proposal]]:
    """Add only physically distinct points needed to identify surface behavior."""
    policy = merged_candidate_policy()
    profile_materiality = float(
        policy["normalized_profile_rms_materiality_fraction"])
    length_materiality = float(
        policy["normalized_length_materiality_fraction"])
    coordinates: list[dict[str, Any]] = []
    proposals: list[Proposal] = []
    for coverage in INTERIOR_ANGLES:
        for mouth in INTERIOR_MOUTHS:
            baseline = _baseline(root, coverage, mouth)
            config = _source_project(baseline)["horncad_config"]
            anchor = _response_surface_anchor(candidates, coverage, mouth)
            existing = _existing_symmetric_points(
                root, coverage, mouth, anchor.length_mm, config)
            feasible_pool: list[tuple[dict[str, Any], Proposal, np.ndarray]] = []
            for slot, (length_level, k_level, n_level) in enumerate(
                    RESPONSE_SURFACE_COORDINATES):
                length = round(anchor.length_mm *
                               RESPONSE_SURFACE_LEVELS["length"][length_level], 3)
                k = RESPONSE_SURFACE_LEVELS["k"][k_level]
                n = RESPONSE_SURFACE_LEVELS["n"][n_level]
                label = f"L{length_level:+d}_K{k_level:+d}_N{n_level:+d}"
                coordinate: dict[str, Any] = {
                    "coverage_deg": coverage, "mouth_mm": mouth,
                    "batch": 2, "slot": slot, "coordinate_label": label,
                    "length_level": length_level, "k_level": k_level,
                    "n_level": n_level, "length_mm": length, "k": k, "n": n,
                    "anchor_length_mm": anchor.length_mm,
                    "anchor_k": anchor.k, "anchor_n": anchor.n,
                    "anchor_s": anchor.s,
                }
                rejected_by = nominal_candidate_rejections(
                    coverage, mouth, k, n)
                if rejected_by:
                    coordinate.update(status="rejected-by-learning",
                                      rejected_by_rules=rejected_by)
                    coordinates.append(coordinate)
                    continue
                metrics = _independent_control_geometry(
                    config, coverage, length, k, n)
                if metrics is None:
                    coordinate.update(
                        status="geometry-rejected",
                        reason="prescribed response-surface coordinate is infeasible")
                    coordinates.append(coordinate)
                    continue
                coordinate["s"] = float(metrics["s"])
                profile = _normalized_profile(config, coverage, length, k, n)
                physical = [_physical_distance(
                    length, profile, item["length_mm"], item["profile"],
                    anchor.length_mm, length_materiality, profile_materiality)
                    for item in existing]
                nearest_index = (int(np.argmin([item[0] for item in physical]))
                                 if physical else None)
                nearest_distance = (physical[nearest_index][0]
                                    if nearest_index is not None else math.inf)
                nearest_profile_rms = (physical[nearest_index][1]
                                       if nearest_index is not None else math.inf)
                coordinate["nearest_existing_distance"] = nearest_distance
                coordinate["nearest_existing_profile_rms_fraction"] = nearest_profile_rms
                if nearest_distance < 1.0:
                    reused = existing[nearest_index]
                    coordinate.update(
                        status="rejected-geometrically-redundant",
                        rejected_by_rules=["physical-profile-materiality-v1"],
                        reused_search=reused["search"],
                        reused_candidate_id=reused["candidate_id"])
                    coordinates.append(coordinate)
                    continue
                coordinate["status"] = "available-for-augmentation"
                coordinates.append(coordinate)
                proposal = Proposal(
                    coverage_deg=coverage, mouth_mm=mouth, batch=2, slot=slot,
                    s=float(metrics["s"]), length_mm=length, k=k, n=n,
                    mouth_length_ratio=mouth / length,
                    exit_angle_deg=float(metrics["exit_angle_deg"]),
                    normalized_curvature_radius=float(
                        metrics["normalized_curvature_radius"]),
                    acquisition="D-optimal quadratic information augmentation",
                    nearest_distance=nearest_distance,
                    matched_parameter="quadratic-augmentation",
                    anchor_length_mm=anchor.length_mm, anchor_k=anchor.k,
                    anchor_n=anchor.n, anchor_s=anchor.s,
                    coordinate_label=label, length_level=length_level,
                    k_level=k_level, n_level=n_level,
                )
                feasible_pool.append((coordinate, proposal, profile))
            all_lengths = np.asarray([
                *[item["length_mm"] for item in existing],
                *[item[1].length_mm for item in feasible_pool],
            ])
            all_profiles = np.asarray([
                *[item["profile"] for item in existing],
                *[item[2] for item in feasible_pool],
            ])
            all_matrix, physical_model = _physical_quadratic_features(
                all_lengths, all_profiles, anchor.length_mm)
            existing_count = len(existing)
            matrix = all_matrix[:existing_count]
            pool_features = all_matrix[existing_count:]
            initial_rank, initial_condition = _model_stats(matrix)
            for coordinate, _, _ in feasible_pool:
                coordinate.update(
                    existing_model_rank=initial_rank,
                    existing_model_condition=(
                        initial_condition if math.isfinite(initial_condition) else None),
                    profile_variance_captured=(
                        physical_model["profile_variance_captured"]),
                    selection_space="normalized-length-plus-profile-pca")
            feasible_pool = [
                (coordinate, proposal, feature)
                for (coordinate, proposal, _), feature
                in zip(feasible_pool, pool_features)
            ]
            selected: list[tuple[dict[str, Any], Proposal, np.ndarray]] = []
            available = feasible_pool[:]
            while available:
                rank, condition = _model_stats(matrix)
                if rank == 10 and condition <= MODEL_CONDITION_LIMIT:
                    break
                best_index = 0
                best_key: tuple[float, float, float] | None = None
                for index, (_, _, feature) in enumerate(available):
                    augmented = np.vstack([matrix, feature])
                    candidate_rank, candidate_condition = _model_stats(augmented)
                    _, log_determinant = np.linalg.slogdet(
                        augmented.T @ augmented + 1e-6 * np.eye(10))
                    key = (float(candidate_rank),
                           -min(candidate_condition, 1e98), float(log_determinant))
                    if best_key is None or key > best_key:
                        best_key, best_index = key, index
                chosen = available.pop(best_index)
                selected.append(chosen)
                matrix = np.vstack([matrix, chosen[2]])
            final_rank, final_condition = _model_stats(matrix)
            for coordinate, proposal, _ in selected:
                coordinate.update(
                    status="selected", final_model_rank=final_rank,
                    final_model_condition=(final_condition if math.isfinite(
                        final_condition) else None),
                    proposal=asdict(proposal))
                proposals.append(proposal)
            for coordinate, _, _ in available:
                coordinate.update(
                    status="not-selected-sufficient-information",
                    final_model_rank=final_rank,
                    final_model_condition=(final_condition if math.isfinite(
                        final_condition) else None))
    return coordinates, proposals


def select_batch(root: Path, batch: int) -> list[Proposal]:
    candidates, _ = load_candidates(root)
    if batch == 2:
        _, proposals = response_surface_design(root, candidates)
        return sorted(proposals, key=lambda item: (
            item.coverage_deg, item.mouth_mm, item.slot))
    model = None
    output: list[Proposal] = []
    cells = [(angle, mouth) for angle in INTERIOR_ANGLES
             for mouth in INTERIOR_MOUTHS]
    if batch == 1:
        cells = [*RETAINED_EDGE_CELLS, *cells]
    for angle in sorted(set(angle for angle, _ in cells)):
        if angle == 50:
            continue
        for mouth in sorted(mouth for candidate_angle, mouth in cells
                            if candidate_angle == angle):
            for slot in range(2):
                output.append(select_proposal(
                    root, angle, mouth, batch, slot, candidates, output, model))
    for mouth in sorted(mouth for angle, mouth in cells if angle == 50):
        for slot in range(2):
            matched = next((item for item in output if (
                batch == 1 and slot == 0 and item.coverage_deg == 45 and
                item.mouth_mm == mouth)), None)
            output.append(select_proposal(
                root, 50, mouth, batch, slot, candidates, output, model,
                matched_target=matched))
    return sorted(output, key=lambda item: (
        item.coverage_deg, item.mouth_mm, item.slot))


def _search_dir(root: Path, proposal: Proposal) -> Path:
    suffix = (f"{proposal.mouth_mm}x{proposal.mouth_mm}-learning-r{proposal.learning_round:02d}"
              if proposal.learning_round is not None else
              f"{proposal.mouth_mm}x{proposal.mouth_mm}-profile-id-b03"
              if proposal.batch == 2 else
              f"{proposal.mouth_mm}x{proposal.mouth_mm}-domain-map-b01")
    return (root / f"{proposal.coverage_deg}deg" /
            suffix)


def materialize_cell_search(root: Path, proposals: list[Proposal],
                            solver_workers: int = 10) -> Path:
    if not proposals:
        raise ValueError("a domain-map cell search requires at least one proposal")
    first = proposals[0]
    if any((item.coverage_deg, item.mouth_mm, item.batch) != (
            first.coverage_deg, first.mouth_mm, first.batch)
            for item in proposals):
        raise ValueError("domain-map proposals must belong to one cell and batch")
    baseline = _baseline(root, first.coverage_deg, first.mouth_mm)
    output = _search_dir(root, first)
    if (output / "search.yaml").exists():
        existing = yaml.safe_load((output / "search.yaml").read_text(
            encoding="utf-8"))["bem_candidate_search"]
        expected_design = ("held-cell-error-controlled-physical-contrasts"
                           if first.learning_round is not None else
                           "physical-profile-quadratic-augmentation" if first.batch == 2
                           else "remote-maximin")
        if (existing.get("domain_mapping", {}).get("design") == expected_design
                and (first.batch != 2 or existing.get("fixed_design") is True)):
            return output
        if (output / "search_state.json").exists():
            raise RuntimeError(
                f"refusing to replace started stale search {output}")
    seed = _source_project(baseline)
    source = _source_search(baseline)
    fake_search = {
        "intended_coverage_h_deg": first.coverage_deg,
        "intended_coverage_v_deg": first.coverage_deg,
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
    }
    seed, derived = materialize_candidate(seed, first.values, fake_search)
    feasible, reason = geometry_feasibility(derived)
    if not feasible:
        raise ValueError(reason)
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    values = [item.values for item in proposals]
    bounds = {}
    for name in values[0]:
        lower = min(item[name] for item in values)
        upper = max(item[name] for item in values)
        if upper - lower < 1e-6:
            upper = lower + 1e-6
        bounds[name] = [lower - 1e-6, upper + 1e-6]
    solver = copy.deepcopy(source["solver"])
    solver["workers"] = solver_workers
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": first.coverage_deg,
        "intended_coverage_v_deg": first.coverage_deg,
        "lower_frequency_hz": fake_search["lower_frequency_hz"],
        "crossover_hz": fake_search["crossover_hz"],
        "upper_frequency_hz": fake_search["upper_frequency_hz"],
        "max_evaluations": len(proposals),
        "initial_candidates": max(0, len(proposals) - 1),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [S_BOUNDS[0] - 0.001, S_BOUNDS[1] + 0.001],
        "sampling_stability_points": float(source.get("sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source.get(
            "confirmation_points_per_octave", 16)),
        "adaptive_pruning": {"enabled": False},
        "fixed_design": True, "bounds": bounds,
        "initial_pool": [{
            "label": (f"system identification · {item.coordinate_label or item.slot} · "
                      f"{item.acquisition}"),
            "values": item.values,
        } for item in proposals[1:]],
        "domain_mapping": {
            "batch": first.batch,
            "design": ("held-cell-error-controlled-physical-contrasts"
                       if first.learning_round is not None else
                       "physical-profile-quadratic-augmentation" if first.batch == 2
                       else "remote-maximin"),
            "proposals": [asdict(item) for item in proposals],
            "score_materiality_points": SCORE_MATERIALITY,
        },
        "solver": solver,
    }
    (output / "search.yaml").write_text(yaml.safe_dump(
        {"bem_candidate_search": search}, sort_keys=False), encoding="utf-8")
    return output


def materialize_batch(root: Path, batch: int,
                      solver_workers: int = 10) -> tuple[list[Path], list[Proposal]]:
    coordinates: list[dict[str, Any]] | None = None
    if batch == 2:
        manifest_path = root / "batch_2_physical_response_surface.json"
        frozen_manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                frozen_manifest = json.loads(manifest_path.read_text(
                    encoding="utf-8"))
            except json.JSONDecodeError:
                frozen_manifest = {}
        frozen_coordinates = frozen_manifest.get("coordinates", [])
        can_resume_frozen = (
            frozen_manifest.get("schema_version") == 3 and
            frozen_manifest.get("design") ==
            "physical-profile-quadratic-augmentation" and
            all("proposal" in item for item in frozen_coordinates
                if item.get("status") == "selected")
        )
        if can_resume_frozen:
            coordinates = frozen_coordinates
            proposals = [Proposal(**item["proposal"]) for item in coordinates
                         if item.get("status") == "selected"]
            summary = frozen_manifest
        else:
            candidates, _ = load_candidates(root)
            coordinates, proposals = response_surface_design(root, candidates)
            summary = {}
        cell_stats = []
        for coverage in INTERIOR_ANGLES:
            for mouth in INTERIOR_MOUTHS:
                cell = [item for item in coordinates
                        if item["coverage_deg"] == coverage
                        and item["mouth_mm"] == mouth]
                audited = next((item for item in cell
                                if "existing_model_rank" in item), {})
                cell_stats.append({
                    "coverage_deg": coverage, "mouth_mm": mouth,
                    "candidate_pool": len(cell),
                    "selected_simulations": sum(
                        item["status"] == "selected" for item in cell),
                    "existing_model_rank": audited.get("existing_model_rank", 0),
                    "existing_model_condition": audited.get(
                        "existing_model_condition"),
                    "final_model_rank": next((item.get("final_model_rank")
                                               for item in cell
                                               if "final_model_rank" in item),
                                              audited.get("existing_model_rank", 0)),
                    "final_model_condition": next((
                        item.get("final_model_condition") for item in cell
                        if "final_model_condition" in item),
                        audited.get("existing_model_condition")),
                    "profile_variance_captured": audited.get(
                        "profile_variance_captured"),
                })
        generated_summary = {
            "schema_version": 3,
            "design": "physical-profile-quadratic-augmentation",
            "independent_factors": [
                "normalized_length", "radial_profile_pc1", "radial_profile_pc2"],
            "levels": RESPONSE_SURFACE_LEVELS,
            "candidate_coordinates_per_cell": len(RESPONSE_SURFACE_COORDINATES),
            "cells": len(INTERIOR_ANGLES) * len(INTERIOR_MOUTHS),
            "total_candidate_coordinates": len(coordinates),
            "planned_simulations": sum(
                item["status"] == "selected" for item in coordinates),
            "covered_by_existing": sum(
                item["status"] == "rejected-geometrically-redundant"
                for item in coordinates),
            "rejected_by_learning": sum(
                item["status"] == "rejected-by-learning" for item in coordinates),
            "not_selected_sufficient_information": sum(
                item["status"] == "not-selected-sufficient-information"
                for item in coordinates),
            "geometry_rejections": sum(
                item["status"] == "geometry-rejected" for item in coordinates),
            "normalized_profile_rms_materiality_fraction": float(
                merged_candidate_policy()[
                    "normalized_profile_rms_materiality_fraction"]),
            "normalized_length_materiality_fraction": float(
                merged_candidate_policy()[
                    "normalized_length_materiality_fraction"]),
            "model_condition_limit": MODEL_CONDITION_LIMIT,
            "cell_stats": cell_stats,
            "coordinates": coordinates,
        }
        if not can_resume_frozen:
            summary = generated_summary
            _write_json(manifest_path, summary)
    else:
        proposals = select_batch(root, batch)
    grouped: dict[tuple[int, int], list[Proposal]] = {}
    for item in proposals:
        grouped.setdefault((item.coverage_deg, item.mouth_mm), []).append(item)
    paths = [materialize_cell_search(root, group, solver_workers)
             for _, group in sorted(grouped.items())]
    return paths, proposals


def _search_status(path: Path) -> str:
    try:
        return str(json.loads((path / "search_state.json").read_text())["status"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return "not-started"


def _active_baseline_searches(root: Path) -> list[Path]:
    """Return only baselines inside the active Phase 4 design envelope."""
    return [
        path for path in baseline_searches(root)
        if int(path.parent.name.removesuffix("deg")) in INTERIOR_ANGLES
        and int(path.name.split("x", 1)[0]) in INTERIOR_MOUTHS
    ]


def repair_s_closure(root: Path, slots: int = 2) -> dict[str, Any]:
    """Rebuild the certificate with geometry limits applied per direction."""
    baselines = _active_baseline_searches(root)
    with ThreadPoolExecutor(max_workers=slots) as executor:
        results = list(executor.map(lambda path: close_baseline(root, path), baselines))
    results.sort(key=lambda item: item["baseline"])
    acceptable = {"closed", "geometry-limited", "boundary-limited"}
    certificate = {
        "status": ("complete" if all(item["status"] in acceptable
                                      for item in results) else "blocked"),
        "results": results,
    }
    _write_json(root / "s_boundary_closure.json", certificate)
    return certificate


def _coupled_length_points(root: Path, coverage: int,
                           mouth: int) -> list[tuple[float, float, Path]]:
    points = []
    angle = root / f"{coverage}deg"
    patterns = (
        f"{mouth}x{mouth}-coupled-r*-s/search_state.json",
        f"{mouth}x{mouth}-coupled-length-closure-r*/search_state.json",
    )
    for pattern in patterns:
        for state_path in sorted(angle.glob(pattern)):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for record in state.get("candidates", []):
                score = record.get("surface_diagnostics", {}).get(
                    "score", {}).get("overall_percent")
                if record.get("status") != "complete" or score is None:
                    continue
                points.append((
                    float(record["derived"]["s_h"]), float(score),
                    state_path.parent / "candidates" / record["id"] / "project.yaml",
                ))
    return points


def close_coupled_length(root: Path, coverage: int = 50, mouth: int = 400,
                         maximum_probes: int = 3) -> dict[str, Any]:
    """Continue a practical-stop local-S winner with expanding coarse jumps."""
    baseline = _baseline(root, coverage, mouth)
    for probe in range(1, maximum_probes + 1):
        points = _coupled_length_points(root, coverage, mouth)
        best = max(points, key=lambda item: item[1])
        has_lower = any(item[0] < best[0] - 1e-3 for item in points)
        has_upper = any(item[0] > best[0] + 1e-3 for item in points)
        if has_lower and has_upper:
            result = {
                "status": "closed", "coverage_deg": coverage, "mouth_mm": mouth,
                "best_s": best[0], "best_score": best[1], "probes": probe - 1,
            }
            _write_json(root / "coupled_length_closure.json", result)
            return result
        side = "lower" if not has_lower else "upper"
        delta = 0.3 * 2 ** (probe - 1)
        target = max(S_BOUNDS[0], best[0] - delta) if side == "lower" else min(
            S_BOUNDS[1], best[0] + delta)
        output = (root / f"{coverage}deg" /
                  f"{mouth}x{mouth}-coupled-length-closure-r{probe:02d}")
        materialize_probe(best[2], baseline, output, target)
        project = yaml.safe_load((output / "project.yaml").read_text(
            encoding="utf-8"))
        if not (output / "search_state.json").exists():
            config = project["horncad_config"]
            horizontal = config["horizontal_basis"]
            snapped_k, snapped_n = snap_k_n(horizontal["k"], horizontal["n"])
            length = _length_for_controls(
                config, coverage, target, snapped_k, snapped_n)
            if length is None:
                raise ValueError(
                    f"could not derive snapped-grid length for S={target:g}")
            values = {
                "length_mm": length, "extension_mm": 0.0,
                "osse_coverage_h_deg": float(coverage),
                "osse_coverage_v_deg": float(coverage),
                "k_h": snapped_k, "k_v": snapped_k,
                "n_h": snapped_n, "n_v": snapped_n,
            }
            source = _source_search(baseline)
            project, _ = materialize_candidate(project, values, {
                "intended_coverage_h_deg": coverage,
                "intended_coverage_v_deg": coverage,
                "lower_frequency_hz": float(source["lower_frequency_hz"]),
                "crossover_hz": float(source["crossover_hz"]),
                "upper_frequency_hz": float(source["upper_frequency_hz"]),
            })
            (output / "project.yaml").write_text(
                yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
        document = yaml.safe_load((output / "search.yaml").read_text(encoding="utf-8"))
        snapped_values = {
            "length_mm": float(project["horncad_config"]["global"]["length"]),
            "extension_mm": 0.0,
            "osse_coverage_h_deg": float(coverage),
            "osse_coverage_v_deg": float(coverage),
            "k_h": float(project["horncad_config"]["horizontal_basis"]["k"]),
            "k_v": float(project["horncad_config"]["vertical_basis"]["k"]),
            "n_h": float(project["horncad_config"]["horizontal_basis"]["n"]),
            "n_v": float(project["horncad_config"]["vertical_basis"]["n"]),
        }
        if not (output / "search_state.json").exists():
            document["bem_candidate_search"]["bounds"] = {
                name: [value - 0.001, value + 0.001]
                for name, value in snapped_values.items()
            }
        document["bem_candidate_search"]["solver"]["workers"] = 20
        document["bem_candidate_search"]["coupled_length_closure"] = {
            "side": side, "target_s": target, "expanding_step": delta,
        }
        if not (output / "search_state.json").exists():
            (output / "search.yaml").write_text(
                yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        state = run_search(output / "search.yaml", output, None)
        generate_report(root, root / "index.html")
        if state.get("status") == "geometry-rejected":
            result = {
                "status": "geometry-limited", "side": side,
                "coverage_deg": coverage, "mouth_mm": mouth,
                "best_s": best[0], "best_score": best[1], "probes": probe,
                "reason": state.get("geometry_rejection", {}).get("reason"),
            }
            _write_json(root / "coupled_length_closure.json", result)
            return result
    points = _coupled_length_points(root, coverage, mouth)
    best = max(points, key=lambda item: item[1])
    result = {
        "status": "unresolved", "coverage_deg": coverage, "mouth_mm": mouth,
        "best_s": best[0], "best_score": best[1], "probes": maximum_probes,
    }
    _write_json(root / "coupled_length_closure.json", result)
    return result


def _run_paths(root: Path, paths: list[Path], slots: int,
               state: dict[str, Any], state_path: Path) -> None:
    pending = [path for path in paths if _search_status(path) != "complete"]
    futures: dict[Any, Path] = {}
    with ThreadPoolExecutor(max_workers=slots) as executor:
        while pending or futures:
            while pending and len(futures) < slots:
                path = pending.pop(0)
                futures[executor.submit(
                    run_search, path / "search.yaml", path, None)] = path
            done, _ = wait(futures, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                path = futures.pop(future)
                future.result()
                state["completed_searches"] = int(state.get("completed_searches", 0)) + 1
                state["last_completed"] = str(path.relative_to(root))
                _write_json(state_path, state)
                generate_report(root, root / "index.html")


def planned_slots() -> list[dict[str, Any]]:
    output = [{
        "coverage_deg": angle, "mouth_mm": mouth, "batch": 1, "slot": slot,
        "status": "planned", "design": "remote-maximin",
    } for angle in INTERIOR_ANGLES for mouth in INTERIOR_MOUTHS
      for slot in range(2)]
    output.extend({
        "coverage_deg": angle, "mouth_mm": mouth, "batch": 2, "slot": slot,
        "status": "awaiting information audit",
        "design": "physical-profile-quadratic-augmentation",
        "coordinate_label": f"L{length:+d}_K{k:+d}_N{n:+d}",
        "length_level": length, "k_level": k, "n_level": n,
    } for angle in INTERIOR_ANGLES for mouth in INTERIOR_MOUTHS
      for slot, (length, k, n) in enumerate(RESPONSE_SURFACE_COORDINATES))
    return output


def _merge_existing_batch_one_slots(
        slots: list[dict[str, Any]], previous: dict[str, Any]) -> None:
    previous_slots = {(item.get("coverage_deg"), item.get("mouth_mm"),
                       item.get("batch"), item.get("slot")): item
                      for item in previous.get("planned_slots", [])}
    for item in slots:
        key = (item["coverage_deg"], item["mouth_mm"], item["batch"], item["slot"])
        if item["batch"] == 1 and key in previous_slots:
            item.update(previous_slots[key])


def _apply_response_surface_manifest(
        state: dict[str, Any], root: Path, proposals: list[Proposal]) -> None:
    manifest = json.loads((root / "batch_2_physical_response_surface.json").read_text(
        encoding="utf-8"))
    records = {(item["coverage_deg"], item["mouth_mm"], item["slot"]): item
               for item in manifest["coordinates"]}
    proposal_records = {(item.coverage_deg, item.mouth_mm, item.slot): item
                        for item in proposals}
    for planned in state["planned_slots"]:
        if planned["batch"] != 2:
            continue
        key = (planned["coverage_deg"], planned["mouth_mm"], planned["slot"])
        planned.update(records[key])
        if key in proposal_records:
            planned.update(asdict(proposal_records[key]), status="materialized")
    state["batch_2_design_summary"] = {
        key: manifest[key] for key in (
            "design", "independent_factors", "levels",
            "candidate_coordinates_per_cell", "cells",
            "total_candidate_coordinates", "planned_simulations",
            "covered_by_existing", "not_selected_sufficient_information",
            "rejected_by_learning", "geometry_rejections",
            "normalized_profile_rms_materiality_fraction",
            "normalized_length_materiality_fraction",
            "model_condition_limit")
    }


def retire_superseded_batch_two(root: Path) -> None:
    """Keep completed evidence but hide the aborted duplicate-heavy searches."""
    state_paths = [
        *root.glob("*deg/*-domain-map-b02/search_state.json"),
        *root.glob("*deg/*-system-id-b02/search_state.json"),
    ]
    for state_path in state_paths:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        state.update(
            status="superseded",
            phase="superseded after existing-data redundancy audit",
            superseded_by="physical-profile-quadratic-augmentation",
            superseded_at_unix=time.time(),
        )
        for candidate in state.get("candidates", []):
            if candidate.get("status") in {"running", "queued"}:
                candidate["status"] = "abandoned-physically-unaudited-design"
        _write_json(state_path, state)


def run_program(root: Path, slots: int = 2, solver_workers: int = 10,
                start_batch: int = 1) -> dict[str, Any]:
    raise RuntimeError(
        "superseded study: use app.tools.run_bem_learning_program; "
        "raw parameter-space domain mapping is intentionally disabled")
    # Retained below only to preserve the historical state-transition implementation
    # while completed artifacts remain readable.
    if start_batch not in (1, 2):
        raise ValueError("start_batch must be 1 or 2")
    state_path = root / "domain_mapping_state.json"
    previous: dict[str, Any] = {}
    if start_batch == 2 and state_path.exists():
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        retire_superseded_batch_two(root)
    slots_plan = planned_slots()
    _merge_existing_batch_one_slots(slots_plan, previous)
    state = {
        "schema_version": 3, "status": "running",
        "phase": ("domain-map-batch-1" if start_batch == 1
                  else "system-identification-batch-2"),
        "total_coordinates": len(slots_plan),
        "total_candidates": len(slots_plan),
        "completed_searches": int(previous.get("completed_searches", 0)),
        "score_materiality_points": SCORE_MATERIALITY,
        "started_at_unix": previous.get("started_at_unix", time.time()),
        "resumed_at_unix": time.time() if start_batch == 2 else None,
        "planned_slots": slots_plan,
    }
    if previous.get("batch_1_proposals"):
        state["batch_1_proposals"] = previous["batch_1_proposals"]
    for key in ("batch_1_status", "batch_1_decision"):
        if key in previous:
            state[key] = previous[key]
    _write_json(state_path, state)
    for batch in range(start_batch, 3):
        state["phase"] = ("domain-map-batch-1" if batch == 1
                          else "system-identification-batch-2")
        paths, proposals = materialize_batch(root, batch, solver_workers)
        state[f"batch_{batch}_proposals"] = [asdict(item) for item in proposals]
        if batch == 2:
            _apply_response_surface_manifest(state, root, proposals)
        else:
            for planned, proposal in zip(
                    [item for item in state["planned_slots"]
                     if item["batch"] == batch], proposals):
                planned.update(asdict(proposal), status="materialized")
        _write_json(state_path, state)
        generate_report(root, root / "index.html")
        _run_paths(root, paths, slots, state, state_path)
    state.update(status="complete", phase="system-identification-complete",
                 completed_at_unix=time.time())
    _write_json(state_path, state)
    generate_report(root, root / "index.html")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--slots", type=int, default=2)
    parser.add_argument("--solver-workers", type=int, default=10)
    parser.add_argument("--materialize-only", action="store_true")
    parser.add_argument("--batch", type=int, choices=(1, 2), default=1,
                        help="batch to materialize without running")
    parser.add_argument("--start-batch", type=int, choices=(1, 2), default=1,
                        help="first batch to execute; use 2 for the guarded handoff")
    args = parser.parse_args()
    if args.materialize_only:
        paths, proposals = materialize_batch(
            args.project_root, args.batch, args.solver_workers)
        print(json.dumps({"searches": len(paths), "candidates": len(proposals)}, indent=2))
        return
    run_program(args.project_root, args.slots, args.solver_workers,
                args.start_batch)


if __name__ == "__main__":
    main()
