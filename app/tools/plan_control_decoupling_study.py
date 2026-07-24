#!/usr/bin/env python3
"""Plan the canonical round-horn L/K/N control-decoupling study.

This command performs geometry and reuse audits only. It never launches BEM.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from dataclasses import dataclass
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import qmc
import yaml

from .export_horncad import osse_radius, termination_metrics
from .run_bem_search import geometry_feasibility


ANGLES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)
LENGTH_FACTORS = (0.80, 1.00, 1.20)
K_LEVELS = (2.0, 4.0, 6.0)
N_LEVELS = (4.0, 8.0, 16.0)
BOUNDARY_LENGTH_FACTORS = (0.70, 1.30)
CLOSURE_LENGTH_FACTORS = (0.60, 1.40)
CLOSURE_K_LEVELS = (1.0, 7.0)
CLOSURE_N_LEVELS = (2.0, 20.0)
PROFILE_SAMPLE_COUNT = 41
PROFILE_RMS_MATERIALITY = 0.01
REUSE_LENGTH_TOLERANCE_MM = 0.25
VALIDATION_POINTS_PER_CELL = 2
MAX_REGISTERED_COORDINATES = 950
MAX_NEW_BEM_CANDIDATES = 800
CANONICAL_SCHEMA = 1


@dataclass(frozen=True)
class ReusableResult:
    coverage_deg: int
    mouth_mm: int
    length_mm: float
    k: float
    n: float
    score: float
    search_path: str
    candidate_id: str
    response_path: str
    report_path: str | None
    completed_at_unix: float


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _baseline(source_root: Path, angle: int, mouth: int) -> Path:
    path = source_root / f"{angle}deg" / f"{mouth}x{mouth}-s-grid"
    if not (path / "project.yaml").is_file() or not (path / "search.yaml").is_file():
        raise FileNotFoundError(f"missing canonical source baseline: {path}")
    return path


def _search_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["bem_candidate_search"]


def _project_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["horncad_config"]


def _solver_fingerprint(search: dict[str, Any]) -> dict[str, Any]:
    solver = copy.deepcopy(search.get("solver", {}))
    solver.pop("workers", None)
    return {
        "lower_frequency_hz": search.get("lower_frequency_hz"),
        "crossover_hz": search.get("crossover_hz"),
        "upper_frequency_hz": search.get("upper_frequency_hz"),
        "sampling_stability_points": search.get("sampling_stability_points"),
        "confirmation_points_per_octave": search.get(
            "confirmation_points_per_octave"),
        "solver": solver,
    }


def _record_values(record: dict[str, Any]) -> tuple[float, float, float] | None:
    values = record.get("values", {})
    try:
        if abs(float(values.get("extension_mm", 0.0))) > 1e-6:
            return None
        if abs(float(values["osse_coverage_h_deg"]) -
               float(values["osse_coverage_v_deg"])) > 1e-6:
            return None
        if (abs(float(values["k_h"]) - float(values["k_v"])) > 1e-6 or
                abs(float(values["n_h"]) - float(values["n_v"])) > 1e-6):
            return None
        return (float(values["length_mm"]), float(values["k_h"]),
                float(values["n_h"]))
    except (KeyError, TypeError, ValueError):
        return None


def reusable_results(source_root: Path) -> list[ReusableResult]:
    """Return only solver-compatible completed responses in the retained domain."""
    baseline_fingerprints = {
        (angle, mouth): _solver_fingerprint(_search_config(
            _baseline(source_root, angle, mouth) / "search.yaml"))
        for angle in ANGLES for mouth in MOUTHS
    }
    results: list[ReusableResult] = []
    for state_path in sorted(source_root.glob("*deg/*x*/search_state.json")):
        try:
            angle = int(state_path.parent.parent.name.removesuffix("deg"))
            mouth = int(state_path.parent.name.split("x", 1)[0])
        except ValueError:
            continue
        if angle not in ANGLES or mouth not in MOUTHS:
            continue
        search_path = state_path.parent / "search.yaml"
        if not search_path.is_file():
            continue
        try:
            fingerprint = _solver_fingerprint(_search_config(search_path))
        except (KeyError, TypeError, yaml.YAMLError):
            continue
        if fingerprint != baseline_fingerprints[(angle, mouth)]:
            continue
        state = _read_json(state_path)
        for record in state.get("candidates", []):
            if record.get("status") != "complete":
                continue
            values = _record_values(record)
            score = record.get("surface_diagnostics", {}).get(
                "score", {}).get("overall_percent")
            if values is None or not isinstance(score, (int, float)):
                continue
            candidate_id = str(record.get("id", ""))
            candidate_dir = state_path.parent / "candidates" / candidate_id
            response = candidate_dir / "bem" / "responses.npz"
            if not response.is_file():
                continue
            reports = sorted((candidate_dir / "bem").glob("*_Report.html"))
            results.append(ReusableResult(
                coverage_deg=angle, mouth_mm=mouth,
                length_mm=values[0], k=values[1], n=values[2],
                score=float(score),
                search_path=str(state_path.parent.relative_to(source_root)),
                candidate_id=candidate_id,
                response_path=str(response.relative_to(source_root)),
                report_path=(str(reports[0].relative_to(source_root))
                             if reports else None),
                completed_at_unix=float(record.get("completed_at_unix", 0.0)),
            ))
    return results


def _cell_reference(results: list[ReusableResult], angle: int,
                    mouth: int) -> ReusableResult:
    candidates = [item for item in results if
                  item.coverage_deg == angle and item.mouth_mm == mouth and
                  math.isclose(item.k, 4.0, abs_tol=1e-6) and
                  math.isclose(item.n, 10.0, abs_tol=1e-6)]
    if not candidates:
        raise RuntimeError(f"no reusable K4/N10 reference for {angle}°/{mouth} mm")
    return max(candidates, key=lambda item: item.score)


def _geometry_audit(config: dict[str, Any], coverage: float, length: float,
                    k: float, n: float) -> tuple[dict[str, float] | None, str | None]:
    global_config = config["global"]
    try:
        metrics = termination_metrics(
            length, float(global_config["throat_radius"]), coverage, k, n,
            float(global_config["mouth_width"]) / 2,
            float(global_config["throat_angle_deg"]),
        )
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        return None, f"OS-SE solution failed: {error}"
    derived = {
        "s_h": metrics["s"], "s_v": metrics["s"],
        "mouth_exit_angle_h_deg": metrics["exit_angle_deg"],
        "mouth_exit_angle_v_deg": metrics["exit_angle_deg"],
        "mouth_curvature_radius_h_mm": metrics["curvature_radius_mm"],
        "mouth_curvature_radius_v_mm": metrics["curvature_radius_mm"],
        "normalized_mouth_curvature_h": metrics["normalized_curvature_radius"],
        "normalized_mouth_curvature_v": metrics["normalized_curvature_radius"],
        "final_tenth_radial_growth_h": metrics[
            "final_tenth_radial_growth_fraction"],
        "final_tenth_radial_growth_v": metrics[
            "final_tenth_radial_growth_fraction"],
    }
    feasible, reason = geometry_feasibility(derived)
    if not feasible:
        return None, reason
    if not 0.05 <= float(metrics["s"]) <= 4.0:
        return None, f"derived S={metrics['s']:.3f} is outside 0.05-4.0"
    return {key: float(value) for key, value in metrics.items()}, None


def _profile(config: dict[str, Any], coverage: float, length: float,
             k: float, n: float, s: float) -> np.ndarray:
    global_config = config["global"]
    mouth_radius = float(global_config["mouth_width"]) / 2
    throat_radius = float(global_config["throat_radius"])
    throat_angle = float(global_config["throat_angle_deg"])
    return np.asarray([
        osse_radius(t * length, length, throat_radius, coverage, k, n, s,
                    throat_angle) / mouth_radius
        for t in np.linspace(0.0, 1.0, PROFILE_SAMPLE_COUNT)
    ])


def _factor_stage(length_level: int, k_level: int, n_level: int) -> str:
    active = sum(level != 0 for level in (length_level, k_level, n_level))
    return ("core-axis" if active <= 1 else
            "two-factor-face" if active == 2 else "three-factor-corner")


def _reuse_match(results: list[ReusableResult], angle: int, mouth: int,
                 length: float, k: float, n: float) -> ReusableResult | None:
    matches = [item for item in results if
               item.coverage_deg == angle and item.mouth_mm == mouth and
               abs(item.length_mm - length) <= REUSE_LENGTH_TOLERANCE_MM and
               math.isclose(item.k, k, abs_tol=1e-6) and
               math.isclose(item.n, n, abs_tol=1e-6)]
    return max(matches, key=lambda item: item.completed_at_unix) if matches else None


def _validation_coordinates(angle: int, mouth: int) -> list[tuple[float, float, float]]:
    """Return deterministic locked interior points, independent of BEM outcomes."""
    sampler = qmc.Sobol(d=3, scramble=True, seed=angle * 1000 + mouth)
    output: list[tuple[float, float, float]] = []
    for row in sampler.random_base2(m=3):
        length_factor = round(0.82 + 0.36 * float(row[0]), 3)
        k = round((3.0 + 2.0 * float(row[1])) * 2) / 2
        n = float(round(6.0 + 8.0 * float(row[2])))
        coordinate = (length_factor, k, n)
        if coordinate not in output:
            output.append(coordinate)
        if len(output) == VALIDATION_POINTS_PER_CELL:
            break
    if len(output) != VALIDATION_POINTS_PER_CELL:
        raise RuntimeError("could not create two distinct validation coordinates")
    return output


def build_manifest(source_root: Path) -> dict[str, Any]:
    results = reusable_results(source_root)
    coordinates: list[dict[str, Any]] = []
    for angle in ANGLES:
        for mouth in MOUTHS:
            baseline = _baseline(source_root, angle, mouth)
            config = _project_config(baseline / "project.yaml")
            reference = _cell_reference(results, angle, mouth)
            cell_rows: list[dict[str, Any]] = []
            accepted_profiles: dict[float, list[tuple[np.ndarray, str]]] = defaultdict(list)
            grid = [
                (li - 1, ki - 1, ni - 1, length_factor, k, n)
                for li, length_factor in enumerate(LENGTH_FACTORS)
                for ki, k in enumerate(K_LEVELS)
                for ni, n in enumerate(N_LEVELS)
            ]
            grid.sort(key=lambda item: (
                sum(level != 0 for level in item[:3]),
                sum(abs(level) for level in item[:3]), item[:3]))
            for length_level, k_level, n_level, length_factor, k, n in grid:
                length = round(reference.length_mm * length_factor, 3)
                identifier = (
                    f"{angle}d-{mouth}mm-L{length_level:+d}-"
                    f"K{k_level:+d}-N{n_level:+d}")
                metrics, rejection = _geometry_audit(
                    config, angle, length, k, n)
                row: dict[str, Any] = {
                    "id": identifier, "kind": "canonical-grid",
                    "stage": _factor_stage(length_level, k_level, n_level),
                    "coverage_deg": angle, "mouth_mm": mouth,
                    "length_level": length_level, "k_level": k_level,
                    "n_level": n_level, "length_factor": length_factor,
                    "stratum": (f"L{length_level:+d}_K{k_level:+d}_N{n_level:+d}"),
                    "length_mm": length, "k": k, "n": n,
                    "reference_length_mm": reference.length_mm,
                    "reference_result": {
                        "search": reference.search_path,
                        "candidate_id": reference.candidate_id,
                        "score": reference.score,
                    },
                }
                if metrics is None:
                    row.update(status="geometry-rejected", reason=rejection)
                    cell_rows.append(row)
                    continue
                row.update(
                    s=metrics["s"], exit_angle_deg=metrics["exit_angle_deg"],
                    normalized_curvature_radius=metrics[
                        "normalized_curvature_radius"],
                    final_tenth_radial_growth_fraction=metrics[
                        "final_tenth_radial_growth_fraction"],
                )
                profile = _profile(config, angle, length, k, n, metrics["s"])
                same_length = accepted_profiles[length]
                redundant = None
                for other_profile, other_id in same_length:
                    rms = float(np.sqrt(np.mean((profile - other_profile) ** 2)))
                    if rms < PROFILE_RMS_MATERIALITY:
                        redundant = (other_id, rms)
                        break
                if redundant is not None:
                    row.update(
                        status="geometry-redundant",
                        reason=("normalized radial profile changes less than 1% RMS"),
                        represented_by=redundant[0],
                        profile_rms_difference=redundant[1],
                    )
                    cell_rows.append(row)
                    continue
                same_length.append((profile, identifier))
                reused = _reuse_match(results, angle, mouth, length, k, n)
                if reused:
                    row.update(status="reused", reused_from={
                        "search": reused.search_path,
                        "candidate_id": reused.candidate_id,
                        "response": reused.response_path,
                        "report": reused.report_path,
                        "score": reused.score,
                    })
                else:
                    row["status"] = "planned"
                cell_rows.append(row)
            for index, (length_factor, k, n) in enumerate(
                    _validation_coordinates(angle, mouth), start=1):
                length = round(reference.length_mm * length_factor, 3)
                identifier = f"{angle}d-{mouth}mm-validation-{index:02d}"
                metrics, rejection = _geometry_audit(
                    config, angle, length, k, n)
                row = {
                    "id": identifier, "kind": "locked-validation",
                    "stage": "locked-validation", "coverage_deg": angle,
                    "mouth_mm": mouth, "length_factor": length_factor,
                    "length_mm": length, "k": k, "n": n,
                    "reference_length_mm": reference.length_mm,
                    "locked_before_bem": True,
                }
                if metrics is None:
                    row.update(status="geometry-rejected", reason=rejection)
                else:
                    row.update(
                        status="planned", s=metrics["s"],
                        exit_angle_deg=metrics["exit_angle_deg"],
                        normalized_curvature_radius=metrics[
                            "normalized_curvature_radius"],
                        final_tenth_radial_growth_fraction=metrics[
                            "final_tenth_radial_growth_fraction"],
                    )
                cell_rows.append(row)
            # The K4/N10 result that defined the length reference is preserved as
            # a free historical anchor even though N=10 is not a factorial level.
            reference_metrics, reference_rejection = _geometry_audit(
                config, angle, reference.length_mm, 4.0, 10.0)
            if reference_metrics is None:
                raise RuntimeError(
                    f"reference failed current geometry gate for {angle}°/{mouth} mm: "
                    f"{reference_rejection}")
            cell_rows.append({
                "id": f"{angle}d-{mouth}mm-reference-K4-N10",
                "kind": "reference-anchor", "stage": "reference-anchor",
                "coverage_deg": angle, "mouth_mm": mouth,
                "length_factor": 1.0, "length_mm": reference.length_mm,
                "k": 4.0, "n": 10.0, "s": reference_metrics["s"],
                "exit_angle_deg": reference_metrics["exit_angle_deg"],
                "normalized_curvature_radius": reference_metrics[
                    "normalized_curvature_radius"],
                "final_tenth_radial_growth_fraction": reference_metrics[
                    "final_tenth_radial_growth_fraction"],
                "status": "reused",
                "reused_from": {
                    "search": reference.search_path,
                    "candidate_id": reference.candidate_id,
                    "response": reference.response_path,
                    "report": reference.report_path,
                    "score": reference.score,
                },
            })
            # Only these sparse length sentinels inspect the wider range. The full
            # interaction grid does not spend 200 corners in likely bad extremes.
            for boundary_index, length_factor in enumerate(
                    BOUNDARY_LENGTH_FACTORS, start=1):
                length = round(reference.length_mm * length_factor, 3)
                metrics, rejection = _geometry_audit(
                    config, angle, length, 4.0, 8.0)
                row = {
                    "id": f"{angle}d-{mouth}mm-boundary-L{boundary_index}",
                    "kind": "boundary-sentinel", "stage": "boundary-sentinel",
                    "coverage_deg": angle, "mouth_mm": mouth,
                    "length_factor": length_factor, "length_mm": length,
                    "k": 4.0, "n": 8.0,
                    "reference_length_mm": reference.length_mm,
                }
                if metrics is None:
                    row.update(status="geometry-rejected", reason=rejection)
                else:
                    row.update(
                        status="planned", s=metrics["s"],
                        exit_angle_deg=metrics["exit_angle_deg"],
                        normalized_curvature_radius=metrics[
                            "normalized_curvature_radius"],
                        final_tenth_radial_growth_fraction=metrics[
                            "final_tenth_radial_growth_fraction"],
                    )
                cell_rows.append(row)
            closure_specs = (
                ("L-low", CLOSURE_LENGTH_FACTORS[0], 4.0, 8.0, -1, 0, 0),
                ("L-high", CLOSURE_LENGTH_FACTORS[1], 4.0, 8.0, 1, 0, 0),
                ("K-low", 1.0, CLOSURE_K_LEVELS[0], 8.0, 0, -1, 0),
                ("K-high", 1.0, CLOSURE_K_LEVELS[1], 8.0, 0, 1, 0),
                ("N-low", 1.0, 4.0, CLOSURE_N_LEVELS[0], 0, 0, -1),
                ("N-high", 1.0, 4.0, CLOSURE_N_LEVELS[1], 0, 0, 1),
            )
            for label, length_factor, k, n, length_direction, k_direction, n_direction in closure_specs:
                length = round(reference.length_mm * length_factor, 3)
                metrics, rejection = _geometry_audit(config, angle, length, k, n)
                row = {
                    "id": f"{angle}d-{mouth}mm-closure-{label}",
                    "kind": "conditional-axis-closure", "stage": "axis-closure",
                    "coverage_deg": angle, "mouth_mm": mouth,
                    "length_factor": length_factor, "length_mm": length,
                    "k": k, "n": n, "reference_length_mm": reference.length_mm,
                    "closure_axis": label[0], "closure_direction": label.split("-", 1)[1],
                    "length_level": length_direction, "k_level": k_direction,
                    "n_level": n_direction,
                }
                if metrics is None:
                    row.update(status="geometry-rejected", reason=rejection)
                else:
                    profile = _profile(config, angle, length, k, n, metrics["s"])
                    redundant = None
                    for other_profile, other_id in accepted_profiles[length]:
                        rms = float(np.sqrt(np.mean((profile - other_profile) ** 2)))
                        if rms < PROFILE_RMS_MATERIALITY:
                            redundant = (other_id, rms)
                            break
                    row.update(
                        s=metrics["s"], exit_angle_deg=metrics["exit_angle_deg"],
                        normalized_curvature_radius=metrics[
                            "normalized_curvature_radius"],
                        final_tenth_radial_growth_fraction=metrics[
                            "final_tenth_radial_growth_fraction"],
                    )
                    if redundant:
                        row.update(
                            status="geometry-redundant",
                            reason="normalized radial profile changes less than 1% RMS",
                            represented_by=redundant[0],
                            profile_rms_difference=redundant[1],
                        )
                    else:
                        row["status"] = "conditional"
                cell_rows.append(row)
            coordinates.extend(cell_rows)
    counts = Counter(row["status"] for row in coordinates)
    stage_counts = {
        stage: dict(Counter(row["status"] for row in coordinates
                            if row["stage"] == stage))
        for stage in ("reference-anchor", "core-axis", "boundary-sentinel",
                      "axis-closure",
                      "two-factor-face", "three-factor-corner",
                      "locked-validation")
    }
    active_grid = [row for row in coordinates if
                   row["kind"] == "canonical-grid" and
                   row["status"] in {"planned", "reused"}]
    factor_matrix = np.asarray([[
        row["length_level"], row["k_level"], row["n_level"]]
        for row in active_grid], dtype=float)
    length_axis, k_axis, n_axis = factor_matrix.T
    quadratic = np.column_stack([
        np.ones(len(factor_matrix)), length_axis, k_axis, n_axis,
        length_axis ** 2, k_axis ** 2, n_axis ** 2,
        length_axis * k_axis, length_axis * n_axis, k_axis * n_axis,
    ])
    active_by_cell = Counter(
        (row["coverage_deg"], row["mouth_mm"]) for row in active_grid)
    cell_model_audit = {}
    for angle in ANGLES:
        for mouth in MOUTHS:
            cell = [row for row in active_grid if
                    row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
            cell_factors = np.asarray([[
                row["length_level"], row["k_level"], row["n_level"]]
                for row in cell], dtype=float)
            cell_l, cell_k, cell_n = cell_factors.T
            cell_quadratic = np.column_stack([
                np.ones(len(cell)), cell_l, cell_k, cell_n,
                cell_l ** 2, cell_k ** 2, cell_n ** 2,
                cell_l * cell_k, cell_l * cell_n, cell_k * cell_n,
            ])
            cell_model_audit[f"{angle}deg-{mouth}mm"] = {
                "coordinates": len(cell),
                "quadratic_model_rank": int(np.linalg.matrix_rank(cell_quadratic)),
                "quadratic_model_condition": float(np.linalg.cond(cell_quadratic)),
            }
    per_cell_level_counts = {
        factor: {
            str(level): {
                "minimum": min(sum(
                    row[factor] == level and row["coverage_deg"] == angle and
                    row["mouth_mm"] == mouth for row in active_grid)
                    for angle in ANGLES for mouth in MOUTHS),
                "maximum": max(sum(
                    row[factor] == level and row["coverage_deg"] == angle and
                    row["mouth_mm"] == mouth for row in active_grid)
                    for angle in ANGLES for mouth in MOUTHS),
            } for level in (-1, 0, 1)
        } for factor in ("length_level", "k_level", "n_level")
    }
    design_audit = {
        "active_factorial_coordinates": len(active_grid),
        "active_coordinates_per_cell": {
            "minimum": min(active_by_cell.values()),
            "maximum": max(active_by_cell.values()),
        },
        "factor_correlation_matrix": np.corrcoef(
            factor_matrix, rowvar=False).tolist(),
        "quadratic_model_rank": int(np.linalg.matrix_rank(quadratic)),
        "quadratic_model_condition": float(np.linalg.cond(quadratic)),
        "cell_quadratic_models": cell_model_audit,
        "per_cell_factor_level_counts": per_cell_level_counts,
    }
    return {
        "schema_version": CANONICAL_SCHEMA,
        "study": "round-horn-control-decoupling",
        "source_evidence_root": "../mouth-size-coverage-grid",
        "domain": {"coverage_deg": list(ANGLES), "mouth_mm": list(MOUTHS)},
        "fixed_design": {
            "type": "three-level full factorial plus locked validation",
            "length_factors": list(LENGTH_FACTORS),
            "k_levels": list(K_LEVELS), "n_levels": list(N_LEVELS),
            "canonical_grid_coordinates": 675,
            "reference_anchors": 25,
            "boundary_length_factors": list(BOUNDARY_LENGTH_FACTORS),
            "boundary_sentinels": 50,
            "locked_validation_coordinates": 50,
            "conditional_axis_closure_coordinates": 150,
            "conditional_closure_length_factors": list(CLOSURE_LENGTH_FACTORS),
            "conditional_closure_k_levels": list(CLOSURE_K_LEVELS),
            "conditional_closure_n_levels": list(CLOSURE_N_LEVELS),
            "maximum_registered_coordinates": MAX_REGISTERED_COORDINATES,
            "maximum_new_bem_candidates": MAX_NEW_BEM_CANDIDATES,
        },
        "geometry_policy": {
            "profile_rms_materiality_fraction": PROFILE_RMS_MATERIALITY,
            "derived_s_bounds": [0.05, 4.0],
            "known_disc_like_examples_must_be_rejected": [
                {"mouth_mm": 300, "coverage_deg": 30, "length_mm": 116.54,
                 "k": 4, "n": 10},
                {"mouth_mm": 500, "coverage_deg": 35, "length_mm": 174.0,
                 "k": 4, "n": 10},
            ],
        },
        "reuse_policy": {
            "length_tolerance_mm": REUSE_LENGTH_TOLERANCE_MM,
            "requires_identical_k_n": True,
            "requires_solver_frequency_fingerprint": True,
            "requires_retained_responses_npz": True,
            "compatible_source_results": len(results),
        },
        "prior_evidence": {
            "length_centers": (
                "best retained K4/N10 S-grid length in each cell; 23 cells have "
                "closed S evidence and two are geometry-limited"),
            "k_range": (
                "matched fine-step gains are generally small near K4-K6, but K6 "
                "is not independently closed; use K2/4/6 plus conditional K1/7"),
            "n2": (
                "14 retained N2 results are noncompetitive; four fixed-length/fixed-K "
                "matches trail N5-N10 by 14.9-17.6 score points; N2 closure only"),
            "n_center": (
                "N4/8/16 preserves a full-rank physically distinct model in all "
                "25 cells; N4/10/16 becomes rank-deficient in some cells"),
        },
        "execution_policy": {
            "stage_order": ["reference-anchor", "core-axis",
                            "boundary-sentinel", "axis-closure", "two-factor-face",
                            "three-factor-corner", "locked-validation"],
            "solver_slots": 2, "workers_per_slot": 10,
            "axis_stage_is_never_score_pruned": True,
            "factorial_score_pruning_enabled": False,
            "factorial_completion_rule": (
                "run every feasible, profile-distinct canonical factorial coordinate; "
                "linked effects may reverse with mouth, coverage, S, or length"),
            "handoff_rule": (
                "a completed or geometry-rejected search immediately releases its slot; "
                "single-candidate searches use an explicit seed candidate rather than an "
                "empty initial pool"),
            "axis_closure_rule": (
                "run the next outward L, K, or N endpoint only when the measured "
                "inner endpoint improves score by at least 0.5 points or provides "
                "a material diagnostic improvement over the center; N=2 is only "
                "the conditional lower safety-bound probe after N=4 points outward"),
        },
        "completion_policy": {
            "all_registered_coordinates_have_terminal_status": True,
            "locked_validation_is_not_used_for_selection": True,
            "report_diagnostic_specific_held_cell_errors": True,
            "report_raw_control_correlations_and_physical_coverage": True,
            "no_conclusion_from_one_cell_only": True,
        },
        "analysis_policy": {
            "primary_outcomes": [
                "surface_score", "mean_containment", "profile_rms_error_db",
                "slice_energy_departure_db", "outward_rise_violation_db",
                "minus_six_rms_error_deg",
            ],
            "within_cell_model_terms": [
                "intercept", "L", "K", "N", "L^2", "K^2", "N^2",
                "L*K", "L*N", "K*N",
            ],
            "within_cell_models_required_for_all_25_cells": True,
            "primary_confirmatory_dataset": (
                "canonical study coordinates plus only strict exact-response reuses; "
                "historical optimizer traces do not fill missing canonical contrasts"),
            "augmented_predictive_dataset": (
                "after confirmatory analysis, add all solver-compatible historical "
                "responses with provenance retained for prediction and transfer checks"),
            "second_stage": (
                "map the same within-cell coefficients across mouth and coverage; "
                "report replicated signs, magnitudes, and diagnostic tradeoffs"),
            "locked_validation": (
                "evaluate interpolation at two preregistered interior points per cell; "
                "never use these points to fit, select, or prune"),
        },
        "status_counts": dict(counts), "stage_counts": stage_counts,
        "design_audit": design_audit,
        "coordinates": coordinates,
    }


def validate_manifest(manifest: dict[str, Any], source_root: Path) -> list[str]:
    errors: list[str] = []
    rows = manifest.get("coordinates", [])
    if len(rows) != MAX_REGISTERED_COORDINATES:
        errors.append(f"expected {MAX_REGISTERED_COORDINATES} coordinates, got {len(rows)}")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("candidate ids are not unique")
    grid = [row for row in rows if row["kind"] == "canonical-grid"]
    validation = [row for row in rows if row["kind"] == "locked-validation"]
    anchors = [row for row in rows if row["kind"] == "reference-anchor"]
    boundaries = [row for row in rows if row["kind"] == "boundary-sentinel"]
    closures = [row for row in rows if row["kind"] == "conditional-axis-closure"]
    if (len(grid), len(anchors), len(boundaries), len(validation), len(closures)) != (675, 25, 50, 50, 150):
        errors.append(
            "expected 675 grid/25 anchors/50 boundaries/50 validation, got "
            f"{len(grid)}/{len(anchors)}/{len(boundaries)}/{len(validation)}/{len(closures)}")
    for angle in ANGLES:
        for mouth in MOUTHS:
            cell_grid = [row for row in grid if row["coverage_deg"] == angle and
                         row["mouth_mm"] == mouth]
            cell_validation = [row for row in validation
                               if row["coverage_deg"] == angle and
                               row["mouth_mm"] == mouth]
            cell_anchors = [row for row in anchors if
                            row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
            cell_boundaries = [row for row in boundaries if
                               row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
            cell_closures = [row for row in closures if
                             row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
            if (len(cell_grid), len(cell_anchors), len(cell_boundaries),
                    len(cell_validation), len(cell_closures)) != (27, 1, 2, 2, 6):
                errors.append(
                    f"{angle}°/{mouth} mm has {len(cell_grid)} grid, "
                    f"{len(cell_anchors)} anchors, {len(cell_boundaries)} boundaries, "
                    f"{len(cell_validation)} validation, and {len(cell_closures)} closure coordinates")
    allowed = {"planned", "conditional", "reused", "geometry-rejected", "geometry-redundant"}
    unknown = sorted(set(row["status"] for row in rows) - allowed)
    if unknown:
        errors.append(f"unknown coordinate statuses: {unknown}")
    new_bem = sum(row["status"] in {"planned", "conditional"} for row in rows)
    if new_bem > MAX_NEW_BEM_CANDIDATES:
        errors.append(f"new BEM ceiling exceeded: {new_bem} > {MAX_NEW_BEM_CANDIDATES}")
    audit = manifest.get("design_audit", {})
    if audit.get("quadratic_model_rank") != 10:
        errors.append("feasible factorial does not identify all quadratic terms")
    if float(audit.get("quadratic_model_condition", math.inf)) > 10:
        errors.append("feasible factorial quadratic condition exceeds 10")
    correlation = np.asarray(audit.get("factor_correlation_matrix", []))
    if correlation.shape != (3, 3) or np.max(
            np.abs(correlation - np.eye(3))) > 0.30:
        errors.append("feasibility filtering leaves control correlation above 0.30")
    if audit.get("active_coordinates_per_cell", {}).get("minimum", 0) < 15:
        errors.append("a cell retains fewer than 15 independent factorial points")
    for cell, cell_audit in audit.get("cell_quadratic_models", {}).items():
        if cell_audit.get("quadratic_model_rank") != 10:
            errors.append(f"{cell} cannot identify its quadratic control model")
        if float(cell_audit.get("quadratic_model_condition", math.inf)) > 10:
            errors.append(f"{cell} quadratic model condition exceeds 10")
    if audit.get("per_cell_factor_level_counts", {}).get(
            "n_level", {}).get("1", {}).get("minimum", 0) < 2:
        errors.append("a cell retains fewer than two physically active high-N points")
    # The actual geometry guard, not a prose promise, must reject known failures.
    for example in manifest["geometry_policy"]["known_disc_like_examples_must_be_rejected"]:
        angle, mouth = example["coverage_deg"], example["mouth_mm"]
        baseline_mouth = min(MOUTHS, key=lambda value: abs(value - mouth))
        config = _project_config(
            _baseline(source_root, angle, baseline_mouth) / "project.yaml")
        config = copy.deepcopy(config)
        config["global"]["mouth_width"] = float(mouth)
        config["global"]["mouth_height"] = float(mouth)
        metrics, _ = _geometry_audit(
            config, angle, example["length_mm"], example["k"], example["n"])
        if metrics is not None:
            errors.append(f"known disc-like geometry passed: {example}")
    return errors


def render_plan(manifest: dict[str, Any]) -> str:
    counts = manifest["status_counts"]
    audit = manifest["design_audit"]
    return f"""# Round-horn control-decoupling study

