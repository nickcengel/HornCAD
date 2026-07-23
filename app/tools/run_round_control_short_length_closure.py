#!/usr/bin/env python3
"""Prepare, run, and analyze the capped short-length closure study."""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import json
from pathlib import Path
from typing import Any

import yaml

from .round_control_model import (
    _content_hash,
    _digest_file,
    _rescore,
    _validate_npz,
)
from .round_control_v2 import _source_project
from .run_bem_search import materialize_candidate, run_search
from .run_stage_aware_bem_queue import run_queue, validate_queue


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/round-control-short-length-closure"
RIDGE_ROOT = ROOT / "examples/round-control-ridge-closure"
RIDGE_MANIFEST = RIDGE_ROOT / "manifest.json"
RIDGE_RESULTS = RIDGE_ROOT / "results.json"
TRAINING_INDEX = (
    ROOT / "examples/control-decoupling/model_source/training_index.json"
)
HEURISTICS = ROOT / "models/round_control_heuristics_v1/heuristics.json"

CELLS = ((35, 300), (40, 250), (45, 250))
INITIAL_MULTIPLIER = 0.8
CONDITIONAL_MULTIPLIER = 0.7
HARD_CANDIDATE_CAP = 6
QUEUE_WORKERS = 4
NUMCALC_PROCESSES = 20


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _ridge_group(coverage: int, mouth: int) -> dict[str, Any]:
    manifest = _read_json(RIDGE_MANIFEST)
    matches = [
        group for group in manifest["groups"]
        if int(group["coverage_deg"]) == coverage
        and int(group["mouth_mm"]) == mouth
    ]
    if len(matches) != 1:
        raise ValueError(f"missing ridge group at {coverage}/{mouth}")
    group = matches[0]
    if float(group["k"]) != 1.0 or float(group["n"]) != 8.0:
        raise ValueError(f"unexpected short-ridge controls at {coverage}/{mouth}")
    return group


def _coordinate(coverage: int, mouth: int,
                multiplier: float) -> dict[str, Any]:
    group = _ridge_group(coverage, mouth)
    length = round(float(group["target_s_length_mm"]) * multiplier, 3)
    label = str(multiplier).replace(".", "p")
    return {
        "id": f"short-closure-{coverage}deg-{mouth}mm-K1-N8-Lx{label}",
        "coverage_deg": coverage,
        "mouth_mm": mouth,
        "k": 1.0,
        "n": 8.0,
        "length_multiplier": multiplier,
        "length_mm": length,
        "length_factor": length / float(group["reference_length_mm"]),
        "target_s": float(group["target_s"]),
        "derived_s": _s_at_length(mouth, coverage, length, 1.0, 8.0),
    }


def _s_at_length(mouth: float, coverage: float, length: float,
                 k: float, n: float) -> float:
    from app.design_api import RoundControlHeuristics

    return RoundControlHeuristics._s_at_length(
        mouth, coverage, length, k, n)


def _directory(stage: str, coordinate: dict[str, Any]) -> Path:
    return (
        STUDY_ROOT / "searches" / stage
        / f"{coordinate['coverage_deg']}deg-{coordinate['mouth_mm']}mm"
    )


def _search_document(coordinate: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, float]]:
    coverage = float(coordinate["coverage_deg"])
    values = {
        "length_mm": float(coordinate["length_mm"]),
        "extension_mm": 0.0,
        "osse_coverage_h_deg": coverage,
        "osse_coverage_v_deg": coverage,
        "k_h": 1.0,
        "k_v": 1.0,
        "n_h": 8.0,
        "n_v": 8.0,
    }
    bounds = {
        key: [
            value-max(1e-6, abs(value)*1e-9),
            value+max(1e-6, abs(value)*1e-9),
        ]
        for key, value in values.items()
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
        "initial_candidates": 1,
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.049, 4.001],
        "sampling_stability_points": 2.0,
        "confirmation_points_per_octave": 16.0,
        "adaptive_pruning": {"enabled": False},
        "bounds": bounds,
        # The search schema requires a nonempty pool. This exact duplicate of
        # the seed cannot authorize a second evaluation under max_evaluations=1.
        "initial_pool": [{
            "label": f"{coordinate['id']}-schema-seed-duplicate",
            "values": values,
        }],
        "solver": {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 10,
        },
        "round_control_short_length_closure": {
            "role": "measured-heuristic-short-length-closure",
            "coordinate_id": coordinate["id"],
            "k_hard_minimum": 1.0,
            "throat_impedance_used_in_score": False,
        },
    }
    return {"bem_candidate_search": search}, values


