#!/usr/bin/env python3
"""Prepare, run, validate, and export the unified round-control v2 model."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np
import yaml

from .export_horncad import termination_metrics
from .round_control_model import (
    ANGLES, MOUTHS, CONTROL_SCALING, DIAGNOSTICS, MODEL_TERMS,
    PREREGISTERED_DIAGNOSTICS, STUDY_ROOT, _basis, _content_hash,
    _digest_file, _errors, _normalize_numbers, _rescore, _solver_fingerprint,
    _summarize_errors, _validate_npz, evaluate_model,
)
from .run_bem_search import (
    candidate_artifact_stem, geometry_feasibility, materialize_candidate,
    run_search,
)


ROOT = Path(__file__).resolve().parents[2]
V1_PRIMARY = ROOT / "models/round_control_primary_v1/model.json"
V1_AUGMENTED = ROOT / "models/round_control_augmented_v1/model.json"
V2_ROOT = ROOT / "examples/round-control-v2-validation"
V2_MODEL_DIR = ROOT / "models/round_control_v2"
TRAINING_INDEX = ROOT / STUDY_ROOT / "model_source/training_index.json"
HISTORICAL_WEIGHTS = (0.0, 0.10, 0.25, 0.50, 1.0)
FOLD_COUNT = 5
VALIDATION_CELLS = (
    (30, 250), (30, 350), (30, 450),
    (35, 300), (35, 400),
    (40, 250), (40, 350),
    (45, 300), (45, 450),
    (50, 250), (50, 400), (50, 450),
)
LENGTH_FACTORS = (0.86, 0.92, 0.97, 1.03, 1.08, 1.14)
K_VALUES = (2.5, 3.0, 3.5, 4.5, 5.0, 5.5)
N_VALUES = (6.0, 7.0, 9.0, 10.0, 12.0, 14.0)
RELEASE_LIMITS = {
    "surface_score": {"mae": 1.75, "p90_absolute": 3.60},
    "mean_containment": {"p90_absolute": 0.12},
    "minus_six_db_rms_error": {"p90_absolute": 0.80},
    "outward_rise_violation": {"p90_absolute": 0.45},
    "profile_rms_error": {"p90_absolute": 0.18},
    "slice_energy_rms_departure": {"p90_absolute": 0.18},
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                   allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _development_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    roles = {"fit", "locked_validation", "historical_challenge"}
    return [row for row in index["rows"] if row["role"] in roles]


def _fold(row: dict[str, Any]) -> int:
    key = str(row["coordinate_hash"]).encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:8], 16) % FOLD_COUNT


def _diagnostic_scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    scales = {}
    for name in DIAGNOSTICS:
        values = np.asarray([row["responses"][name] for row in rows])
        q25, q75 = np.percentile(values, (25, 75))
        scales[name] = float(max(q75 - q25, np.std(values) * 0.25, 1e-6))
    return scales


def _density_weights(rows: list[dict[str, Any]],
                     historical_weight: float) -> np.ndarray:
    bins = Counter((
        int(row["coverage_deg"]),
        int(row["mouth_mm"]),
        round((row["length_factor"] - 1.0) / 0.05),
        round((row["k"] - 4.0) / 0.25),
        round((row["n"] - 8.0) / 1.0),
    ) for row in rows if row["provenance"] == "historical")
    return np.asarray([
        1.0 if row["provenance"] != "historical" else
        historical_weight / bins[(
            int(row["coverage_deg"]),
            int(row["mouth_mm"]),
            round((row["length_factor"] - 1.0) / 0.05),
            round((row["k"] - 4.0) / 0.25),
            round((row["n"] - 8.0) / 1.0),
        )]
        for row in rows
    ], dtype=float)


def _fit_cells(rows: list[dict[str, Any]], historical_weight: float
               ) -> tuple[dict[str, Any], dict[str, Any]]:
    cells = {}
    audit = {}
    for coverage in ANGLES:
        for mouth in MOUTHS:
            selected = [
                row for row in rows
                if int(row["coverage_deg"]) == coverage
                and int(row["mouth_mm"]) == mouth
                and (historical_weight > 0 or
                     row["provenance"] != "historical")
            ]
            x = np.vstack([
                _basis(row["length_factor"], row["k"], row["n"])
                for row in selected
            ])
            weights = _density_weights(selected, historical_weight)
            active = weights > 0
            if np.linalg.matrix_rank(x[active]) != len(MODEL_TERMS):
                raise ValueError(
                    f"{coverage}deg-{mouth}mm loses rank {len(MODEL_TERMS)}")
            root = np.sqrt(weights)
            xw = x * root[:, None]
            condition = float(np.linalg.cond(xw[active]))
            if not math.isfinite(condition) or condition > 1e8:
                raise ValueError(
                    f"{coverage}deg-{mouth}mm invalid condition {condition}")

            coefficients = {}
            covariance = {}
            residual_std = {}
            residual_matrix = []
            for diagnostic in DIAGNOSTICS:
                y = np.asarray([
                    row["responses"][diagnostic] for row in selected])
                beta, *_ = np.linalg.lstsq(xw, y * root, rcond=None)
                residual = y - x @ beta
                dof = max(1, int(np.count_nonzero(active)) - len(MODEL_TERMS))
                variance = float(np.sum(weights * residual**2) / dof)
                coefficients[diagnostic] = beta.tolist()
                covariance[diagnostic] = (
                    np.linalg.pinv(xw.T @ xw) * variance).tolist()
                residual_std[diagnostic] = math.sqrt(max(variance, 0.0))
                residual_matrix.append(residual)
            residual_array = np.asarray(residual_matrix)
            cell_id = f"{coverage}deg-{mouth}mm"
            cells[cell_id] = {
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "coefficients": coefficients,
                "coefficient_covariance": covariance,
                "residual_std": residual_std,
                "residual_covariance": np.cov(residual_array).tolist(),
                "support": {
                    "length_factor": [
                        min(row["length_factor"] for row in selected),
                        max(row["length_factor"] for row in selected),
                    ],
                    "k": [
                        min(row["k"] for row in selected),
                        max(row["k"] for row in selected),
                    ],
                    "n": [
                        min(row["n"] for row in selected),
                        max(row["n"] for row in selected),
                    ],
                },
                "evidence_ids": [row["id"] for row in selected],
            }
            audit[cell_id] = {
                "rows": len(selected),
                "canonical_rows": sum(
                    row["provenance"] != "historical" for row in selected),
                "historical_rows": sum(
                    row["provenance"] == "historical" for row in selected),
                "rank": int(np.linalg.matrix_rank(xw[active])),
                "condition_number": condition,
                "effective_weight": float(np.sum(weights)),
            }
    return cells, audit


def _base_model(index: dict[str, Any], cells: dict[str, Any],
                audit: dict[str, Any], historical_weight: float,
                model_id: str) -> dict[str, Any]:
    references = {}
    for row in index["rows"]:
        if row.get("reference_length_mm") is not None:
            references[
                f"{int(row['coverage_deg'])}deg-{int(row['mouth_mm'])}mm"
            ] = float(row["reference_length_mm"])
    model = {
        "schema_version": 2,
        "model_id": model_id,
        "model_family": "round symmetric square zero-extension OS-SE",
        "diagnostics": list(DIAGNOSTICS),
        "preregistered_diagnostics": list(PREREGISTERED_DIAGNOSTICS),
        "experimental_diagnostics": {
            "throat_impedance_score": {
                "status": "experimental preparatory output",
                "included_in_surface_score": False,
                "included_in_model_choice": False,
            },
        },
        "terms": list(MODEL_TERMS),
        "control_scaling": CONTROL_SCALING,
        "coefficient_interpolation": "bilinear",
        "mouth_grid_mm": list(MOUTHS),
        "coverage_grid_deg": list(ANGLES),
        "reference_length_mm": references,
        "geometry_policy": {
            "derived_s_bounds": [0.05, 4.0],
            "maximum_final_tenth_radial_growth_fraction": 0.52,
            "throat_radius_mm": 12.7,
            "throat_angle_deg": 6.0,
            "extension_mm": 0.0,
        },
        "cells": cells,
        "fit_audit": audit,
        "fit_roles": [
            "fit", "former_v1_locked_validation", "historical_challenge"],
        "historical_weighting": {
            "global_weight": historical_weight,
            "density_method": (
                "inverse occupancy in cell × 0.05 L-factor × 0.25 K × 1 N bins"),
            "cell_router": False,
        },
        "provenance": {
            "training_index_sha256": _content_hash(index),
            "diagnostic_implementation_sha256":
                index["diagnostic_implementation_sha256"],
            "coordinate_hash": index["coordinate_hash"],
            "fitting_implementation_sha256": _digest_file(Path(__file__)),
        },
    }
    return model


def _normalized_loss(error_rows: list[dict[str, Any]],
                     scales: dict[str, float]) -> dict[str, Any]:
    by_cell = defaultdict(list)
    for row in error_rows:
        cell = f"{int(row['coverage_deg'])}deg-{int(row['mouth_mm'])}mm"
        value = float(np.mean([
            abs(row["error"][name]) / scales[name]
            for name in PREREGISTERED_DIAGNOSTICS
        ]))
        by_cell[cell].append(value)
    all_values = [value for values in by_cell.values() for value in values]
    cell_values = {
        cell: float(np.mean(values)) for cell, values in sorted(by_cell.items())}
    mean_value = float(np.mean(all_values))
    worst = max(cell_values.values())
    return {
        "mean_equal_diagnostic_normalized_mae": mean_value,
        "worst_cell_equal_diagnostic_normalized_mae": worst,
        "selection_loss": mean_value + 0.25 * worst,
        "by_cell": cell_values,
    }


def _cross_validate(index: dict[str, Any], rows: list[dict[str, Any]],
                    historical_weight: float,
                    scales: dict[str, float]) -> dict[str, Any]:
    all_errors = []
    fold_audit = []
    for fold in range(FOLD_COUNT):
        training = [row for row in rows if _fold(row) != fold]
        withheld = [row for row in rows if _fold(row) == fold]
        cells, audit = _fit_cells(training, historical_weight)
        model = _base_model(
            index, cells, audit, historical_weight,
            f"round_control_v2_candidate_hw{historical_weight:g}")
        errors = _errors(model, withheld)
        all_errors.extend(errors)
        fold_audit.append({
            "fold": fold,
            "training_rows": len(training),
            "withheld_rows": len(withheld),
            "minimum_cell_rank": min(
                item["rank"] for item in audit.values()),
            "maximum_condition_number": max(
                item["condition_number"] for item in audit.values()),
        })
    return {
        "fold_count": FOLD_COUNT,
        "coordinate_grouping": "SHA-256(coordinate_hash) modulo five",
        "errors": _summarize_errors(all_errors),
        "normalized": _normalized_loss(all_errors, scales),
        "fold_audit": fold_audit,
        "withheld_row_count": len(all_errors),
    }


def _candidate_id(weight: float) -> str:
    return f"historical_weight_{str(weight).replace('.', 'p')}"


def _fit_candidates(index: dict[str, Any]) -> tuple[
        dict[str, dict[str, Any]], dict[str, Any]]:
    rows = _development_rows(index)
    scales = _diagnostic_scales(rows)
    candidates = {}
    comparison = {}
    for weight in HISTORICAL_WEIGHTS:
        cells, audit = _fit_cells(rows, weight)
        candidate_id = _candidate_id(weight)
        model = _base_model(
            index, cells, audit, weight,
            f"round_control_v2_candidate_{candidate_id}")
        cv = _cross_validate(index, rows, weight, scales)
        model["development_cross_validation"] = cv
        model["interval_half_width"] = {
            name: max(
                cv["errors"][name]["p90_absolute"],
                1.645 * max(
                    cell["residual_std"][name] for cell in cells.values()),
            )
            for name in DIAGNOSTICS
        }
        model["model_sha256"] = _content_hash(model)
        candidates[candidate_id] = model
        comparison[candidate_id] = {
            "historical_weight": weight,
            "model_sha256": model["model_sha256"],
            "cross_validation": cv,
        }
    provisional = min(
        comparison,
        key=lambda name:
        comparison[name]["cross_validation"]["normalized"]["selection_loss"])
    summary = {
        "schema_version": 2,
        "development_row_count": len(rows),
        "diagnostic_scales": scales,
        "candidate_order": list(candidates),
        "provisional_candidate": provisional,
        "provisional_selection_rule": (
            "minimum mean normalized MAE + 0.25 × worst-cell normalized MAE"),
        "comparison": comparison,
        "throat_impedance_used_in_selection": False,
    }
    return candidates, summary


def _geometry_values(row: dict[str, Any], length_factor: float,
                     k: float, n: float) -> dict[str, float] | None:
    length = float(row["reference_length_mm"]) * length_factor
    metrics = termination_metrics(
        length, 12.7, float(row["coverage_deg"]), k, n,
        float(row["mouth_mm"]) / 2.0, 6.0)
    derived = {
        "s_h": metrics["s"], "s_v": metrics["s"],
        "mouth_exit_angle_h_deg": metrics["exit_angle_deg"],
        "mouth_exit_angle_v_deg": metrics["exit_angle_deg"],
        "mouth_curvature_radius_h_mm": metrics["curvature_radius_mm"],
        "mouth_curvature_radius_v_mm": metrics["curvature_radius_mm"],
        "normalized_mouth_curvature_h": metrics["normalized_curvature_radius"],
        "normalized_mouth_curvature_v": metrics["normalized_curvature_radius"],
        "final_tenth_radial_growth_h":
            metrics["final_tenth_radial_growth_fraction"],
        "final_tenth_radial_growth_v":
            metrics["final_tenth_radial_growth_fraction"],
    }
    feasible, _ = geometry_feasibility(derived)
    if not feasible or not 0.05 <= float(metrics["s"]) <= 4.0:
        return None
    return {
        "length_mm": round(length, 3),
        "length_factor": length_factor,
        "k": k,
        "n": n,
        "derived_s": float(metrics["s"]),
    }


def _nearest_distance(candidate: dict[str, float],
                      rows: list[dict[str, Any]]) -> float:
    return min(math.sqrt(
        ((candidate["length_factor"] - row["length_factor"]) / 0.2) ** 2 +
        ((candidate["k"] - row["k"]) / 2.0) ** 2 +
        ((candidate["n"] - row["n"]) / 4.0) ** 2
    ) for row in rows)


def _prediction_spread(candidate: dict[str, float], mouth: int, coverage: int,
                       models: list[dict[str, Any]],
                       scales: dict[str, float]) -> float:
    predictions = [
        evaluate_model(
            model, mouth_mm=mouth, coverage_deg=coverage,
            length_mm=candidate["length_mm"], k=candidate["k"],
            n=candidate["n"])
        for model in models
    ]
    return float(np.mean([
        np.std([prediction[name] for prediction in predictions]) / scales[name]
        for name in PREREGISTERED_DIAGNOSTICS
    ]))


def _select_validation_coordinates(
        index: dict[str, Any], candidates: dict[str, dict[str, Any]],
        comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    v1_models = [_read_json(V1_PRIMARY), _read_json(V1_AUGMENTED)]
    models = list(candidates.values()) + v1_models
    scales = comparison["diagnostic_scales"]
    selected = []
    for coverage, mouth in VALIDATION_CELLS:
        cell_rows = [
            row for row in _development_rows(index)
            if int(row["coverage_deg"]) == coverage
            and int(row["mouth_mm"]) == mouth
        ]
        reference = cell_rows[0]
        existing = {
            (round(row["length_factor"], 5), round(row["k"], 5),
             round(row["n"], 5))
            for row in cell_rows
        }
        pool = []
        for length_factor in LENGTH_FACTORS:
            for k in K_VALUES:
                for n in N_VALUES:
                    if (round(length_factor, 5), round(k, 5),
                            round(n, 5)) in existing:
                        continue
                    value = _geometry_values(reference, length_factor, k, n)
                    if value is None:
                        continue
                    spread = _prediction_spread(
                        value, mouth, coverage, models, scales)
                    distance = _nearest_distance(value, cell_rows)
                    value["selection_spread"] = spread
                    value["nearest_development_distance"] = distance
                    value["selection_criterion"] = spread + 0.20 * min(distance, 2.0)
                    pool.append(value)
        if not pool:
            raise RuntimeError(f"no feasible validation pool for {coverage}/{mouth}")
        chosen = max(
            pool,
            key=lambda item: (
                item["selection_criterion"],
                item["nearest_development_distance"],
                item["length_factor"], item["k"], item["n"],
            ))
        predictions = {
            model["model_id"]: evaluate_model(
                model, mouth_mm=mouth, coverage_deg=coverage,
                length_mm=chosen["length_mm"], k=chosen["k"], n=chosen["n"])
            for model in models
        }
        selected.append({
            "id": (
                f"v2-locked-{coverage}deg-{mouth}mm-"
                f"L{chosen['length_factor']:g}-K{chosen['k']:g}-N{chosen['n']:g}"
            ),
            "coverage_deg": coverage,
            "mouth_mm": mouth,
            **chosen,
            "frozen_predictions": predictions,
        })
    return selected


def _source_project(index: dict[str, Any], coverage: int, mouth: int) -> Path:
    rows = [
        row for row in index["rows"]
        if row["role"] == "fit"
        and int(row["coverage_deg"]) == coverage
        and int(row["mouth_mm"]) == mouth
    ]
    if not rows:
        raise RuntimeError(f"no canonical source project for {coverage}/{mouth}")
    row = min(rows, key=lambda item:
              abs(item["length_factor"] - 1.0) +
              abs(item["k"] - 4.0) + abs(item["n"] - 8.0))
    response = ROOT / row["source_path"]
    project = response.parents[1] / "project.yaml"
    if not project.is_file():
        raise FileNotFoundError(project)
    return project


def _fixed_search(coordinate: dict[str, Any]) -> dict[str, Any]:
    coverage = float(coordinate["coverage_deg"])
    values = {
        "length_mm": float(coordinate["length_mm"]),
        "extension_mm": 0.0,
        "osse_coverage_h_deg": coverage,
        "osse_coverage_v_deg": coverage,
        "k_h": float(coordinate["k"]),
        "k_v": float(coordinate["k"]),
        "n_h": float(coordinate["n"]),
        "n_v": float(coordinate["n"]),
    }
    bounds = {
        name: [value - max(1e-6, abs(value) * 1e-9),
               value + max(1e-6, abs(value) * 1e-9)]
        for name, value in values.items()
    }
    search = {
        "version": 1,
        "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage,
        "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": 500.0,
        "crossover_hz": 750.0,
        "upper_frequency_hz": 8000.0,
        "max_evaluations": 1,
        "initial_candidates": 0,
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.049, 4.001],
        "sampling_stability_points": 2.0,
        "confirmation_points_per_octave": 16.0,
        "adaptive_pruning": {"enabled": False},
        "fixed_design": True,
        "bounds": bounds,
        "solver": {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 10,
        },
        "round_control_v2_validation": {
            "coordinate_id": coordinate["id"],
            "role": "fresh-locked-validation",
        },
    }
    return {"bem_candidate_search": search}, values


def _materialize_searches(index: dict[str, Any],
                          coordinates: list[dict[str, Any]]) -> None:
    for coordinate in coordinates:
        coverage = int(coordinate["coverage_deg"])
        mouth = int(coordinate["mouth_mm"])
        directory = V2_ROOT / "searches" / f"{coverage}deg" / f"{mouth}x{mouth}"
        source = yaml.safe_load(
            _source_project(index, coverage, mouth).read_text(encoding="utf-8"))
        document, values = _fixed_search(coordinate)
        project, _ = materialize_candidate(
            copy.deepcopy(source), values, document["bem_candidate_search"])
        _write_yaml(directory / "project.yaml", project)
        _write_yaml(directory / "search.yaml", document)


def prepare() -> dict[str, Any]:
    index = _read_json(TRAINING_INDEX)
    candidates, comparison = _fit_candidates(index)
    coordinates = _select_validation_coordinates(
        index, candidates, comparison)
    V2_ROOT.mkdir(parents=True, exist_ok=True)
    candidate_directory = V2_ROOT / "candidate_models"
    for candidate_id, model in candidates.items():
        _write_json(candidate_directory / f"{candidate_id}.json", model)
    _materialize_searches(index, coordinates)
    search_inputs = {}
    for coordinate in coordinates:
        coverage = int(coordinate["coverage_deg"])
        mouth = int(coordinate["mouth_mm"])
        directory = V2_ROOT / "searches" / f"{coverage}deg" / f"{mouth}x{mouth}"
        search_inputs[coordinate["id"]] = {
            "project_sha256": _digest_file(directory / "project.yaml"),
            "search_sha256": _digest_file(directory / "search.yaml"),
        }
    manifest = {
        "schema_version": 2,
        "status": "frozen-not-run",
        "domain": {
            "coverage_grid_deg": list(ANGLES),
            "mouth_grid_mm": list(MOUTHS),
            "full_grid_remains_supported": True,
        },
        "candidate_comparison": comparison,
        "validation_coordinates": coordinates,
        "search_inputs": search_inputs,
        "validation_cell_count": len(coordinates),
        "release_limits": RELEASE_LIMITS,
        "final_selection_rule": (
            "development-cross-validation winner must pass every fresh locked "
            "release gate; fresh outcomes cannot switch candidates"),
        "training_index_sha256": _content_hash(index),
        "v1_primary_sha256": _digest_file(V1_PRIMARY),
        "v1_augmented_sha256": _digest_file(V1_AUGMENTED),
        "implementation_sha256": _digest_file(Path(__file__)),
        "outcomes_loaded": False,
        "bem_jobs_scheduled": 0,
    }
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(V2_ROOT / "manifest.json", manifest)
    _write_json(V2_ROOT / "runtime_state.json", {
        "schema_version": 1,
        "status": "not-started",
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "events": [],
    })
    return manifest


def _verify_freeze() -> dict[str, Any]:
    manifest = _read_json(V2_ROOT / "manifest.json")
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items() if key != "freeze_sha256"})
    if expected != actual:
        raise ValueError("v2 validation manifest differs from its freeze hash")
    if manifest.get("outcomes_loaded"):
        raise ValueError("frozen preparation manifest already contains outcomes")
    for item in manifest["candidate_comparison"]["candidate_order"]:
        path = V2_ROOT / "candidate_models" / f"{item}.json"
        model = _read_json(path)
        expected_model = manifest["candidate_comparison"]["comparison"][
            item]["model_sha256"]
        actual_model = _content_hash({
            key: value for key, value in model.items() if key != "model_sha256"})
        if model["model_sha256"] != expected_model or actual_model != expected_model:
            raise ValueError(f"changed frozen candidate model: {item}")
    for coordinate_id, hashes in manifest["search_inputs"].items():
        coordinate = next(
            row for row in manifest["validation_coordinates"]
            if row["id"] == coordinate_id)
        directory = (
            V2_ROOT / "searches" /
            f"{int(coordinate['coverage_deg'])}deg" /
            f"{int(coordinate['mouth_mm'])}x{int(coordinate['mouth_mm'])}")
        if _digest_file(directory / "project.yaml") != hashes["project_sha256"]:
            raise ValueError(f"changed frozen project input: {coordinate_id}")
        if _digest_file(directory / "search.yaml") != hashes["search_sha256"]:
            raise ValueError(f"changed frozen search input: {coordinate_id}")
    return manifest


def _search_items(manifest: dict[str, Any]) -> list[tuple[str, Path]]:
    output = []
    for coordinate in manifest["validation_coordinates"]:
        coverage = int(coordinate["coverage_deg"])
        mouth = int(coordinate["mouth_mm"])
        directory = V2_ROOT / "searches" / f"{coverage}deg" / f"{mouth}x{mouth}"
        output.append((coordinate["id"], directory))
    return output


def status() -> dict[str, Any]:
    manifest = _verify_freeze()
    rows = []
    for coordinate_id, directory in _search_items(manifest):
        state_path = directory / "search_state.json"
        state = _read_json(state_path) if state_path.is_file() else {}
        rows.append({
            "id": coordinate_id,
            "status": state.get("status", "not-started"),
            "complete_candidates": sum(
                row.get("status") == "complete"
                for row in state.get("candidates", [])),
        })
    summary = dict(Counter(row["status"] for row in rows))
    return {"summary": summary, "rows": rows}


def preflight() -> dict[str, Any]:
    manifest = _verify_freeze()
    for _, directory in _search_items(manifest):
        state = run_search(
            directory / "search.yaml", directory, binary=None, dry_run=True)
        if state.get("status") != "preflight":
            raise ValueError(
                f"{directory}: expected preflight, got {state.get('status')}")
        candidates = state.get("candidates", [])
        if len(candidates) != 1 or candidates[0].get("status") != "preflight":
            raise ValueError(f"{directory}: incomplete fixed-design preflight")
    return status()


def _run_one(item: tuple[str, Path]) -> dict[str, Any]:
    coordinate_id, directory = item
    command = [
        sys.executable, "-m", "app.tools.run_bem_search",
        str(directory / "search.yaml"), "--output-dir", str(directory),
    ]
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True)
    return {
        "id": coordinate_id,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run(slots: int) -> dict[str, Any]:
    if slots < 1 or slots > 2:
        raise ValueError("slots must be 1 or 2; each BEM search uses ten workers")
    manifest = _verify_freeze()
    runtime_path = V2_ROOT / "runtime_state.json"
    runtime = _read_json(runtime_path)
    if runtime["manifest_freeze_sha256"] != manifest["freeze_sha256"]:
        raise ValueError("runtime state belongs to another validation manifest")
    pending = []
    for item in _search_items(manifest):
        coordinate_id, directory = item
        state_path = directory / "search_state.json"
        state = _read_json(state_path) if state_path.is_file() else {}
        if state.get("status") != "complete":
            pending.append(item)
        else:
            runtime["events"].append({
                "time_unix": time.time(), "id": coordinate_id,
                "status": "reused-complete",
            })
    runtime["status"] = "running"
    runtime["slots"] = slots
    runtime["started_at_unix"] = runtime.get("started_at_unix", time.time())
    _write_json(runtime_path, runtime)
    failures = []
    with ThreadPoolExecutor(max_workers=slots) as executor:
        futures = {executor.submit(_run_one, item): item for item in pending}
        for future in as_completed(futures):
            result = future.result()
            event = {
                "time_unix": time.time(),
                "id": result["id"],
                "status": (
                    "complete" if result["returncode"] == 0 else "failed"),
                "returncode": result["returncode"],
            }
            runtime["events"].append(event)
            _write_json(runtime_path, runtime)
            if result["returncode"]:
                failures.append(result)
    current = status()
    all_complete = (
        current["summary"].get("complete", 0) ==
        len(manifest["validation_coordinates"]))
    runtime["status"] = (
        "complete" if all_complete else
        "failed" if failures else "incomplete")
    runtime["completed_at_unix"] = time.time()
    runtime["failures"] = failures
    _write_json(runtime_path, runtime)
    if failures:
        raise RuntimeError(
            "one or more v2 validation searches failed: " +
            ", ".join(item["id"] for item in failures))
    if not all_complete:
        raise RuntimeError("v2 validation searches did not all complete")
    return runtime


def _validation_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    solver_fingerprints = set()
    for coordinate, (_, directory) in zip(
            manifest["validation_coordinates"], _search_items(manifest)):
        state = _read_json(directory / "search_state.json")
        complete = [
            row for row in state.get("candidates", [])
            if row.get("status") == "complete"]
        if len(complete) != 1:
            raise ValueError(
                f"{coordinate['id']}: expected one complete response")
        record = complete[0]
        response = directory / "candidates" / record["id"] / "bem/responses.npz"
        arrays, response_fingerprint = _validate_npz(response)
        values, impedance, delta = _rescore(response)
        if delta > 1e-9:
            raise ValueError(
                f"{coordinate['id']}: stored diagnostics differ by {delta:g}")
        search = yaml.safe_load(
            (directory / "search.yaml").read_text())["bem_candidate_search"]
        solver_fingerprints.add(_content_hash(_normalize_numbers(
            _solver_fingerprint(search))))
        rows.append({
            "id": coordinate["id"],
            "coverage_deg": coordinate["coverage_deg"],
            "mouth_mm": coordinate["mouth_mm"],
            "length_mm": coordinate["length_mm"],
            "length_factor": coordinate["length_factor"],
            "k": coordinate["k"],
            "n": coordinate["n"],
            "derived_s": coordinate["derived_s"],
            "provenance": "fresh-v2-locked",
            "benchmark": False,
            "responses": values,
            "throat_impedance": impedance,
            "response_sha256": _digest_file(response),
            "response_fingerprint": response_fingerprint,
            "npz_arrays": arrays,
            "source_path": str(response.relative_to(ROOT)),
        })
    if len(solver_fingerprints) != 1:
        raise ValueError("fresh validation searches do not share one solver fingerprint")
    return rows


def _release_checks(summary: dict[str, Any]) -> dict[str, Any]:
    checks = {}
    for diagnostic, limits in RELEASE_LIMITS.items():
        for metric, limit in limits.items():
            value = float(summary[diagnostic][metric])
            checks[f"{diagnostic}.{metric}"] = {
                "value": value, "limit": limit, "passed": value <= limit}
    return {
        "checks": checks,
        "passed": all(item["passed"] for item in checks.values()),
    }


def finalize() -> dict[str, Any]:
    manifest = _verify_freeze()
    current = status()
    if current["summary"].get("complete", 0) != len(VALIDATION_CELLS):
        raise ValueError("fresh v2 validation is incomplete")
    rows = _validation_rows(manifest)
    scales = manifest["candidate_comparison"]["diagnostic_scales"]
    results = {}
    for candidate_id in manifest["candidate_comparison"]["candidate_order"]:
        model = _read_json(
            V2_ROOT / "candidate_models" / f"{candidate_id}.json")
        errors = _errors(model, rows)
        results[candidate_id] = {
            "model_sha256": model["model_sha256"],
            "summary": _summarize_errors(errors),
            "normalized": _normalized_loss(errors, scales),
            "rows": errors,
        }
    selected_id = manifest["candidate_comparison"]["provisional_candidate"]
    selected_result = results[selected_id]
    release = _release_checks(selected_result["summary"])
    validation = {
        "schema_version": 2,
        "model_id": "round_control_v2",
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "fresh_locked_count": len(rows),
        "selection_rule": manifest["final_selection_rule"],
        "selected_candidate": selected_id,
        "candidate_results": results,
        "release_gate": release,
        "throat_impedance_used_in_selection": False,
        "evidence": rows,
    }
    _write_json(V2_ROOT / "validation_results.json", validation)
    if not release["passed"]:
        raise ValueError(
            "no v2 release: selected candidate failed registered limits")

    model = _read_json(
        V2_ROOT / "candidate_models" / f"{selected_id}.json")
    model["model_id"] = "round_control_v2"
    model["selected_candidate"] = selected_id
    model["fresh_validation"] = {
        "count": len(rows),
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "validation_sha256": _content_hash(validation),
    }
    model["interval_half_width"] = {
        name: max(
            model["interval_half_width"][name],
            selected_result["summary"][name]["p90_absolute"],
        )
        for name in DIAGNOSTICS
    }
    model["model_sha256"] = _content_hash({
        key: value for key, value in model.items() if key != "model_sha256"})
    index = _read_json(TRAINING_INDEX)
    V2_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(V2_MODEL_DIR / "model.json", model)
    _write_json(V2_MODEL_DIR / "validation.json", validation)
    _write_json(V2_MODEL_DIR / "training_index.json", index)
    _write_json(V2_MODEL_DIR / "provenance.json", {
        **model["provenance"],
        "model_sha256": model["model_sha256"],
        "validation_sha256": _content_hash(validation),
        "fresh_validation_response_sha256": {
            row["id"]: row["response_sha256"] for row in rows},
    })
    _write_json(V2_MODEL_DIR / "rules.json", {
        "schema_version": 2,
        "status": "placeholder",
        "rules": [],
        "reason": "diagnose/improve remain deferred",
    })
    card = f"""# Round Control v2