This directory is the clean canonical study for axisymmetric, round-mouth,
zero-extension OS-SE horns. Historical searches are evidence sources, not an
execution queue.

## Domain and registered design

- Coverage half-angles: 30, 35, 40, 45, and 50 degrees.
- Round mouth diameters: 250, 300, 350, 400, and 450 mm.
- Independent controls: physical length, K, and N. S is recorded as derived.
- Per cell: complete 3×3×3 factorial at length factors 0.80/1.00/1.20,
  K 2/4/6, and N 4/8/16.
- Per cell: one strictly reused K4/N10 reference and two length-only boundary
  sentinels at factors 0.70 and 1.30.
- Per cell: six conditional hard-boundary probes at length factors 0.60/1.40,
  K 1/7, and N 2/20. These are registered but run only after an inner endpoint
  points outward. N=2 is never part of the regular grid.
- Locked validation: two deterministic interior coordinates per cell.
- Registered ceiling: 675 factorial + 25 references + 50 boundary sentinels +
  50 validation + 150 conditional closure probes = 950 coordinates. The actual
  new-BEM ceiling remains 800.

Preflight currently classifies {counts.get('reused', 0)} coordinates as strictly
reusable, {counts.get('geometry-rejected', 0)} as invalid geometry,
{counts.get('geometry-redundant', 0)} as physically redundant, and
{counts.get('planned', 0)} as requiring BEM. A further
{counts.get('conditional', 0)} feasible closure probes run only when triggered.