def _prepare_stage(stage: str,
                   coordinates: list[dict[str, Any]]) -> dict[str, Any]:
    if stage not in {"initial", "conditional"}:
        raise ValueError(f"unknown stage {stage}")
    if not coordinates:
        raise ValueError("cannot prepare an empty stage")
    index = _read_json(TRAINING_INDEX)
    inputs = {}
    for coordinate in coordinates:
        coverage = int(coordinate["coverage_deg"])
        mouth = int(coordinate["mouth_mm"])
        directory = _directory(stage, coordinate)
        source = yaml.safe_load(
            _source_project(index, coverage, mouth).read_text(encoding="utf-8")
        )
        document, values = _search_document(coordinate)
        project, _ = materialize_candidate(
            copy.deepcopy(source), values, document["bem_candidate_search"])
        _write_yaml(directory / "project.yaml", project)
        _write_yaml(directory / "search.yaml", document)
        inputs[coordinate["id"]] = {
            "project": str((directory / "project.yaml").relative_to(ROOT)),
            "project_sha256": _digest_file(directory / "project.yaml"),
            "search": str((directory / "search.yaml").relative_to(ROOT)),
            "search_sha256": _digest_file(directory / "search.yaml"),
        }
    manifest = {
        "schema_version": 1,
        "study_id": "round-control-short-length-closure-v1",
        "stage": stage,
        "status": "frozen-not-run",
        "hard_study_candidate_cap": HARD_CANDIDATE_CAP,
        "candidate_count": len(coordinates),
        "coordinates": coordinates,
        "inputs": inputs,
        "ridge_manifest_sha256": _digest_file(RIDGE_MANIFEST),
        "ridge_results_sha256": _digest_file(RIDGE_RESULTS),
        "heuristics_sha256": _digest_file(HEURISTICS),
        "scheduler": {
            "type": "stage-aware-bem-queue",
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
            "search_sharding": "one-candidate-per-search",
        },
        "conditional_rule": (
            "add Lx0.7 only where measured Lx0.8 surface score exceeds "
            "the retained Lx0.9 score"
        ),
        "throat_impedance": {
            "retained": True,
            "included_in_surface_score": False,
            "included_in_conditional_decision": False,
        },
    }
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(STUDY_ROOT / f"{stage}_manifest.json", manifest)
    return manifest


def prepare_initial() -> dict[str, Any]:
    coordinates = [
        _coordinate(coverage, mouth, INITIAL_MULTIPLIER)
        for coverage, mouth in CELLS
    ]
    return _prepare_stage("initial", coordinates)


def _verify_stage(stage: str) -> dict[str, Any]:
    path = STUDY_ROOT / f"{stage}_manifest.json"
    manifest = _read_json(path)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError(f"{stage} manifest freeze hash changed")
    if _digest_file(RIDGE_RESULTS) != manifest["ridge_results_sha256"]:
        raise ValueError("ridge results changed")
    for coordinate in manifest["coordinates"]:
        item = manifest["inputs"][coordinate["id"]]
        for kind in ("project", "search"):
            path = ROOT / item[kind]
            if _digest_file(path) != item[f"{kind}_sha256"]:
                raise ValueError(f"changed {stage} input: {path}")
    return manifest