One unified portable quadratic response model for symmetric, square,
zero-extension round OS-SE horns over the complete 250–450 mm mouth and
30–50 degree coverage grid.

The model uses one global historical-evidence weight
({model['historical_weighting']['global_weight']:g}) and has no cell router or
companion production model. The primary and augmented v1 models remain audit
artifacts.

Fresh locked validation count: {len(rows)}.
Surface-score MAE: {selected_result['summary']['surface_score']['mae']:.4f}.
Surface-score p90 absolute error:
{selected_result['summary']['surface_score']['p90_absolute']:.4f}.

`throat_impedance_score` remains an independent experimental output. It was not
used to select this model and is not included in surface score.
"""
    (V2_MODEL_DIR / "model_card.md").write_text(card, encoding="utf-8")
    return validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    subparsers.add_parser("preflight")
    subparsers.add_parser("status")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--slots", type=int, default=2)
    subparsers.add_parser("finalize")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        result = prepare()
        print(f"freeze SHA-256: {result['freeze_sha256']}")
        print(f"fresh locked candidates: {result['validation_cell_count']}")
    elif args.command == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True))
    elif args.command == "status":
        print(json.dumps(status(), indent=2, sort_keys=True))
    elif args.command == "run":
        result = run(args.slots)
        print(f"status: {result['status']}")
    elif args.command == "finalize":
        result = finalize()
        print(f"selected candidate: {result['selected_candidate']}")
        print(f"release passed: {result['release_gate']['passed']}")


if __name__ == "__main__":
    main()
