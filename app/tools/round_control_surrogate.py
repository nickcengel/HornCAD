#!/usr/bin/env python3
"""Select and challenge a nonlinear round-control surrogate without new BEM."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .round_control_model import (
    DIAGNOSTICS, PREREGISTERED_DIAGNOSTICS, _content_hash,
    _summarize_errors,
)


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = (
    ROOT / "examples/control-decoupling/model_source/training_index.json")
CHALLENGE_PATH = (
    ROOT / "examples/round-control-v2-validation/validation_results.json")
OUTPUT_ROOT = ROOT / "examples/round-control-nonlinear-evaluation"
SELECTION_PATH = OUTPUT_ROOT / "development_selection.json"
RESULT_PATH = OUTPUT_ROOT / "challenge_results.json"
MODEL_DIR = ROOT / "models/round_control_baseline_v2"

ANGLES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)
FOLD_COUNT = 5
SCALES = np.asarray((0.2, 2.0, 4.0), dtype=float)
RELEASE_LIMITS = {
    "surface_score": {"mae": 1.75, "p90_absolute": 3.60},
    "mean_containment": {"p90_absolute": 0.12},
    "minus_six_db_rms_error": {"p90_absolute": 0.80},
    "outward_rise_violation": {"p90_absolute": 0.45},
    "profile_rms_error": {"p90_absolute": 0.18},
    "slice_energy_rms_departure": {"p90_absolute": 0.18},
}

# This candidate family and order are frozen by the selection artifact before
# challenge_results.json is read.
CANDIDATES = (
    {"id": "quadratic", "method": "quadratic"},
    {"id": "nearest", "method": "neighbor", "neighbors": 1},
    {"id": "idw_k4_p2", "method": "idw", "neighbors": 4, "power": 2.0},
    {"id": "idw_k8_p2", "method": "idw", "neighbors": 8, "power": 2.0},
    {"id": "idw_k12_p2", "method": "idw", "neighbors": 12, "power": 2.0},
    {"id": "local_affine_k12", "method": "local_affine", "neighbors": 12,
     "ridge": 0.01},
    {"id": "local_affine_k20", "method": "local_affine", "neighbors": 20,
     "ridge": 0.01},
    {"id": "quadratic_rbf_b0p5_r0p001", "method": "quadratic_rbf",
     "bandwidth": 0.5, "ridge": 0.001},
    {"id": "quadratic_rbf_b0p75_r0p001", "method": "quadratic_rbf",
     "bandwidth": 0.75, "ridge": 0.001},
    {"id": "quadratic_rbf_b1_r0p001", "method": "quadratic_rbf",
     "bandwidth": 1.0, "ridge": 0.001},
    {"id": "quadratic_rbf_b0p75_r0p01", "method": "quadratic_rbf",
     "bandwidth": 0.75, "ridge": 0.01},
    {"id": "quadratic_rbf_b1_r0p01", "method": "quadratic_rbf",
     "bandwidth": 1.0, "ridge": 0.01},
    {"id": "quadratic_rbf_b1p5_r0p01", "method": "quadratic_rbf",
     "bandwidth": 1.5, "ridge": 0.01},
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _development_rows() -> list[dict[str, Any]]:
    index = _read(INDEX_PATH)
    roles = {"fit", "locked_validation", "historical_challenge"}
    rows = [
        row for row in index["rows"]
        if row["role"] in roles
        and int(row["coverage_deg"]) in ANGLES
        and int(row["mouth_mm"]) in MOUTHS
    ]
    coordinates = {
        (row["coverage_deg"], row["mouth_mm"], row["length_factor"],
         row["k"], row["n"])
        for row in rows
    }
    if len(coordinates) != len(rows):
        raise ValueError("development evidence contains duplicate coordinates")
    return rows


def _x(row: dict[str, Any]) -> np.ndarray:
    return (
        np.asarray((row["length_factor"], row["k"], row["n"]), dtype=float)
        - np.asarray((1.0, 4.0, 8.0), dtype=float)
    ) / SCALES


def _basis(x: np.ndarray) -> np.ndarray:
    l, k, n = x
    return np.asarray((1.0, l, k, n, l*l, k*k, n*n, l*k, l*n, k*n))


def _fold(row: dict[str, Any]) -> int:
    digest = hashlib.sha256(
        str(row["coordinate_hash"]).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % FOLD_COUNT


def _blocked_fold(row: dict[str, Any]) -> int:
    """Spatial checkerboard audit; neighboring points commonly change folds."""
    x = _x(row)
    bins = np.floor((x + np.asarray((1.5, 1.5, 1.5))) * 2.0).astype(int)
    return int((bins[0] + 2*bins[1] + 3*bins[2]) % FOLD_COUNT)


def _diagnostic_scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    output = {}
    for name in DIAGNOSTICS:
        values = np.asarray([row["responses"][name] for row in rows])
        q25, q75 = np.percentile(values, (25, 75))
        output[name] = float(max(q75-q25, np.std(values)*0.25, 1e-6))
    return output


def _fit_cell(rows: list[dict[str, Any]],
              candidate: dict[str, Any]) -> dict[str, Any]:
    x = np.vstack([_x(row) for row in rows])
    y = np.asarray([
        [row["responses"][name] for name in DIAGNOSTICS]
        for row in rows
    ])
    model: dict[str, Any] = {
        "candidate": candidate,
        "x": x.tolist(),
        "y": y.tolist(),
        "evidence_ids": [row["id"] for row in rows],
    }
    if candidate["method"] in {"quadratic", "quadratic_rbf"}:
        design = np.vstack([_basis(item) for item in x])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        model["beta"] = beta.tolist()
    if candidate["method"] == "quadratic_rbf":
        residual = y - design @ beta
        bandwidth = float(candidate["bandwidth"])
        squared = np.sum((x[:, None, :] - x[None, :, :])**2, axis=2)
        kernel = np.exp(-0.5*squared/(bandwidth**2))
        ridge = float(candidate["ridge"])
        alpha = np.linalg.solve(
            kernel + ridge*np.eye(len(x)), residual)
        model.update({
            "alpha": alpha.tolist(),
        })
    return model


def fit(rows: list[dict[str, Any]],
        candidate: dict[str, Any]) -> dict[str, Any]:
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cell[(int(row["coverage_deg"]), int(row["mouth_mm"]))].append(row)
    expected = {(angle, mouth) for angle in ANGLES for mouth in MOUTHS}
    if set(by_cell) != expected:
        raise ValueError("training data do not cover all 25 cells")
    return {
        "schema_version": 1,
        "model_id": f"round_control_surrogate_{candidate['id']}",
        "model_family": "axisymmetric round-mouth zero-extension OS-SE",
        "diagnostics": list(DIAGNOSTICS),
        "control_scaling": {
            "center": [1.0, 4.0, 8.0],
            "scale": SCALES.tolist(),
        },
        "candidate": candidate,
        "cells": {
            f"{angle}deg-{mouth}mm": _fit_cell(cell_rows, candidate)
            for (angle, mouth), cell_rows in sorted(by_cell.items())
        },
    }


def _predict_cell(model: dict[str, Any], x: np.ndarray) -> np.ndarray:
    candidate = model["candidate"]
    centers = np.asarray(model["x"], dtype=float)
    values = np.asarray(model["y"], dtype=float)
    distances = np.linalg.norm(centers-x, axis=1)
    nearest = np.argsort(distances)
    exact = nearest[0]
    if distances[exact] < 1e-12:
        return values[exact]
    method = candidate["method"]
    if method == "quadratic":
        return _basis(x) @ np.asarray(model["beta"], dtype=float)
    if method == "neighbor":
        return values[exact]
    if method == "idw":
        chosen = nearest[:min(int(candidate["neighbors"]), len(nearest))]
        weights = 1.0 / np.maximum(
            distances[chosen], 1e-9)**float(candidate["power"])
        return np.average(values[chosen], axis=0, weights=weights)
    if method == "local_affine":
        chosen = nearest[:min(int(candidate["neighbors"]), len(nearest))]
        delta = centers[chosen]-x
        design = np.column_stack((np.ones(len(chosen)), delta))
        weights = np.exp(-0.5*distances[chosen]**2)
        root = np.sqrt(weights)
        weighted = design*root[:, None]
        ridge = float(candidate["ridge"])
        penalty = np.diag((0.0, ridge, ridge, ridge))
        beta = np.linalg.solve(
            weighted.T@weighted+penalty,
            weighted.T@(values[chosen]*root[:, None]))
        return beta[0]
    if method == "quadratic_rbf":
        bandwidth = float(candidate["bandwidth"])
        kernel = np.exp(
            -0.5*np.sum((centers-x)**2, axis=1)/(bandwidth**2))
        return (
            _basis(x) @ np.asarray(model["beta"], dtype=float)
            + kernel @ np.asarray(model["alpha"], dtype=float)
        )
    raise ValueError(f"unknown method {method}")


def predict(model: dict[str, Any],
            row: dict[str, Any]) -> dict[str, float]:
    cell_id = (
        f"{int(row['coverage_deg'])}deg-{int(row['mouth_mm'])}mm")
    values = _predict_cell(model["cells"][cell_id], _x(row))
    return {
        name: float(value) for name, value in zip(DIAGNOSTICS, values)
    }


def _error_rows(model: dict[str, Any],
                rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        predicted = predict(model, row)
        observed = row["responses"]
        output.append({
            "id": row["id"],
            "coverage_deg": row["coverage_deg"],
            "mouth_mm": row["mouth_mm"],
            "length_factor": row["length_factor"],
            "k": row["k"],
            "n": row["n"],
            "observed": observed,
            "predicted": predicted,
            "error": {
                name: predicted[name]-observed[name]
                for name in DIAGNOSTICS
            },
        })
    return output


def _normalized(errors: list[dict[str, Any]],
                scales: dict[str, float]) -> dict[str, float]:
    per_row = [
        np.mean([
            abs(row["error"][name])/scales[name]
            for name in PREREGISTERED_DIAGNOSTICS
        ])
        for row in errors
    ]
    by_cell: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(errors, per_row):
        by_cell[
            f"{int(row['coverage_deg'])}deg-{int(row['mouth_mm'])}mm"
        ].append(float(value))
    cell_means = {
        key: float(np.mean(values)) for key, values in sorted(by_cell.items())
    }
    mean = float(np.mean(per_row))
    worst = max(cell_means.values())
    return {
        "mean_equal_diagnostic_normalized_mae": mean,
        "worst_cell_equal_diagnostic_normalized_mae": worst,
        "selection_loss": mean+0.25*worst,
    }


def _cross_validate(rows: list[dict[str, Any]],
                    candidate: dict[str, Any],
                    scales: dict[str, float],
                    fold_function) -> dict[str, Any]:
    errors = []
    fold_counts = []
    for fold_number in range(FOLD_COUNT):
        training = [
            row for row in rows if fold_function(row) != fold_number]
        withheld = [
            row for row in rows if fold_function(row) == fold_number]
        model = fit(training, candidate)
        fold_errors = _error_rows(model, withheld)
        errors.extend(fold_errors)
        fold_counts.append({
            "fold": fold_number,
            "training": len(training),
            "withheld": len(withheld),
        })
    return {
        "summary": _summarize_errors(errors),
        "normalized": _normalized(errors, scales),
        "folds": fold_counts,
        "row_count": len(errors),
    }


def select() -> dict[str, Any]:
    rows = _development_rows()
    scales = _diagnostic_scales(rows)
    comparison = {}
    for candidate in CANDIDATES:
        random_cv = _cross_validate(rows, candidate, scales, _fold)
        blocked_cv = _cross_validate(rows, candidate, scales, _blocked_fold)
        comparison[candidate["id"]] = {
            "candidate": candidate,
            "coordinate_grouped_cv": random_cv,
            "spatial_checkerboard_audit": blocked_cv,
            "selection_loss": (
                random_cv["normalized"]["selection_loss"]
                + 0.25*blocked_cv["normalized"]["selection_loss"]
            ),
        }
    selected = min(
        comparison, key=lambda key: comparison[key]["selection_loss"])
    result = {
        "schema_version": 1,
        "status": "development-selected-challenge-unread",
        "development_row_count": len(rows),
        "development_coordinate_count": len(rows),
        "candidate_family": list(CANDIDATES),
        "diagnostic_scales": scales,
        "selection_rule": (
            "minimum coordinate-grouped selection loss plus 0.25 times "
            "spatial-checkerboard selection loss; six radiation diagnostics "
            "only; throat impedance excluded"),
        "release_rule": (
            "challenge must beat frozen quadratic by at least 20% on surface "
            "score MAE, p90 absolute error, and equal-diagnostic normalized "
            "MAE; no radiation diagnostic p90 may worsen by more than 10%; "
            "original v2 release gates are reported separately"),
        "comparison": comparison,
        "selected_candidate": selected,
        "challenge_outcomes_loaded": False,
        "throat_impedance_used_in_selection": False,
        "training_index_sha256": _content_hash(_read(INDEX_PATH)),
    }
    result["selection_sha256"] = _content_hash(result)
    _write(SELECTION_PATH, result)
    return result


def _challenge_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validation = _read(CHALLENGE_PATH)
    selected_quadratic = validation["selected_candidate"]
    rows = validation["candidate_results"][selected_quadratic]["rows"]
    challenge = []
    for row in rows:
        challenge.append({
            key: row[key] for key in (
                "id", "coverage_deg", "mouth_mm", "length_factor", "k", "n",
                "observed",
            )
        })
        challenge[-1]["responses"] = challenge[-1].pop("observed")
    return challenge, validation


def _release_checks(summary: dict[str, Any]) -> dict[str, Any]:
    checks = {}
    for name, metrics in RELEASE_LIMITS.items():
        for metric, limit in metrics.items():
            value = float(summary[name][metric])
            checks[f"{name}.{metric}"] = {
                "value": value, "limit": limit, "passed": value <= limit,
            }
    return {
        "checks": checks,
        "passed": all(item["passed"] for item in checks.values()),
    }


def challenge() -> dict[str, Any]:
    selection = _read(SELECTION_PATH)
    expected = selection["selection_sha256"]
    actual = _content_hash({
        key: value for key, value in selection.items()
        if key != "selection_sha256"
    })
    if expected != actual or selection["challenge_outcomes_loaded"]:
        raise ValueError("development selection is not a valid outcome-free freeze")
    candidate = next(
        item for item in CANDIDATES
        if item["id"] == selection["selected_candidate"])
    development = _development_rows()
    model = fit(development, candidate)
    challenge_rows, frozen = _challenge_rows()
    errors = _error_rows(model, challenge_rows)
    summary = _summarize_errors(errors)
    normalized = _normalized(errors, selection["diagnostic_scales"])

    quadratic_id = frozen["selected_candidate"]
    quadratic = frozen["candidate_results"][quadratic_id]
    quadratic_summary = quadratic["summary"]
    quadratic_normalized = quadratic["normalized"]
    improvements = {
        "surface_score_mae": (
            1-summary["surface_score"]["mae"]
            / quadratic_summary["surface_score"]["mae"]),
        "surface_score_p90": (
            1-summary["surface_score"]["p90_absolute"]
            / quadratic_summary["surface_score"]["p90_absolute"]),
        "normalized_mae": (
            1-normalized["mean_equal_diagnostic_normalized_mae"]
            / quadratic_normalized[
                "mean_equal_diagnostic_normalized_mae"]),
    }
    p90_ratios = {
        name: (
            summary[name]["p90_absolute"]
            / max(quadratic_summary[name]["p90_absolute"], 1e-12)
        )
        for name in PREREGISTERED_DIAGNOSTICS
    }
    material_improvement = (
        all(value >= 0.20 for value in improvements.values())
        and all(value <= 1.10 for value in p90_ratios.values())
    )
    gates = _release_checks(summary)
    release = material_improvement
    result = {
        "schema_version": 1,
        "model_id": "round_control_baseline_v2",
        "selected_candidate": candidate["id"],
        "selection_sha256": expected,
        "challenge_count": len(challenge_rows),
        "summary": summary,
        "normalized": normalized,
        "rows": errors,
        "frozen_quadratic_candidate": quadratic_id,
        "frozen_quadratic_summary": quadratic_summary,
        "frozen_quadratic_normalized": quadratic_normalized,
        "relative_improvements": improvements,
        "radiation_p90_ratios_vs_quadratic": p90_ratios,
        "material_improvement_rule_passed": material_improvement,
        "original_v2_release_gates": gates,
        "release": release,
        "throat_impedance_used_in_release": False,
    }
    _write(RESULT_PATH, result)
    if release:
        model["model_id"] = "round_control_baseline_v2"
        model["selection_sha256"] = expected
        model["challenge_results_sha256"] = _content_hash(result)
        model["interval_half_width"] = {
            name: summary[name]["p90_absolute"] for name in DIAGNOSTICS
        }
        model["model_sha256"] = _content_hash(model)
        _write(MODEL_DIR / "model.json", model)
        _write(MODEL_DIR / "validation.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("select", "challenge"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = select() if args.command == "select" else challenge()
    if args.command == "select":
        print(f"selected: {result['selected_candidate']}")
        print(f"selection SHA-256: {result['selection_sha256']}")
    else:
        print(f"release: {result['release']}")
        print(json.dumps(result["relative_improvements"], indent=2))


if __name__ == "__main__":
    main()