After geometry and redundancy filtering, {audit['active_factorial_coordinates']}
independent factorial coordinates remain, with
{audit['active_coordinates_per_cell']['minimum']}-
{audit['active_coordinates_per_cell']['maximum']} per cell. The complete
quadratic control basis has rank {audit['quadratic_model_rank']} and condition
{audit['quadratic_model_condition']:.2f}; no absolute pairwise factor
correlation exceeds 0.30. Every cell retains at least two physically active
high-N points. More importantly, every cell independently retains rank 10 for
the same ten-term quadratic L/K/N model; per-cell condition numbers range from
{min(value['quadratic_model_condition'] for value in audit['cell_quadratic_models'].values()):.2f}
to {max(value['quadratic_model_condition'] for value in audit['cell_quadratic_models'].values()):.2f}.

## Why the grid is fixed

The full factorial gives balanced independent L, K, and N effects plus every
two- and three-control interaction. Existing results may fill exact slots but do
not alter the registered design. Dense optimizer traces cannot count as grid
coverage merely because they are numerous.

## Prior evidence retained

The physical-length center in each cell is the best retained K4/N10 S-grid
length, not a generic constant. Twenty-three retained cells have closed S
evidence and two are geometry-limited. This preserves the earlier mouth/coverage
length prescription while the factorial measures how K and N modify it.

