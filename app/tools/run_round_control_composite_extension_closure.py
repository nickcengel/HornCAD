#!/usr/bin/env python3
"""Run the fixed eight-case 6° composite extension/S closure."""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import yaml

from .round_control_model import _validate_npz
from .run_bem_search import materialize_candidate, run_search
from .run_extension_throat_angle_study import _search_document
from .run_stage_aware_bem_queue import run_queue, validate_queue


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/round-control-composite-extension-closure"
MAP = ROOT / "examples/round-control-composite-extension-map/map.json"
MANIFEST = STUDY_ROOT / "manifest.json"
ANGLE_ADDENDUM_MANIFEST = STUDY_ROOT / "angle_addendum_manifest.json"
LOWER_ANGLE_MANIFEST = STUDY_ROOT / "lower_angle_manifest.json"
QUEUE_WORKERS = 4
NUMCALC_PROCESSES = 20
ANGLE_ADDENDUM_CELLS = (
    (45, 250),
    (45, 450),
    (50, 250),
    (50, 450),
)
LOWER_ANGLE_CELLS = tuple(
    (coverage, mouth)
    for coverage in (30, 35, 40)
    for mouth in (250, 300, 350, 400, 450)
)
DESIGN = {
    "45deg-250mm": {
        "extension_mm": 60,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "45deg-350mm": {
        "extension_mm": 40,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "45deg-400mm": {
        "extension_mm": 40,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "50deg-250mm": {
        "extension_mm": 60,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "50deg-300mm": {
        "extension_mm": 20,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "50deg-350mm": {
        "extension_mm": 40,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "50deg-400mm": {
        "extension_mm": 40,
        "modes": ("ordinary", "length-s-matched", "k-s-matched"),
    },
    "50deg-450mm": {
        "extension_mm": 60,
        "modes": ("length-s-matched", "k-s-matched"),
    },
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _parent_project(parent: dict[str, Any]) -> Path:
    response = ROOT / parent["source_path"]
    project = response.parents[1] / "project.yaml"
    if not project.is_file():
        raise FileNotFoundError(project)
    return project


def _candidate_directory(row: dict[str, Any]) -> Path:
    return STUDY_ROOT / "searches" / row["id"]


def _legacy_angle_parent(coverage: int, mouth: int) -> tuple[
        Path, dict[str, Any], dict[str, Any]]:
    search = (
        ROOT / "examples/extension-throat-angle-heuristics/searches"
        / "primary-development" / f"{coverage}deg" / f"{mouth}mm"
        / "primary-A6-E40"
    )
    state = _read(search / "search_state.json")
    if state.get("status") != "complete":
        raise ValueError(f"incomplete legacy angle parent: {search}")
    record = state["candidates"][0]
    source = yaml.safe_load(
        (search / "project.yaml").read_text(encoding="utf-8"))
    return search, source, record


def _materialized(
    source: dict[str, Any],
    parent: dict[str, Any],
    coverage: int,
    mouth: int,
    extension: int,
    length: float,
    k: float,
    candidate_id: str,
    throat_angle_deg: int = 6,
    stage: str = "s-matched-closure",
    parent_role: str = "composite-winner",
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = {
        "id": candidate_id,
        "stage": stage,
        "parent_role": parent_role,
        "coverage_deg": coverage,
        "round_mouth_diameter_mm": mouth,
        "throat_angle_deg": throat_angle_deg,
        "extension_mm": extension,
        "length_mm": length,
    }
    source["horncad_config"]["global"]["throat_angle_deg"] = float(
        throat_angle_deg)
    parent_values = {
        "id": parent["id"],
        "length_mm": parent["length_mm"],
        "k": k,
        "n": parent["n"],
        "s": parent["s"],
    }
    document, values = _search_document(row, parent_values)
    search = document["bem_candidate_search"]
    search["extension_throat_angle_study"] = {
        "study_id": "round-control-composite-extension-closure-v1",
        "coordinate_id": candidate_id,
        "parent_id": parent["id"],
        "throat_angle_deg": throat_angle_deg,
        "extension_mm": extension,
        "ranking": "composite_score_v1.0",
    }
    project, _ = materialize_candidate(
        copy.deepcopy(source), values, search)
    return project, document


def _s_at_length(
    source: dict[str, Any],
    parent: dict[str, Any],
    coverage: int,
    mouth: int,
    extension: int,
    length: float,
) -> float:
    project, _ = _materialized(
        source, parent, coverage, mouth, extension, length,
        float(parent["k"]), "s-solver")
    return float(project["horncad_config"]["horizontal_basis"]["solved_s"])


def _solve_length_for_s(
    source: dict[str, Any],
    parent: dict[str, Any],
    coverage: int,
    mouth: int,
    extension: int,
) -> float:
    target = float(parent["s"])
    center = float(parent["length_mm"])
    low, high = center*0.5, center*2.0
    low_s = _s_at_length(
        source, parent, coverage, mouth, extension, low)
    high_s = _s_at_length(
        source, parent, coverage, mouth, extension, high)
    if not min(low_s, high_s) <= target <= max(low_s, high_s):
        raise ValueError(
            f"{coverage}/{mouth}: S={target:g} not bracketed by length")
    for _ in range(80):
        middle = (low+high)/2.0
        middle_s = _s_at_length(
            source, parent, coverage, mouth, extension, middle)
        if (low_s-target)*(middle_s-target) <= 0:
            high, high_s = middle, middle_s
        else:
            low, low_s = middle, middle_s
    return (low+high)/2.0


def _solve_k_for_s(
    source: dict[str, Any],
    parent: dict[str, Any],
    coverage: int,
    mouth: int,
    extension: int,
) -> float:
    target = float(parent["s"])
    length = float(parent["length_mm"])

    def at(k: float) -> float:
        project, _ = _materialized(
            source, parent, coverage, mouth, extension, length, k, "k-solver")
        return float(
            project["horncad_config"]["horizontal_basis"]["solved_s"])

    low, high = 1.0, 7.0
    low_s, high_s = at(low), at(high)
    if not min(low_s, high_s) <= target <= max(low_s, high_s):
        raise ValueError(
            f"{coverage}/{mouth}: S={target:g} not bracketed by K=1..7")
    for _ in range(80):
        middle = (low+high)/2.0
        middle_s = at(middle)
        if (low_s-target)*(middle_s-target) <= 0:
            high, high_s = middle, middle_s
        else:
            low, low_s = middle, middle_s
    return (low+high)/2.0


def prepare() -> dict[str, Any]:
    if MANIFEST.exists():
        raise FileExistsError(MANIFEST)
    map_result = _read(MAP)
    expected = map_result["content_sha256"]
    actual = _content_hash({
        key: value for key, value in map_result.items()
        if key != "content_sha256"
    })
    if actual != expected:
        raise ValueError("composite extension map content hash is stale")
    coordinates = []
    inputs = {}
    for cell_id, design in DESIGN.items():
        extension = int(design["extension_mm"])
        cell = map_result["cells"][cell_id]
        parent = cell["zero_extension_winner"]
        coverage = int(cell["coverage_deg"])
        mouth = int(cell["mouth_mm"])
        source_path = _parent_project(parent)
        source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        matched_length = _solve_length_for_s(
            source, parent, coverage, mouth, extension)
        matched_k = _solve_k_for_s(
            source, parent, coverage, mouth, extension)
        for mode in design["modes"]:
            length = (
                matched_length if mode == "length-s-matched"
                else float(parent["length_mm"])
            )
            k = (
                matched_k if mode == "k-s-matched"
                else float(parent["k"])
            )
            candidate_id = (
                f"composite-ext-{coverage}deg-{mouth}mm-"
                f"E{extension}-{mode}")
            project, search = _materialized(
                source, parent, coverage, mouth, extension,
                length, k, candidate_id)
            derived_s = float(
                project["horncad_config"]["horizontal_basis"]["solved_s"])
            if mode != "ordinary" and not math.isclose(
                    derived_s, float(parent["s"]), abs_tol=1e-9):
                raise ValueError(f"{candidate_id}: S match failed")
            directory = _candidate_directory({"id": candidate_id})
            project_path = directory / "project.yaml"
            search_path = directory / "search.yaml"
            _write_yaml(project_path, project)
            _write_yaml(search_path, search)
            coordinates.append({
                "id": candidate_id,
                "cell": cell_id,
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "throat_angle_deg": 6,
                "extension_mm": extension,
                "mode": mode,
                "length_mm": float(length),
                "profile_plus_extension_length_mm":
                    float(length+extension),
                "k": float(k),
                "n": float(parent["n"]),
                "derived_s": derived_s,
                "target_parent_s": float(parent["s"]),
                "parent_id": parent["id"],
                "parent_length_mm": float(parent["length_mm"]),
                "parent_surface_score_v2_3":
                    float(parent["surface_score_v2_3"]),
                "parent_throat_impedance_score_v2_3_0":
                    float(parent["throat_impedance_score_v2_3_0"]),
                "parent_composite_score_v1_0":
                    float(parent["composite_score_v1_0"]),
                "parent_response_sha256": parent["response_sha256"],
                "parent_source_path": parent["source_path"],
            })
            inputs[candidate_id] = {
                "project": str(project_path.relative_to(ROOT)),
                "project_sha256": _file_hash(project_path),
                "search": str(search_path.relative_to(ROOT)),
                "search_sha256": _file_hash(search_path),
            }
    if len(coordinates) != 23:
        raise ValueError("closure must contain exactly 23 candidates")
    manifest = {
        "schema_version": 1,
        "study_id": "round-control-composite-extension-closure-v1",
        "status": "prepared-not-run",
        "candidate_count": len(coordinates),
        "hard_candidate_cap": 24,
        "ranking": "composite_score_v1.0",
        "throat_angle_deg": 6,
        "scheduler": {
            "type": "stage-aware",
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
        },
        "source_map": str(MAP.relative_to(ROOT)),
        "source_map_sha256": _file_hash(MAP),
        "source_map_content_sha256": map_result["content_sha256"],
        "coordinates": coordinates,
        "inputs": inputs,
    }
    manifest["coordinate_sha256"] = _content_hash(coordinates)
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(MANIFEST, manifest)
    refresh_index()
    return manifest


def prepare_angle_addendum() -> dict[str, Any]:
    """Prepare four A8 bridge points against exact legacy A6/A12 pairs."""
    if ANGLE_ADDENDUM_MANIFEST.exists():
        raise FileExistsError(ANGLE_ADDENDUM_MANIFEST)
    coordinates = []
    inputs = {}
    for coverage, mouth in ANGLE_ADDENDUM_CELLS:
        parent_search, source, record = _legacy_angle_parent(
            coverage, mouth)
        values = record["values"]
        candidate_id = (
            f"composite-ext-{coverage}deg-{mouth}mm-E40-angle8-bridge")
        parent = {
            "id": (
                f"legacy-primary-{coverage}deg-{mouth}mm-A6-E40"),
            "length_mm": float(values["length_mm"]),
            "k": float(values["k_h"]),
            "n": float(values["n_h"]),
            "s": float(record["derived"]["s_h"]),
        }
        row = {
            "id": candidate_id,
            "stage": "angle-response-addendum",
            "parent_role": "legacy-primary-A6",
            "coverage_deg": coverage,
            "round_mouth_diameter_mm": mouth,
            "throat_angle_deg": 8,
            "extension_mm": 40,
        }
        source["horncad_config"]["global"]["throat_angle_deg"] = 8.0
        document, candidate_values = _search_document(row, parent)
        search = document["bem_candidate_search"]
        search["extension_throat_angle_study"].update({
            "study_id": "round-control-composite-extension-closure-v1",
            "ranking": "composite_score_v1.0",
            "purpose": "A8 bridge within an exact A6/A12 angle pair",
        })
        project, _ = materialize_candidate(
            copy.deepcopy(source), candidate_values, search)
        directory = _candidate_directory({"id": candidate_id})
        project_path = directory / "project.yaml"
        search_path = directory / "search.yaml"
        _write_yaml(project_path, project)
        _write_yaml(search_path, document)
        response = parent_search / record["response_archive"]
        report = parent_search / record["report_file"]
        surface = record["surface_diagnostics"]["score"]
        impedance = record["throat_impedance_diagnostics"]
        composite = record["composite_diagnostics"]
        derived_s = float(
            project["horncad_config"]["horizontal_basis"]["solved_s"])
        coordinates.append({
            "id": candidate_id,
            "cell": f"{coverage}deg-{mouth}mm",
            "coverage_deg": coverage,
            "mouth_mm": mouth,
            "throat_angle_deg": 8,
            "extension_mm": 40,
            "mode": "angle8-bridge",
            "length_mm": float(values["length_mm"]),
            "profile_plus_extension_length_mm":
                float(values["length_mm"])+40.0,
            "k": float(values["k_h"]),
            "n": float(values["n_h"]),
            "derived_s": derived_s,
            "target_parent_s": float(record["derived"]["s_h"]),
            "parent_id": parent["id"],
            "parent_length_mm": float(values["length_mm"]),
            "parent_surface_score_v2_3":
                float(surface["overall_percent"]),
            "parent_throat_impedance_score_v2_3_0":
                float(impedance["overall_percent"]),
            "parent_composite_score_v1_0":
                float(composite["overall_percent"]),
            "parent_response_sha256": _file_hash(response),
            "parent_source_path": str(response.relative_to(ROOT)),
            "parent_report_path": str(report.relative_to(ROOT)),
        })
        inputs[candidate_id] = {
            "project": str(project_path.relative_to(ROOT)),
            "project_sha256": _file_hash(project_path),
            "search": str(search_path.relative_to(ROOT)),
            "search_sha256": _file_hash(search_path),
        }
    manifest = {
        "schema_version": 1,
        "study_id": "round-control-composite-extension-angle8-addendum-v1",
        "status": "prepared-not-run",
        "candidate_count": len(coordinates),
        "authorized_total_candidate_count": 27,
        "selection": {
            "purpose": "bridge exact matched A6/A12 impedance comparisons",
            "cells": [
                f"{coverage}deg-{mouth}mm"
                for coverage, mouth in ANGLE_ADDENDUM_CELLS
            ],
            "extension_mm": 40,
            "held_fixed": ["length_mm", "k", "n", "extension_mm"],
        },
        "ranking": "composite_score_v1.0",
        "coordinates": coordinates,
        "inputs": inputs,
    }
    manifest["coordinate_sha256"] = _content_hash(coordinates)
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(ANGLE_ADDENDUM_MANIFEST, manifest)
    refresh_index()
    return manifest


def _verify_angle_addendum() -> dict[str, Any]:
    manifest = _read(ANGLE_ADDENDUM_MANIFEST)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError("angle addendum freeze hash changed")
    if (manifest["candidate_count"] != 4
            or manifest["authorized_total_candidate_count"] != 27):
        raise ValueError("angle addendum candidate count changed")
    for values in manifest["inputs"].values():
        for kind in ("project", "search"):
            path = ROOT / values[kind]
            if _file_hash(path) != values[f"{kind}_sha256"]:
                raise ValueError(f"frozen input changed: {path}")
    return manifest


def prepare_lower_angle_study() -> dict[str, Any]:
    """Prepare complete matched A6/A8 E40 coverage for 30°–40°."""
    if LOWER_ANGLE_MANIFEST.exists():
        raise FileExistsError(LOWER_ANGLE_MANIFEST)
    map_result = _read(MAP)
    coordinates = []
    inputs = {}
    reused_a6 = []
    for coverage, mouth in LOWER_ANGLE_CELLS:
        cell_id = f"{coverage}deg-{mouth}mm"
        parent = map_result["cells"][cell_id]["zero_extension_winner"]
        exact_a6 = [
            row for row in map_result["evidence"]
            if (
                row["coverage_deg"] == coverage
                and row["mouth_mm"] == mouth
                and row["throat_angle_deg"] == 6
                and row["extension_mm"] == 40
                and math.isclose(
                    row["length_mm"], parent["length_mm"], abs_tol=1e-9)
                and math.isclose(row["k"], parent["k"], abs_tol=1e-9)
                and math.isclose(row["n"], parent["n"], abs_tol=1e-9)
            )
        ]
        if len(exact_a6) > 1:
            hashes = {row["response_sha256"] for row in exact_a6}
            if len(hashes) != 1:
                raise ValueError(f"{cell_id}: duplicate A6 responses differ")
        if exact_a6:
            reused_a6.append({
                "cell": cell_id,
                "id": exact_a6[0]["id"],
                "response_sha256": exact_a6[0]["response_sha256"],
                "report_path": exact_a6[0]["report_path"],
            })
        angles = (8,) if exact_a6 else (6, 8)
        source_path = _parent_project(parent)
        for angle in angles:
            source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
            candidate_id = (
                f"composite-ext-{coverage}deg-{mouth}mm-"
                f"E40-angle{angle}-lower-grid")
            project, search = _materialized(
                source, parent, coverage, mouth, 40,
                float(parent["length_mm"]), float(parent["k"]),
                candidate_id, throat_angle_deg=angle,
                stage="lower-coverage-angle-grid",
                parent_role="current-composite-winner",
            )
            derived_s = float(
                project["horncad_config"]["horizontal_basis"]["solved_s"])
            directory = _candidate_directory({"id": candidate_id})
            project_path = directory / "project.yaml"
            search_path = directory / "search.yaml"
            _write_yaml(project_path, project)
            _write_yaml(search_path, search)
            coordinates.append({
                "id": candidate_id,
                "cell": cell_id,
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "throat_angle_deg": angle,
                "extension_mm": 40,
                "mode": f"angle{angle}-lower-grid",
                "length_mm": float(parent["length_mm"]),
                "profile_plus_extension_length_mm":
                    float(parent["length_mm"])+40.0,
                "k": float(parent["k"]),
                "n": float(parent["n"]),
                "derived_s": derived_s,
                "target_parent_s": float(parent["s"]),
                "parent_id": parent["id"],
                "parent_length_mm": float(parent["length_mm"]),
                "parent_surface_score_v2_3":
                    float(parent["surface_score_v2_3"]),
                "parent_throat_impedance_score_v2_3_0":
                    float(parent["throat_impedance_score_v2_3_0"]),
                "parent_composite_score_v1_0":
                    float(parent["composite_score_v1_0"]),
                "parent_response_sha256": parent["response_sha256"],
                "parent_source_path": parent["source_path"],
            })
            inputs[candidate_id] = {
                "project": str(project_path.relative_to(ROOT)),
                "project_sha256": _file_hash(project_path),
                "search": str(search_path.relative_to(ROOT)),
                "search_sha256": _file_hash(search_path),
            }
    if len(coordinates) != 25 or len(reused_a6) != 5:
        raise ValueError(
            "lower angle design must contain 25 new and 5 reused responses")
    manifest = {
        "schema_version": 1,
        "study_id": "round-control-lower-coverage-angle-grid-v1",
        "status": "prepared-not-run",
        "candidate_count": len(coordinates),
        "additional_candidate_cap": 25,
        "angles_deg": [6, 8],
        "extension_mm": 40,
        "coverage_deg": [30, 35, 40],
        "mouth_mm": [250, 300, 350, 400, 450],
        "selection": {
            "new_a8_count": 15,
            "new_a6_count": 10,
            "reused_exact_a6_count": 5,
            "held_fixed_within_cell":
                ["length_mm", "k", "n", "extension_mm"],
        },
        "reused_exact_a6": reused_a6,
        "coordinates": coordinates,
        "inputs": inputs,
    }
    manifest["coordinate_sha256"] = _content_hash(coordinates)
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(LOWER_ANGLE_MANIFEST, manifest)
    refresh_index()
    return manifest


def _verify_lower_angle_manifest() -> dict[str, Any]:
    manifest = _read(LOWER_ANGLE_MANIFEST)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError("lower angle manifest freeze hash changed")
    if (manifest["candidate_count"] != 25
            or manifest["additional_candidate_cap"] != 25):
        raise ValueError("lower angle candidate cap changed")
    for values in manifest["inputs"].values():
        for kind in ("project", "search"):
            path = ROOT / values[kind]
            if _file_hash(path) != values[f"{kind}_sha256"]:
                raise ValueError(f"frozen input changed: {path}")
    return manifest


def _verify_manifest() -> dict[str, Any]:
    manifest = _read(MANIFEST)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError("manifest freeze hash changed")
    if (manifest["candidate_count"] != 23
            or manifest["hard_candidate_cap"] != 24):
        raise ValueError("candidate cap changed")
    for values in manifest["inputs"].values():
        for kind in ("project", "search"):
            path = ROOT / values[kind]
            if _file_hash(path) != values[f"{kind}_sha256"]:
                raise ValueError(f"frozen input changed: {path}")
    return manifest


def _search_paths(manifest: dict[str, Any]) -> list[Path]:
    return [
        ROOT / manifest["inputs"][row["id"]]["search"]
        for row in manifest["coordinates"]
    ]


def preflight() -> dict[str, Any]:
    manifest = _verify_manifest()
    paths = _search_paths(manifest)
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    searches = []
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if (state.get("status") != "preflight" or len(candidates) != 1
                or candidates[0].get("status") != "preflight"):
            raise ValueError(f"one-candidate preflight failed: {path}")
        searches.append(str(path.relative_to(ROOT)))
    result = {
        "schema_version": 1,
        "status": "passed",
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": searches,
    }
    _write_json(STUDY_ROOT / "preflight.json", result)
    refresh_index()
    return result


def run() -> dict[str, Any]:
    manifest = _verify_manifest()
    if not (STUDY_ROOT / "preflight.json").is_file():
        raise ValueError("preflight has not passed")
    try:
        return run_queue(
            _search_paths(manifest),
            STUDY_ROOT / "runtime.json",
            queue_workers=QUEUE_WORKERS,
            numcalc_processes=NUMCALC_PROCESSES,
            on_event=lambda _event: refresh_index(),
        )
    finally:
        refresh_index()


def preflight_angle_addendum() -> dict[str, Any]:
    manifest = _verify_angle_addendum()
    paths = _search_paths(manifest)
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    searches = []
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if (state.get("status") != "preflight" or len(candidates) != 1
                or candidates[0].get("status") != "preflight"):
            raise ValueError(f"one-candidate preflight failed: {path}")
        searches.append(str(path.relative_to(ROOT)))
    result = {
        "schema_version": 1,
        "status": "passed",
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": searches,
    }
    _write_json(STUDY_ROOT / "angle_addendum_preflight.json", result)
    refresh_index()
    return result


def run_angle_addendum() -> dict[str, Any]:
    manifest = _verify_angle_addendum()
    if not (STUDY_ROOT / "angle_addendum_preflight.json").is_file():
        raise ValueError("angle addendum preflight has not passed")
    base_runtime = _read(STUDY_ROOT / "runtime.json")
    if base_runtime.get("status") != "complete":
        raise ValueError(
            "base closure must complete before the angle addendum starts")
    try:
        return run_queue(
            _search_paths(manifest),
            STUDY_ROOT / "angle_addendum_runtime.json",
            queue_workers=QUEUE_WORKERS,
            numcalc_processes=NUMCALC_PROCESSES,
            on_event=lambda _event: refresh_index(),
        )
    finally:
        refresh_index()


def run_angle_addendum_after_base() -> dict[str, Any]:
    """Wait without consuming solver slots, then run the frozen A8 addendum."""
    while True:
        runtime = _read(STUDY_ROOT / "runtime.json")
        if runtime.get("status") != "running":
            break
        time.sleep(10)
    return run_angle_addendum()


def preflight_lower_angle_study() -> dict[str, Any]:
    manifest = _verify_lower_angle_manifest()
    paths = _search_paths(manifest)
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    searches = []
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if (state.get("status") != "preflight" or len(candidates) != 1
                or candidates[0].get("status") != "preflight"):
            raise ValueError(f"one-candidate preflight failed: {path}")
        searches.append(str(path.relative_to(ROOT)))
    result = {
        "schema_version": 1,
        "status": "passed",
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": searches,
    }
    _write_json(STUDY_ROOT / "lower_angle_preflight.json", result)
    refresh_index()
    return result


def run_lower_angle_study() -> dict[str, Any]:
    manifest = _verify_lower_angle_manifest()
    if not (STUDY_ROOT / "lower_angle_preflight.json").is_file():
        raise ValueError("lower angle preflight has not passed")
    for runtime_path in (
        STUDY_ROOT / "runtime.json",
        STUDY_ROOT / "angle_addendum_runtime.json",
    ):
        runtime = _read(runtime_path)
        if runtime.get("status") != "complete":
            raise ValueError(
                f"prior study phase is not complete: {runtime_path}")
    try:
        return run_queue(
            _search_paths(manifest),
            STUDY_ROOT / "lower_angle_runtime.json",
            queue_workers=QUEUE_WORKERS,
            numcalc_processes=NUMCALC_PROCESSES,
            on_event=lambda _event: refresh_index(),
        )
    finally:
        refresh_index()


def run_all_angle_addenda_after_base() -> dict[str, Any]:
    while True:
        runtime = _read(STUDY_ROOT / "runtime.json")
        if runtime.get("status") != "running":
            break
        time.sleep(10)
    angle_result = run_angle_addendum()
    if angle_result.get("status") != "complete":
        raise ValueError("wide A8 addendum failed")
    lower_result = run_lower_angle_study()
    return {
        "status": lower_result.get("status"),
        "wide_angle_addendum": angle_result,
        "lower_angle_study": lower_result,
    }


def _measured(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for coordinate in manifest["coordinates"]:
        search = (
            ROOT / manifest["inputs"][coordinate["id"]]["search"]
        ).parent
        state = _read(search / "search_state.json")
        record = state["candidates"][0]
        if state.get("status") != "complete":
            raise ValueError(f"{coordinate['id']}: incomplete")
        response = (
            search / "candidates" / str(record["id"])
            / "bem" / "responses.npz"
        )
        _validate_npz(response)
        surface = record["surface_diagnostics"]["score"]
        impedance = record["throat_impedance_diagnostics"]
        composite = record["composite_diagnostics"]
        if (surface.get("version") != "v2.3"
                or impedance.get("diagnostic_version") != "2.3.0"
                or composite.get("version") != "1.0"):
            raise ValueError(f"{coordinate['id']}: stale diagnostics")
        reports = sorted(response.parent.glob("*_Report.html"))
        rows.append({
            **coordinate,
            "surface_score_v2_3": float(surface["overall_percent"]),
            "throat_impedance_score_v2_3_0":
                float(impedance["overall_percent"]),
            "composite_score_v1_0": float(composite["overall_percent"]),
            "surface_delta_points": float(surface["overall_percent"])
                - coordinate["parent_surface_score_v2_3"],
            "impedance_delta_points": float(impedance["overall_percent"])
                - coordinate["parent_throat_impedance_score_v2_3_0"],
            "composite_delta_points": float(composite["overall_percent"])
                - coordinate["parent_composite_score_v1_0"],
            "response_path": str(response.relative_to(ROOT)),
            "response_sha256": _file_hash(response),
            "report_path": str(
                (reports[0] if reports else search / "search_report.html")
                .relative_to(ROOT)),
        })
    return rows


def analyze() -> dict[str, Any]:
    manifest = _verify_manifest()
    evidence = _measured(manifest)
    cells = {}
    for cell_id in DESIGN:
        rows = [row for row in evidence if row["cell"] == cell_id]
        by_mode = {row["mode"]: row for row in rows}
        comparisons = {}
        if "ordinary" in by_mode:
            ordinary = by_mode["ordinary"]
            for mode, row in by_mode.items():
                if mode == "ordinary":
                    continue
                comparisons[f"{mode}_minus_ordinary"] = {
                    key: row[key]-ordinary[key]
                    for key in (
                        "surface_score_v2_3",
                        "throat_impedance_score_v2_3_0",
                        "composite_score_v1_0",
                    )
                }
        cells[cell_id] = {
            "modes": by_mode,
            "comparisons": comparisons,
            "extension_beats_parent": max(
                row["composite_score_v1_0"] for row in rows
            ) > rows[0]["parent_composite_score_v1_0"],
        }
    result = {
        "schema_version": 1,
        "study_id": manifest["study_id"],
        "status": "complete",
        "candidate_count": len(evidence),
        "ranking": manifest["ranking"],
        "cells": cells,
        "evidence": evidence,
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "results.json", result)
    refresh_index()
    return result


def _relative(path: str) -> str:
    return os.path.relpath(ROOT / path, STUDY_ROOT).replace(os.sep, "/")


def refresh_index() -> Path:
    if not MANIFEST.is_file():
        return STUDY_ROOT / "index.html"
    base_manifest = _read(MANIFEST)
    addendum_manifest = (
        _read(ANGLE_ADDENDUM_MANIFEST)
        if ANGLE_ADDENDUM_MANIFEST.is_file() else None
    )
    lower_angle_manifest = (
        _read(LOWER_ANGLE_MANIFEST)
        if LOWER_ANGLE_MANIFEST.is_file() else None
    )
    coordinates = list(base_manifest["coordinates"])
    inputs = dict(base_manifest["inputs"])
    if addendum_manifest:
        coordinates.extend(addendum_manifest["coordinates"])
        inputs.update(addendum_manifest["inputs"])
    if lower_angle_manifest:
        coordinates.extend(lower_angle_manifest["coordinates"])
        inputs.update(lower_angle_manifest["inputs"])
    base_runtime = (
        _read(STUDY_ROOT / "runtime.json")
        if (STUDY_ROOT / "runtime.json").is_file() else {}
    )
    addendum_runtime = (
        _read(STUDY_ROOT / "angle_addendum_runtime.json")
        if (STUDY_ROOT / "angle_addendum_runtime.json").is_file() else {}
    )
    lower_angle_runtime = (
        _read(STUDY_ROOT / "lower_angle_runtime.json")
        if (STUDY_ROOT / "lower_angle_runtime.json").is_file() else {}
    )
    scheduler_active = any(
        runtime.get("status") == "running"
        for runtime in (
            base_runtime, addendum_runtime, lower_angle_runtime)
    )
    results = (
        _read(STUDY_ROOT / "results.json")
        if (STUDY_ROOT / "results.json").is_file() else None
    )
    rows = []
    state_by_id = {}
    for coordinate in coordinates:
        search = (
            ROOT / inputs[coordinate["id"]]["search"]
        ).parent
        state_by_id[coordinate["id"]] = (
            _read(search / "search_state.json")
            if (search / "search_state.json").is_file() else {})
    terminal = {"complete", "failed", "error", "blocked"}
    active_ids = set()
    for phase_manifest, runtime in (
        (base_manifest, base_runtime),
        (addendum_manifest, addendum_runtime),
        (lower_angle_manifest, lower_angle_runtime),
    ):
        if not phase_manifest or runtime.get("status") != "running":
            continue
        queue_workers = int(
            (runtime.get("scheduler") or {}).get(
                "queue_workers", QUEUE_WORKERS))
        phase_unresolved = [
            coordinate["id"] for coordinate in phase_manifest["coordinates"]
            if state_by_id[coordinate["id"]].get("status", "planned")
            not in terminal
        ]
        active_ids.update(phase_unresolved[:queue_workers])
    unresolved = [
        coordinate["id"] for coordinate in coordinates
        if state_by_id[coordinate["id"]].get("status", "planned")
        not in terminal
    ]
    complete = sum(
        state.get("status") == "complete"
        for state in state_by_id.values()
    )
    failed = sum(
        state.get("status") in {"failed", "error", "blocked"}
        for state in state_by_id.values()
    )
    running = len(active_ids)
    queued = max(0, len(unresolved)-running)

    def number(value: Any, digits: int = 2) -> str:
        return (
            f"{float(value):.{digits}f}"
            if isinstance(value, (int, float)) and math.isfinite(value)
            else "—"
        )

    for coordinate in coordinates:
        search = (
            ROOT / inputs[coordinate["id"]]["search"]
        ).parent
        state = state_by_id[coordinate["id"]]
        status = state.get("status", "planned")
        if coordinate["id"] in active_ids and status not in terminal:
            status = "running"
        elif scheduler_active and status not in terminal:
            status = "queued"
        result = next((
            row for row in (results or {}).get("evidence", [])
            if row["id"] == coordinate["id"]
        ), {})
        record = (
            state.get("candidates", [{}])[0]
            if state.get("candidates") else {}
        )
        if not result and record:
            surface = (
                (record.get("surface_diagnostics") or {}).get("score") or {})
            impedance = record.get("throat_impedance_diagnostics") or {}
            composite = record.get("composite_diagnostics") or {}
            result = {
                "surface_score_v2_3": surface.get("overall_percent"),
                "throat_impedance_score_v2_3_0":
                    impedance.get("overall_percent"),
                "composite_score_v1_0": composite.get("overall_percent"),
            }
            for key, parent_key in (
                ("surface_delta_points", "parent_surface_score_v2_3"),
                ("impedance_delta_points",
                 "parent_throat_impedance_score_v2_3_0"),
                ("composite_delta_points",
                 "parent_composite_score_v1_0"),
            ):
                score_key = {
                    "surface_delta_points": "surface_score_v2_3",
                    "impedance_delta_points":
                        "throat_impedance_score_v2_3_0",
                    "composite_delta_points": "composite_score_v1_0",
                }[key]
                if isinstance(result.get(score_key), (int, float)):
                    result[key] = (
                        float(result[score_key])-coordinate[parent_key])
        report = result.get("report_path")
        if not report and record.get("report_file"):
            candidate = search / str(record["report_file"])
            if candidate.is_file():
                report = str(candidate.relative_to(ROOT))
        label = html.escape(coordinate["id"])
        if report:
            label = f"<a href='{html.escape(_relative(report))}'>{label}</a>"
        parent_response = ROOT / coordinate["parent_source_path"]
        parent_reports = (
            [ROOT / coordinate["parent_report_path"]]
            if coordinate.get("parent_report_path") else
            sorted(parent_response.parent.glob("*_Report.html"))
        )
        parent_label = html.escape(coordinate["parent_id"])
        if parent_reports:
            parent_href = os.path.relpath(
                parent_reports[0], STUDY_ROOT).replace(os.sep, "/")
            parent_label = (
                f"<a href='{html.escape(parent_href)}'>{parent_label}</a>")
        status_class = (
            "complete" if status == "complete" else
            "running" if status == "running" else
            "failed" if status in {"failed", "error", "blocked"} else
            "pending"
        )
        rows.append(
            f"<tr data-cell='{html.escape(coordinate['cell'])}' "
            f"data-mode='{html.escape(coordinate['mode'])}'>"
            f"<td>{label}</td>"
            f"<td><span class='badge {status_class}'>{html.escape(status)}</span></td>"
            f"<td>{html.escape(coordinate['cell'])}</td>"
            f"<td>{html.escape(coordinate['mode'])}</td>"
            f"<td>{coordinate['throat_angle_deg']}</td>"
            f"<td>{coordinate['extension_mm']}</td>"
            f"<td>{number(coordinate['length_mm'],3)}</td>"
            f"<td>{number(coordinate['profile_plus_extension_length_mm'],3)}</td>"
            f"<td>{number(coordinate['k'],3)}</td>"
            f"<td>{number(coordinate['n'],2)}</td>"
            f"<td>{number(coordinate['derived_s'],4)}</td>"
            f"<td>{number(result.get('surface_score_v2_3'))}</td>"
            f"<td>{number(result.get('surface_delta_points'))}</td>"
            f"<td>{number(result.get('throat_impedance_score_v2_3_0'))}</td>"
            f"<td>{number(result.get('impedance_delta_points'))}</td>"
            f"<td>{number(result.get('composite_score_v1_0'))}</td>"
            f"<td>{number(result.get('composite_delta_points'))}</td>"
            f"<td>{number(coordinate['parent_composite_score_v1_0'])}</td>"
            f"<td>{parent_label}</td></tr>"
        )
    refresh = (
        "<meta http-equiv='refresh' content='30'>"
        if scheduler_active else ""
    )
    cell_buttons = "".join(
        f"<button data-cell-filter='{html.escape(cell)}'>{html.escape(cell)}</button>"
        for cell in sorted(
            {coordinate["cell"] for coordinate in coordinates},
            key=lambda value: tuple(
                int(part.removesuffix(suffix))
                for part, suffix in zip(value.split("-"), ("deg", "mm"))
            ),
        )
    )
    document = f"""<!doctype html><meta charset="utf-8">
{refresh}<title>6° composite extension closure</title>
<style>
:root{{--bg:#10161d;--panel:#17212a;--panel2:#202c36;--line:#34414c;--ink:#e8edf2;--muted:#aab5bf;--accent:#68c9bd}}
*{{box-sizing:border-box}}body{{font:15px system-ui,sans-serif;margin:0;padding:20px;background:var(--bg);color:var(--ink)}}
h1,h2{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow:auto}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right}}th{{background:var(--panel2);cursor:pointer;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;text-transform:uppercase;font-size:.8rem}}.complete{{background:#174b40;color:#8de8cc}}.running{{background:#5a451d;color:#f6d39a}}.failed{{background:#5a2929;color:#ffb2b2}}.pending{{background:#29343e;color:#c8d0d8}}
.filters{{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}}button{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel2);color:var(--ink);cursor:pointer}}button[aria-pressed=true]{{border-color:var(--accent);background:#173c39}}.muted{{color:var(--muted)}}
</style>
<h1>Round-control 6° composite extension/S closure</h1>
<p>Established fixed-candidate study report. Composite v1.0 is 75% surface
v2.3 plus 25% throat impedance v2.3.0.</p>
<div class="summary">
<div class="card"><strong>{complete} / {len(coordinates)}</strong>BEM complete</div>
<div class="card"><strong>{running}</strong>running searches</div>
<div class="card"><strong>{queued}</strong>queued searches</div>
<div class="card"><strong>{failed}</strong>failed · {len(coordinates)} authorized</div>
</div>
<section><h2>Project range</h2><table><tr><th>Coverage</th><th>Mouths</th>
<th>Throat angle</th><th>Extensions</th><th>Recovery controls</th>
<th>Scheduler</th></tr><tr><td>30°–50°</td><td>250–450 mm</td>
<td>6°/8° grid; 6° S closure</td><td>20, 40, 60 mm</td><td>OSSE length and K at fixed S</td>
<td>4 queue workers · 20 NumCalc processes</td></tr></table>
<p class="muted">Base coordinate SHA-256:
<code>{html.escape(base_manifest['coordinate_sha256'])}</code>
{(" · Wide A8 SHA-256: <code>" + html.escape(addendum_manifest["coordinate_sha256"]) + "</code>") if addendum_manifest else ""}
{(" · Lower-angle SHA-256: <code>" + html.escape(lower_angle_manifest["coordinate_sha256"]) + "</code>") if lower_angle_manifest else ""}</p></section>
<section><h2>Candidates</h2><div class="filters">
<button data-cell-filter="all" aria-pressed="true">All cells</button>{cell_buttons}
</div><table id="candidate-table"><thead><tr><th>Candidate</th><th>Status</th>
<th>Cell</th><th>Mode</th><th>Angle</th><th>Extension</th><th>OSSE length</th>
<th>Total length</th><th>K</th><th>N</th><th>S</th><th>Surface v2.3</th>
<th>Surface Δ</th><th>Impedance v2.3.0</th><th>Impedance Δ</th>
<th>Composite v1.0</th><th>Composite Δ</th><th>Parent composite</th>
<th>Parent</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<script>
const table=document.querySelector('#candidate-table'),body=table.tBodies[0];
for(const [i,th] of [...table.tHead.rows[0].cells].entries()){{
 th.addEventListener('click',()=>{{const asc=th.dataset.order!=='asc';th.dataset.order=asc?'asc':'desc';
 const rows=[...body.rows].sort((a,b)=>{{const av=a.cells[i].textContent.trim(),bv=b.cells[i].textContent.trim(),an=Number(av),bn=Number(bv);
 const d=Number.isFinite(an)&&Number.isFinite(bn)?an-bn:av.localeCompare(bv);return asc?d:-d}});body.append(...rows)}})
}}
for(const button of document.querySelectorAll('[data-cell-filter]')){{
 button.addEventListener('click',()=>{{const value=button.dataset.cellFilter;
 for(const other of document.querySelectorAll('[data-cell-filter]'))other.setAttribute('aria-pressed',String(other===button));
 for(const row of body.rows)row.hidden=value!=='all'&&row.dataset.cell!==value}})
}}
</script>"""
    STUDY_ROOT.mkdir(parents=True, exist_ok=True)
    path = STUDY_ROOT / "index.html"
    path.write_text(document, encoding="utf-8")
    return path


def watch_index() -> dict[str, Any]:
    """Keep the ledger-backed index current for an already-running scheduler."""
    refresh_count = 0
    while True:
        refresh_index()
        refresh_count += 1
        base_runtime = (
            _read(STUDY_ROOT / "runtime.json")
            if (STUDY_ROOT / "runtime.json").is_file() else {}
        )
        addendum_runtime = (
            _read(STUDY_ROOT / "angle_addendum_runtime.json")
            if (STUDY_ROOT / "angle_addendum_runtime.json").is_file()
            else {}
        )
        lower_angle_runtime = (
            _read(STUDY_ROOT / "lower_angle_runtime.json")
            if (STUDY_ROOT / "lower_angle_runtime.json").is_file()
            else {}
        )
        if not any(
            runtime.get("status") == "running"
            for runtime in (
                base_runtime, addendum_runtime, lower_angle_runtime)
        ):
            break
        time.sleep(10)
    return {"status": "complete", "refresh_count": refresh_count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "prepare", "preflight", "run", "analyze", "index", "watch-index",
        "prepare-angle-addendum", "preflight-angle-addendum",
        "run-angle-addendum", "run-angle-addendum-after-base",
        "prepare-lower-angle", "preflight-lower-angle",
        "run-lower-angle", "run-all-angle-addenda-after-base"))
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "preflight":
        result = preflight()
    elif args.command == "run":
        result = run()
    elif args.command == "analyze":
        result = analyze()
    elif args.command == "watch-index":
        result = watch_index()
    elif args.command == "prepare-angle-addendum":
        result = prepare_angle_addendum()
    elif args.command == "preflight-angle-addendum":
        result = preflight_angle_addendum()
    elif args.command == "run-angle-addendum":
        result = run_angle_addendum()
    elif args.command == "run-angle-addendum-after-base":
        result = run_angle_addendum_after_base()
    elif args.command == "prepare-lower-angle":
        result = prepare_lower_angle_study()
    elif args.command == "preflight-lower-angle":
        result = preflight_lower_angle_study()
    elif args.command == "run-lower-angle":
        result = run_lower_angle_study()
    elif args.command == "run-all-angle-addenda-after-base":
        result = run_all_angle_addenda_after_base()
    else:
        result = {"index": str(refresh_index().relative_to(ROOT))}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