def _search_paths(manifest: dict[str, Any]) -> list[Path]:
    return [
        ROOT / manifest["inputs"][coordinate["id"]]["search"]
        for coordinate in manifest["coordinates"]
    ]


def preflight(stage: str) -> dict[str, Any]:
    manifest = _verify_stage(stage)
    paths = _search_paths(manifest)
    scheduler = validate_queue(
        paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    rows = []
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        if state.get("status") != "preflight":
            raise ValueError(f"preflight failed: {path}")
        candidates = state.get("candidates", [])
        if len(candidates) != 1 or candidates[0].get("status") != "preflight":
            raise ValueError(f"wrong one-candidate preflight: {path}")
        rows.append({
            "search": str(path.relative_to(ROOT)),
            "candidate_count": 1,
        })
    result = {"stage": stage, "scheduler": scheduler, "searches": rows}
    _write_json(STUDY_ROOT / f"{stage}_preflight.json", result)
    return result


def run(stage: str) -> dict[str, Any]:
    manifest = _verify_stage(stage)
    preflight_path = STUDY_ROOT / f"{stage}_preflight.json"
    if not preflight_path.is_file():
        raise ValueError(f"{stage} preflight has not run")
    return run_queue(
        _search_paths(manifest),
        STUDY_ROOT / f"{stage}_runtime.json",
        queue_workers=QUEUE_WORKERS,
        numcalc_processes=NUMCALC_PROCESSES,
    )


def _ridge_score(coverage: int, mouth: int,
                 multiplier: float) -> float:
    result = _read_json(RIDGE_RESULTS)
    cell = result["cells"][f"{coverage}deg-{mouth}mm"]
    return float(cell["scores_by_length_multiplier"][f"{multiplier:.1f}"])


def _measured(stage: str) -> list[dict[str, Any]]:
    manifest = _verify_stage(stage)
    rows = []
    for coordinate in manifest["coordinates"]:
        directory = _directory(stage, coordinate)
        response = directory / "candidates/candidate-000/bem/responses.npz"
        _, _ = _validate_npz(response)
        values, impedance, delta = _rescore(response)
        if delta > 1e-9:
            raise ValueError(
                f"{coordinate['id']}: stored diagnostics differ by {delta:g}")
        rows.append({
            **coordinate,
            "stage": stage,
            "responses": {**values, **impedance},
            "response_path": str(response.relative_to(ROOT)),
            "response_sha256": _digest_file(response),
        })
    return rows


def prepare_conditional() -> dict[str, Any]:
    initial = _measured("initial")
    coordinates = [
        _coordinate(
            int(row["coverage_deg"]),
            int(row["mouth_mm"]),
            CONDITIONAL_MULTIPLIER,
        )
        for row in initial
        if float(row["responses"]["surface_score"]) > _ridge_score(
            int(row["coverage_deg"]), int(row["mouth_mm"]), 0.9)
    ]
    decision = {
        "schema_version": 1,
        "rule": "schedule Lx0.7 only when Lx0.8 score exceeds Lx0.9",
        "initial_response_hashes": {
            row["id"]: row["response_sha256"] for row in initial
        },
        "selected_cells": [
            {
                "coverage_deg": row["coverage_deg"],
                "mouth_mm": row["mouth_mm"],
            }
            for row in initial
            if float(row["responses"]["surface_score"]) > _ridge_score(
                int(row["coverage_deg"]), int(row["mouth_mm"]), 0.9)
        ],
        "candidate_count": len(coordinates),
    }
    decision["content_sha256"] = _content_hash(decision)
    _write_json(STUDY_ROOT / "conditional_decision.json", decision)
    if not coordinates:
        return decision
    if len(initial)+len(coordinates) > HARD_CANDIDATE_CAP:
        raise ValueError("conditional stage exceeds hard candidate cap")
    manifest = _prepare_stage("conditional", coordinates)
    return {"decision": decision, "manifest": manifest}


def analyze() -> dict[str, Any]:
    initial = _measured("initial")
    conditional_manifest = STUDY_ROOT / "conditional_manifest.json"
    conditional = (
        _measured("conditional") if conditional_manifest.is_file() else [])
    by_cell = {}
    for coverage, mouth in CELLS:
        initial_row = next(
            row for row in initial
            if row["coverage_deg"] == coverage and row["mouth_mm"] == mouth)
        conditional_rows = [
            row for row in conditional
            if row["coverage_deg"] == coverage and row["mouth_mm"] == mouth
        ]
        scores = {
            "0.9": _ridge_score(coverage, mouth, 0.9),
            "1.0": _ridge_score(coverage, mouth, 1.0),
            "0.8": float(initial_row["responses"]["surface_score"]),
        }
        if conditional_rows:
            scores["0.7"] = float(
                conditional_rows[0]["responses"]["surface_score"])
            bracketed = scores["0.8"] >= max(scores["0.7"], scores["0.9"])
            preferred = max(("0.7", "0.8", "0.9"), key=scores.get)
        else:
            bracketed = scores["0.9"] >= max(scores["0.8"], scores["1.0"])
            preferred = max(("0.8", "0.9", "1.0"), key=scores.get)
        by_cell[f"{coverage}deg-{mouth}mm"] = {
            "k": 1.0,
            "n": 8.0,
            "scores_by_length_multiplier": scores,
            "bracketed": bracketed,
            "preferred_length_multiplier": float(preferred),
            "status": "bracketed" if bracketed else "short-boundary-at-cap",
        }
    evidence = initial+conditional
    result = {
        "schema_version": 1,
        "study_id": "round-control-short-length-closure-v1",
        "candidate_count": len(evidence),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "cells": by_cell,
        "evidence": sorted(evidence, key=lambda row: row["id"]),
        "summary": {
            "tested_cells": len(CELLS),
            "bracketed_cells": sum(
                row["bracketed"] for row in by_cell.values()),
            "short_boundary_cells": sum(
                not row["bracketed"] for row in by_cell.values()),
        },
        "scheduler": {
            "type": "stage-aware-bem-queue",
            "search_sharding": "one-candidate-per-search",
            "numcalc_process_capacity": NUMCALC_PROCESSES,
        },
        "throat_impedance_used_in_surface_score": False,
        "throat_impedance_used_in_decisions": False,
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "results.json", result)
    return result


def status() -> dict[str, Any]:
    rows = []
    for stage in ("initial", "conditional"):
        path = STUDY_ROOT / f"{stage}_manifest.json"
        if not path.is_file():
            continue
        manifest = _verify_stage(stage)
        for coordinate, search in zip(
                manifest["coordinates"], _search_paths(manifest)):
            state_path = search.parent / "search_state.json"
            state = _read_json(state_path) if state_path.is_file() else {}
            complete = sum(
                item.get("status") == "complete"
                for item in state.get("candidates", []))
            rows.append({
                "id": coordinate["id"],
                "stage": stage,
                "status": state.get("status", "not-started"),
                "complete_candidates": complete,
            })
    return {
        "summary": dict(Counter(row["status"] for row in rows)),
        "complete_candidates": sum(
            row["complete_candidates"] for row in rows),
        "scheduled_candidates": len(rows),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "prepare-initial", "preflight", "run", "prepare-conditional",
        "analyze", "status",
    ))
    parser.add_argument(
        "--stage", choices=("initial", "conditional"), default="initial")
    args = parser.parse_args()
    if args.command == "prepare-initial":
        result = prepare_initial()
    elif args.command == "preflight":
        result = preflight(args.stage)
    elif args.command == "run":
        result = run(args.stage)
    elif args.command == "prepare-conditional":
        result = prepare_conditional()
    elif args.command == "analyze":
        result = analyze()
    else:
        result = status()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