K=2/4/6 brackets the useful K≈3-6 ridge more honestly than the earlier
2.5/4/5.5 proposal. Fine K changes near the ridge generally moved score by only
tenths, but K=6 was not independently closed, so K=1/7 remain conditional probes.

N=2 is not a regular sample. Four retained fixed-length/fixed-K comparisons put
it 14.9-17.6 score points below N=5-10; it runs only if N=4 unexpectedly improves
over N=8. N=4/8/16 is used because it leaves every cell full-rank and physically
distinct. Substituting N=10 for N=8 makes some cells rank-deficient through
profile redundancy; the K4/N10 anchor is still reused in every cell.

## Geometry and reuse gates

Every coordinate is solved analytically before meshing. Invalid OS-SE solutions,
derived S outside 0.05-4.0, excessive terminal radial growth, and other existing
geometry-feasibility failures are terminal geometry rejections. The known
300×300×116.54 mm 30-degree and 500×500×174 mm 35-degree disc-like examples are
unit-tested against this same gate.

At fixed length, a control change producing less than 1% RMS change in normalized
radial profile is recorded as geometry-redundant and receives no BEM solve.

Reuse requires matching mouth, coverage, K, N, length within 0.25 mm, identical
solver/frequency fingerprint, and a retained responses.npz archive. Reused
responses will be rescored with the current diagnostics before final analysis.

## Execution and completion policy

Execution order is reference anchors, core center/axes, sparse boundary sentinels,
conditional axis closure, two-factor faces, three-factor corners, then locked
validation. No canonical factorial coordinate is pruned by score. Every feasible,
profile-distinct center, axis, face, and corner runs because L/K/N effects are
already known to change with mouth, coverage, and derived S. This preserves the
same identifiable response model in every cell.

An outer L/K/N closure point runs only if the measured inner endpoint improves
score by at least 0.5 points or materially improves a component diagnostic over
the center. N=2 is therefore only a lower safety-bound check after N=4 beats N=8;
existing evidence gives no reason to sample it routinely.

Two searches with ten workers each keep twenty cores occupied. Search completion,
failure, or geometry rejection immediately releases a slot. Single-candidate
searches are explicitly supported; an empty initial pool is forbidden. One search
failure is isolated and cannot stall the other slot or the remaining searches.
The runner records the failure and finishes all independent work before reporting
the study blocked.

The study cannot be launched accidentally by either generator. The runner requires
the exact SHA-256 of the reviewed manifest, and refuses a stale execution plan or
a confirmation hash from an earlier version of the design.

## Completion

Every registered coordinate must finish as reused, complete, geometry-rejected,
geometry-redundant, pruned by a documented rule, or failed. Locked validation is
not used for candidate selection. Final reporting includes diagnostic-specific
held-cell errors, raw-control correlations, physical-space coverage, replicated
steering effects, and all pruning decisions.

`manifest.json` is authoritative. `index.html` is generated from it.

## Registered analysis

For each of the 25 cells, fit the same terms: intercept, L, K, N, L², K², N²,
L×K, L×N, and K×N. Fit each of the six originally registered outcomes
separately: legacy surface score v1, containment, profile error, slice-energy
departure, outward rise, and the secondary −6 dB error. This distinguishes a
score gain from the physical diagnostic tradeoff that produced it. Surface
score v2 was developed later and does not retroactively alter this
preregistration.

The second stage maps those cell-local coefficients across mouth and coverage,
looking for effects that repeat rather than relying on one optimizer trace or one
cell. The two locked interior points per cell test interpolation and are excluded
from fitting, selection, and pruning.

The primary confirmatory fit uses only this canonical study and strict exact
response reuses. A second augmented predictive fit may then add all compatible
historical responses, retaining source provenance. Historical optimizer traces
can improve prediction but cannot substitute for a missing canonical contrast.
"""


def render_index(manifest: dict[str, Any], progress: dict[str, Any] | None = None) -> str:
    counts = manifest["status_counts"]
    progress = progress or {}
    coordinate_status = progress.get("coordinate_status", {})
    rows = []
    for row in manifest["coordinates"]:
        reason = row.get("reason", "")
        status = coordinate_status.get(row["id"], row["status"])
        rows.append(
            "<tr>" + "".join([
                f"<td>{html.escape(row['id'])}</td>",
                f"<td>{row['coverage_deg']}°</td>",
                f"<td>{row['mouth_mm']} mm</td>",
                f"<td>{row['length_mm']:.1f}</td>",
                f"<td>{row['k']:g}</td><td>{row['n']:g}</td>",
                (f"<td>{row['s']:.2f}</td>" if isinstance(row.get("s"),
                 (int, float)) and math.isfinite(row["s"]) else "<td>—</td>"),
                f"<td>{html.escape(row['stage'])}</td>",
                f"<td>{html.escape(status)}</td>",
                f"<td>{html.escape(reason)}</td>",
            ]) + "</tr>")
    wave_rows = []
    for wave in progress.get("waves", []):
        wave_rows.append("<tr>" + "".join([
            f"<td>{html.escape(wave['wave'])}</td>",
            f"<td>{wave['searches']}</td><td>{wave['candidates']}</td>",
            f"<td>{wave['complete']}</td><td>{wave['running']}</td>",
            f"<td>{wave['not_started']}</td><td>{wave['failed']}</td>",
            f"<td>{wave['pruned']}</td>",
        ]) + "</tr>")
    runtime = progress.get("runtime", {})
    runtime_status = html.escape(str(runtime.get("status", "not launched")))
    manifest_digest = html.escape(str(progress.get("manifest_sha256", "—")))
    wave_section = ("<section><h2>Execution waves</h2>"
                    f"<p>Status: <strong>{runtime_status}</strong></p>"
                    "<div class='table-wrap wave-table'><table><thead><tr>"
                    "<th>Wave</th><th>Searches</th><th>Candidates</th>"
                    "<th>Complete</th><th>Running</th><th>Not started</th>"
                    "<th>Failed</th><th>Pruned</th></tr></thead><tbody>" +
                    "".join(wave_rows) + "</tbody></table></div></section>"
                    if wave_rows else "")
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Round-horn control decoupling</title><style>
:root{{--bg:#0b1117;--panel:#141d26;--text:#dce7f0;--muted:#8fa4b5;--line:#2b3c49}}
body{{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}}
main{{padding:20px;max-width:none}}h1{{margin-top:0}}.summary{{display:flex;gap:12px;flex-wrap:wrap}}
.card{{background:var(--panel);padding:12px 16px;border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:max-content}}
th,td{{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left}}th{{position:sticky;top:0;background:var(--panel)}}
.table-wrap{{overflow:auto;max-height:70vh;border:1px solid var(--line)}}.muted{{color:var(--muted)}}</style></head>
<body><main><h1>Round-horn control decoupling</h1>
<p>Frozen 3×3×3 L/K/N factorial across 25 cells, sparse boundaries, references, and locked validation. No BEM has been launched by the planner.</p>
<div class='summary'><div class='card'><strong>800</strong><br>registered</div>
<div class='card'><strong>{counts.get('planned', 0)}</strong><br>planned BEM</div>
<div class='card'><strong>{counts.get('reused', 0)}</strong><br>strict reuse</div>
<div class='card'><strong>{counts.get('geometry-rejected', 0)}</strong><br>geometry rejected</div>
<div class='card'><strong>{counts.get('geometry-redundant', 0)}</strong><br>geometry redundant</div></div>
<p class='muted'>Execution order and pruning rules are documented in study_plan.md. The manifest is authoritative.<br>Manifest SHA-256: <code>{manifest_digest}</code></p>
{wave_section}
<h2>Registered coordinates</h2>
<div class='table-wrap'><table><thead><tr><th>ID</th><th>Coverage</th><th>Mouth</th><th>Length mm</th><th>K</th><th>N</th><th>S</th><th>Stage</th><th>Status</th><th>Reason</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></main></body></html>"""


def write_study(source_root: Path, output: Path) -> dict[str, Any]:
    manifest = build_manifest(source_root)
    errors = validate_manifest(manifest, source_root)
    if errors:
        raise RuntimeError("manifest preflight failed:\n- " + "\n- ".join(errors))
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "study_plan.md").write_text(
        render_plan(manifest), encoding="utf-8")
    (output / "index.html").write_text(
        render_index(manifest), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("examples/mouth-size-coverage-grid"))
    parser.add_argument("--output", type=Path,
                        default=Path("examples/control-decoupling"))
    args = parser.parse_args()
    manifest = write_study(args.source, args.output)
    print(json.dumps({
        "coordinates": len(manifest["coordinates"]),
        "status_counts": manifest["status_counts"],
        "stage_counts": manifest["stage_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()
