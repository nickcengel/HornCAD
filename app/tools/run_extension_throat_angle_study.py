#!/usr/bin/env python3
"""Execute the staged full-grid extension and throat-angle heuristic study."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml

from .export_horncad import osse_base_radius, termination_unit
from .prepare_extension_throat_angle_study import (
    CONDITIONAL_CELLS,
    ENDPOINT_ANGLES_EXTENSIONS,
    INITIAL_CANDIDATES,
    MAX_CANDIDATES,
    RADIATION_ERROR_LIMITS,
    SECONDARY_CELLS,
    candidate_design,
    validate_design,
)
from .round_control_model import (
    _content_hash,
    _digest_file,
    _rescore,
    _validate_npz,
)
from .run_bem_search import materialize_candidate, run_search
from .run_stage_aware_bem_queue import run_queue, validate_queue


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/extension-throat-angle-heuristics"
TRAINING_INDEX = (
    ROOT / "examples/control-decoupling/model_source/training_index.json")
V2_RESULTS = (
    ROOT / "examples/round-control-v2-validation/validation_results.json")
RIDGE_RESULTS = ROOT / "examples/round-control-ridge-closure/results.json"
SHORT_RESULTS = (
    ROOT / "examples/round-control-short-length-closure/results.json")
ROUND_HEURISTICS = ROOT / "models/round_control_heuristics_v1/heuristics.json"
MANIFEST = STUDY_ROOT / "manifest.json"
FROZEN_HEURISTIC = STUDY_ROOT / "frozen_paired_heuristic.json"

DEVELOPMENT_STAGES = ("primary-development", "secondary-transfer")
LOCKED_STAGE = "locked-validation"
CONDITIONAL_STAGE = "conditional-validation"
QUEUE_WORKERS = 4
NUMCALC_PROCESSES = 20
DIAGNOSTICS = (
    "surface_score",
    "mean_containment",
    "profile_rms_error",
    "slice_energy_rms_departure",
    "outward_rise_violation",
    "minus_six_db_rms_error",
    "throat_impedance_score",
)


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


def _response_project(response: Path) -> Path:
    project = response.parents[1] / "project.yaml"
    if not project.is_file():
        raise FileNotFoundError(project)
    return project


def _normalized_evidence() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = _read_json(TRAINING_INDEX)
    for row in index["rows"]:
        response = ROOT / row["source_path"]
        if (not response.is_file()
                or any(row.get(key) is None for key in (
                    "length_mm", "length_factor", "k", "n", "s"))
                or not isinstance(row.get("responses"), dict)):
            continue
        rows.append({
            "id": row["id"],
            "coverage_deg": int(row["coverage_deg"]),
            "mouth_mm": int(row["mouth_mm"]),
            "length_mm": float(row["length_mm"]),
            "length_factor": float(row["length_factor"]),
            "k": float(row["k"]),
            "n": float(row["n"]),
            "s": float(row["s"]),
            "responses": row["responses"],
            "response_path": str(response.relative_to(ROOT)),
            "response_sha256": row["response_sha256"],
            "project_path": str(_response_project(response).relative_to(ROOT)),
            "provenance": row["provenance"],
        })
    for path, provenance in (
        (V2_RESULTS, "fresh-v2-locked"),
        (RIDGE_RESULTS, "ridge-closure"),
        (SHORT_RESULTS, "short-length-closure"),
    ):
        result = _read_json(path)
        for row in result["evidence"]:
            response_value = row.get("response_path", row.get("source_path"))
            response = ROOT / response_value
            rows.append({
                "id": row["id"],
                "coverage_deg": int(row["coverage_deg"]),
                "mouth_mm": int(row["mouth_mm"]),
                "length_mm": float(row["length_mm"]),
                "length_factor": float(row["length_factor"]),
                "k": float(row["k"]),
                "n": float(row["n"]),
                "s": float(row.get("derived_s", row.get("s"))),
                "responses": row["responses"],
                "response_path": str(response.relative_to(ROOT)),
                "response_sha256": row["response_sha256"],
                "project_path": str(
                    _response_project(response).relative_to(ROOT)),
                "provenance": provenance,
            })
    unique = {}
    for row in rows:
        unique[row["id"]] = row
    return list(unique.values())


def _distance(first: dict[str, Any], second: dict[str, Any]) -> float:
    return math.sqrt(
        ((float(first["length_factor"])-float(second["length_factor"]))/0.2)**2
        + ((float(first["k"])-float(second["k"]))/2.0)**2
        + ((float(first["n"])-float(second["n"]))/4.0)**2
    )


def select_parents() -> dict[str, Any]:
    evidence = _normalized_evidence()
    by_id = {row["id"]: row for row in evidence}
    heuristic = _read_json(ROUND_HEURISTICS)
    cell_audit = heuristic["audit"]["observed_high_score_zones"]["cells"]
    primary = {}
    for coverage in (30, 35, 40, 45, 50):
        for mouth in (250, 300, 350, 400, 450):
            cell_id = f"{coverage}deg-{mouth}mm"
            parent_id = cell_audit[cell_id]["best"]["id"]
            if parent_id not in by_id:
                raise ValueError(f"cannot resolve primary parent {parent_id}")
            primary[cell_id] = by_id[parent_id]
    secondary = {}
    secondary_audit = {}
    for coverage, mouth in SECONDARY_CELLS:
        cell_id = f"{coverage}deg-{mouth}mm"
        parent = primary[cell_id]
        candidates = [
            row for row in evidence
            if row["coverage_deg"] == coverage
            and row["mouth_mm"] == mouth
            and row["id"] != parent["id"]
            and float(parent["responses"]["surface_score"])
            - float(row["responses"]["surface_score"]) <= 2.0
        ]
        if not candidates:
            raise ValueError(f"no distinct competitive secondary at {cell_id}")
        preferred = [
            row for row in candidates if _distance(parent, row) >= 1.1
        ]
        selected = max(
            preferred or candidates,
            key=lambda row: (
                float(row["responses"]["surface_score"]),
                _distance(parent, row),
                row["id"],
            ),
        )
        secondary[cell_id] = selected
        secondary_audit[cell_id] = {
            "primary_id": parent["id"],
            "secondary_id": selected["id"],
            "normalized_distance": _distance(parent, selected),
            "surface_score_gap": (
                float(parent["responses"]["surface_score"])
                - float(selected["responses"]["surface_score"])
            ),
            "distance_target_met": _distance(parent, selected) >= 1.1,
        }
    return {
        "selection_rule": {
            "primary": "final measured surface-score winner in each cell",
            "secondary": (
                "highest-scoring non-primary within 2 surface-score points "
                "among candidates at normalized L/K/N distance >= 1.1; "
                "if none exists, use the highest-scoring distinct candidate "
                "within the same score window"
            ),
            "throat_impedance_used": False,
        },
        "primary": primary,
        "secondary": secondary,
        "secondary_audit": secondary_audit,
    }


def _parent_for(row: dict[str, Any],
                parents: dict[str, Any]) -> dict[str, Any]:
    cell_id = (
        f"{row['coverage_deg']}deg-{row['round_mouth_diameter_mm']}mm")
    return parents[row["parent_role"]][cell_id]


def _candidate_directory(row: dict[str, Any]) -> Path:
    mouth = row["round_mouth_diameter_mm"]
    label = (
        f"{row['parent_role']}-A{row['throat_angle_deg']}"
        f"-E{row['extension_mm']}")
    return (
        STUDY_ROOT / "searches" / row["stage"]
        / f"{row['coverage_deg']}deg" / f"{mouth}mm" / label
    )


def _search_document(row: dict[str, Any],
                     parent: dict[str, Any]) -> tuple[
                         dict[str, Any], dict[str, float]]:
    coverage = float(row["coverage_deg"])
    values = {
        "length_mm": float(parent["length_mm"]),
        "extension_mm": float(row["extension_mm"]),
        "osse_coverage_h_deg": coverage,
        "osse_coverage_v_deg": coverage,
        "k_h": float(parent["k"]),
        "k_v": float(parent["k"]),
        "n_h": float(parent["n"]),
        "n_v": float(parent["n"]),
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
        "fixed_design": True,
        "bounds": bounds,
        "initial_pool": [{
            "label": f"{row['id']}-schema-seed-duplicate",
            "values": values,
        }],
        "solver": {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 10,
        },
        "extension_throat_angle_study": {
            "coordinate_id": row["id"],
            "stage": row["stage"],
            "parent_id": parent["id"],
            "parent_role": row["parent_role"],
            "throat_angle_deg": row["throat_angle_deg"],
            "throat_impedance_reported": True,
            "throat_impedance_used_in_surface_score": False,
        },
    }
    return {"bem_candidate_search": search}, values


def _geometry_metadata(
    project: dict[str, Any],
    parent: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, float]:
    config = project["horncad_config"]
    global_config = config["global"]
    effective_radius = float(global_config["effective_throat_radius"])
    length = float(parent["length_mm"])
    coverage = float(row["coverage_deg"])
    k = float(parent["k"])
    n = float(parent["n"])
    angle = float(row["throat_angle_deg"])
    parent_s = float(parent["s"])
    equivalent_radius = (
        osse_base_radius(
            length, length, effective_radius, coverage, k, angle)
        + parent_s*termination_unit(length, length, 0.995, n)
    )
    mouth = float(row["round_mouth_diameter_mm"])
    return {
        "derived_s": float(config["horizontal_basis"]["solved_s"]),
        "authored_throat_radius_mm": float(global_config["throat_radius"]),
        "effective_profile_throat_radius_mm": effective_radius,
        "osse_length_mm": length,
        "profile_plus_extension_length_mm":
            length+float(row["extension_mm"]),
        "equivalent_mouth_diameter_mm": 2.0*equivalent_radius,
        "equivalent_mouth_shift_mm": 2.0*equivalent_radius-mouth,
    }


def _materialize(rows: list[dict[str, Any]],
                 parents: dict[str, Any]) -> dict[str, Any]:
    inputs = {}
    enriched = []
    for row in rows:
        parent = _parent_for(row, parents)
        source_path = ROOT / parent["project_path"]
        source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        source["horncad_config"]["global"]["throat_angle_deg"] = float(
            row["throat_angle_deg"])
        document, values = _search_document(row, parent)
        project, _ = materialize_candidate(
            copy.deepcopy(source), values, document["bem_candidate_search"])
        directory = _candidate_directory(row)
        _write_yaml(directory / "project.yaml", project)
        _write_yaml(directory / "search.yaml", document)
        metadata = _geometry_metadata(project, parent, row)
        item = {
            **row,
            "parent_id": parent["id"],
            "parent_response_path": parent["response_path"],
            "parent_response_sha256": parent["response_sha256"],
            "parent_surface_score": float(
                parent["responses"]["surface_score"]),
            "parent_throat_impedance_score": float(
                parent["responses"]["throat_impedance_score"]),
            **metadata,
        }
        enriched.append(item)
        inputs[row["id"]] = {
            "project": str((directory / "project.yaml").relative_to(ROOT)),
            "project_sha256": _digest_file(directory / "project.yaml"),
            "search": str((directory / "search.yaml").relative_to(ROOT)),
            "search_sha256": _digest_file(directory / "search.yaml"),
        }
    return {"coordinates": enriched, "inputs": inputs}


def prepare() -> dict[str, Any]:
    design = candidate_design()
    validate_design(design)
    if MANIFEST.exists():
        raise FileExistsError(f"study already prepared: {MANIFEST}")
    parents = select_parents()
    initial_rows = [
        row for row in design if row["stage"] != CONDITIONAL_STAGE]
    materialized = _materialize(initial_rows, parents)
    abstract_conditional = [
        row for row in design if row["stage"] == CONDITIONAL_STAGE]
    manifest = {
        "schema_version": 1,
        "study_id": "extension-throat-angle-heuristics-v1",
        "status": "frozen-not-run",
        "hard_candidate_cap": MAX_CANDIDATES,
        "initial_candidate_count": INITIAL_CANDIDATES,
        "candidate_count": len(materialized["coordinates"]),
        "counts": {
            stage: sum(
                row["stage"] == stage
                for row in materialized["coordinates"])
            for stage in (*DEVELOPMENT_STAGES, LOCKED_STAGE)
        },
        "parents": parents,
        "coordinates": materialized["coordinates"],
        "conditional_coordinates": abstract_conditional,
        "inputs": materialized["inputs"],
        "source_hashes": {
            "training_index": _digest_file(TRAINING_INDEX),
            "v2_results": _digest_file(V2_RESULTS),
            "ridge_results": _digest_file(RIDGE_RESULTS),
            "short_results": _digest_file(SHORT_RESULTS),
            "round_heuristics": _digest_file(ROUND_HEURISTICS),
        },
        "scheduler": {
            "type": "stage-aware-bem-queue",
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
            "search_sharding": "one-candidate-per-search",
        },
        "radiation_absolute_error_limits": RADIATION_ERROR_LIMITS,
        "throat_impedance": {
            "reported_in_all_reports": True,
            "included_in_surface_score": False,
            "included_in_ranking": False,
            "included_in_expansion_gate": False,
        },
        "implementation_sha256": _digest_file(Path(__file__)),
        "outcomes_loaded": False,
        "bem_jobs_scheduled": 0,
    }
    coordinate_payload = [
        {
            key: row[key]
            for key in (
                "id", "stage", "coverage_deg",
                "round_mouth_diameter_mm", "parent_id", "parent_role",
                "throat_angle_deg", "extension_mm",
            )
        }
        for row in manifest["coordinates"]
    ] + manifest["conditional_coordinates"]
    manifest["coordinate_sha256"] = hashlib.sha256(
        json.dumps(
            coordinate_payload, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(MANIFEST, manifest)
    write_index()
    return manifest


def _verify_manifest() -> dict[str, Any]:
    manifest = _read_json(MANIFEST)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if expected != actual:
        raise ValueError("study manifest freeze hash changed")
    if manifest["candidate_count"] > manifest["hard_candidate_cap"]:
        raise ValueError("candidate cap exceeded")
    for row in manifest["coordinates"]:
        item = manifest["inputs"][row["id"]]
        for kind in ("project", "search"):
            path = ROOT / item[kind]
            if _digest_file(path) != item[f"{kind}_sha256"]:
                raise ValueError(f"changed frozen input: {path}")
    return manifest


def _stage_rows(manifest: dict[str, Any],
                stages: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        row for row in manifest["coordinates"] if row["stage"] in stages
    ]


def _search_paths(manifest: dict[str, Any],
                  stages: tuple[str, ...]) -> list[Path]:
    return [
        ROOT / manifest["inputs"][row["id"]]["search"]
        for row in _stage_rows(manifest, stages)
    ]


def preflight(stages: tuple[str, ...]) -> dict[str, Any]:
    manifest = _verify_manifest()
    paths = _search_paths(manifest, stages)
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    completed = []
    for index, path in enumerate(paths, 1):
        state = run_search(path, path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if (state.get("status") != "preflight" or len(candidates) != 1
                or candidates[0].get("status") != "preflight"):
            raise ValueError(f"one-candidate preflight failed: {path}")
        completed.append(str(path.relative_to(ROOT)))
        if index % 25 == 0:
            print(f"preflight {index}/{len(paths)}", flush=True)
    label = "-".join(stages)
    result = {
        "schema_version": 1,
        "stages": list(stages),
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": completed,
    }
    _write_json(STUDY_ROOT / f"preflight-{label}.json", result)
    # A combined all-initial preflight also freezes the exact stage-specific
    # evidence needed by the separately launched development and locked runs.
    for marker_stages in (DEVELOPMENT_STAGES, (LOCKED_STAGE,)):
        if set(marker_stages).issubset(stages):
            marker_paths = _search_paths(manifest, marker_stages)
            marker = {
                **result,
                "stages": list(marker_stages),
                "candidate_count": len(marker_paths),
                "searches": [
                    str(path.relative_to(ROOT)) for path in marker_paths
                ],
            }
            _write_json(
                STUDY_ROOT / f"preflight-{'-'.join(marker_stages)}.json",
                marker,
            )
    write_index()
    return result


def run(stages: tuple[str, ...]) -> dict[str, Any]:
    manifest = _verify_manifest()
    label = "-".join(stages)
    preflight_path = STUDY_ROOT / f"preflight-{label}.json"
    if not preflight_path.is_file():
        raise ValueError(f"missing stage preflight: {preflight_path}")
    result = run_queue(
        _search_paths(manifest, stages),
        STUDY_ROOT / f"runtime-{label}.json",
        queue_workers=QUEUE_WORKERS,
        numcalc_processes=NUMCALC_PROCESSES,
    )
    write_index()
    return result


def _measured_row(manifest: dict[str, Any],
                  row: dict[str, Any]) -> dict[str, Any]:
    search = ROOT / manifest["inputs"][row["id"]]["search"]
    response = search.parent / "candidates/candidate-000/bem/responses.npz"
    _, _ = _validate_npz(response)
    values, impedance, delta = _rescore(response)
    if delta > 1e-9:
        raise ValueError(f"{row['id']}: diagnostics differ by {delta:g}")
    return {
        **row,
        "responses": {**values, **impedance},
        "response_path": str(response.relative_to(ROOT)),
        "response_sha256": _digest_file(response),
    }


def _baseline(parent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": parent["id"],
        "throat_angle_deg": 6,
        "extension_mm": 0,
        "responses": {
            key: float(parent["responses"][key]) for key in DIAGNOSTICS
        },
        "response_path": parent["response_path"],
        "response_sha256": parent["response_sha256"],
    }


def _formula_prediction(
    measured: dict[tuple[int, int], dict[str, float]],
    angle: int,
    extension: int,
) -> dict[str, float]:
    baseline = measured[(6, 0)]
    at_extension = measured[(6, extension)]
    at_angle_zero = measured[(angle, 0)]
    at_angle_forty = measured[(angle, 40)]
    at_six_forty = measured[(6, 40)]
    return {
        diagnostic: (
            baseline[diagnostic]
            + (at_extension[diagnostic]-baseline[diagnostic])
            + (at_angle_zero[diagnostic]-baseline[diagnostic])
            + extension/40.0*(
                at_angle_forty[diagnostic]
                - at_six_forty[diagnostic]
                - (at_angle_zero[diagnostic]-baseline[diagnostic])
            )
        )
        for diagnostic in DIAGNOSTICS
    }


def freeze_heuristic() -> dict[str, Any]:
    manifest = _verify_manifest()
    development = [
        _measured_row(manifest, row)
        for row in _stage_rows(manifest, DEVELOPMENT_STAGES)
    ]
    lookup = {}
    predictions = {}
    for cell_id, parent in manifest["parents"]["primary"].items():
        coverage = int(parent["coverage_deg"])
        mouth = int(parent["mouth_mm"])
        rows = [
            row for row in development
            if row["parent_role"] == "primary"
            and int(row["coverage_deg"]) == coverage
            and int(row["round_mouth_diameter_mm"]) == mouth
        ]
        baseline = _baseline(parent)
        table = {
            (int(row["throat_angle_deg"]), int(row["extension_mm"])):
                {key: float(row["responses"][key]) for key in DIAGNOSTICS}
            for row in rows
        }
        table[(6, 0)] = baseline["responses"]
        required = {
            (6, 0), (6, 20), (6, 40), (6, 60),
            (0, 0), (12, 0), (0, 40), (12, 40),
        }
        if set(table) != required:
            raise ValueError(f"{cell_id}: incomplete primary lookup")
        lookup[cell_id] = {
            f"A{angle}-E{extension}": values
            for (angle, extension), values in sorted(table.items())
        }
        predictions[cell_id] = {
            f"A{angle}-E{extension}":
                _formula_prediction(table, angle, extension)
            for angle, extension in ENDPOINT_ANGLES_EXTENSIONS
        }
    secondary = {}
    for cell_id, parent in manifest["parents"]["secondary"].items():
        rows = [
            row for row in development
            if row["parent_role"] == "secondary"
            and int(row["coverage_deg"]) == int(parent["coverage_deg"])
            and int(row["round_mouth_diameter_mm"]) == int(parent["mouth_mm"])
        ]
        secondary[cell_id] = {
            "parent": _baseline(parent),
            "measurements": {
                f"A{int(row['throat_angle_deg'])}-E{int(row['extension_mm'])}":
                    {key: float(row["responses"][key])
                     for key in DIAGNOSTICS}
                for row in rows
            },
        }
    artifact = {
        "schema_version": 1,
        "heuristic_id": "extension_throat_heuristics_v1-frozen",
        "status": "frozen-before-locked-outcomes",
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "development_response_hashes": {
            row["id"]: row["response_sha256"] for row in development
        },
        "formula": (
            "y(a,e)=y(6,0)+[y(6,e)-y(6,0)]+[y(a,0)-y(6,0)]"
            "+(e/40)*{y(a,40)-y(6,40)-[y(a,0)-y(6,0)]}"
        ),
        "diagnostics": list(DIAGNOSTICS),
        "radiation_absolute_error_limits": RADIATION_ERROR_LIMITS,
        "primary_lookup": lookup,
        "locked_and_conditional_predictions": predictions,
        "secondary_transfer_measurements": secondary,
        "throat_impedance": {
            "predicted_and_reported": True,
            "included_in_surface_score": False,
            "included_in_validation_gate": False,
        },
    }
    artifact["freeze_sha256"] = _content_hash(artifact)
    _write_json(FROZEN_HEURISTIC, artifact)
    write_index()
    return artifact


def validate_locked() -> dict[str, Any]:
    manifest = _verify_manifest()
    frozen = _read_json(FROZEN_HEURISTIC)
    expected = frozen["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in frozen.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError("frozen heuristic hash changed")
    rows = [
        _measured_row(manifest, row)
        for row in _stage_rows(manifest, (LOCKED_STAGE,))
    ]
    comparisons = []
    gate_failed = False
    for row in rows:
        cell_id = (
            f"{row['coverage_deg']}deg-"
            f"{row['round_mouth_diameter_mm']}mm")
        key = f"A{row['throat_angle_deg']}-E{row['extension_mm']}"
        predicted = frozen["locked_and_conditional_predictions"][cell_id][key]
        errors = {
            diagnostic: float(row["responses"][diagnostic])-float(value)
            for diagnostic, value in predicted.items()
        }
        failures = {
            diagnostic: abs(errors[diagnostic]) > limit
            for diagnostic, limit in RADIATION_ERROR_LIMITS.items()
        }
        failed = any(failures.values())
        gate_failed = gate_failed or failed
        comparisons.append({
            "id": row["id"],
            "cell": cell_id,
            "coordinate": key,
            "predicted": predicted,
            "observed": {
                key: float(row["responses"][key]) for key in DIAGNOSTICS
            },
            "errors": errors,
            "radiation_threshold_failures": failures,
            "radiation_gate_failed": failed,
            "response_sha256": row["response_sha256"],
        })
    result = {
        "schema_version": 1,
        "frozen_heuristic_sha256": frozen["freeze_sha256"],
        "candidate_count": len(rows),
        "radiation_gate_failed": gate_failed,
        "conditional_block_authorized": gate_failed,
        "comparisons": comparisons,
        "throat_impedance_used_in_gate": False,
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "locked_validation.json", result)
    write_index()
    return result


def prepare_conditional() -> dict[str, Any]:
    validation = _read_json(STUDY_ROOT / "locked_validation.json")
    if not validation["conditional_block_authorized"]:
        result = {
            "schema_version": 1,
            "authorized": False,
            "candidate_count": 0,
            "reason": "all locked radiation thresholds passed",
        }
        _write_json(STUDY_ROOT / "conditional_decision.json", result)
        return result
    manifest = _verify_manifest()
    if any(row["stage"] == CONDITIONAL_STAGE
           for row in manifest["coordinates"]):
        raise ValueError("conditional block already prepared")
    materialized = _materialize(
        manifest["conditional_coordinates"], manifest["parents"])
    manifest["coordinates"].extend(materialized["coordinates"])
    manifest["inputs"].update(materialized["inputs"])
    manifest["candidate_count"] = len(manifest["coordinates"])
    if manifest["candidate_count"] != MAX_CANDIDATES:
        raise ValueError("conditional materialization did not reach hard cap")
    # This is an authorized append whose exact abstract coordinates were
    # already covered by the original coordinate hash.
    manifest["conditional_materialization"] = {
        "locked_validation_content_sha256": validation["content_sha256"],
        "candidate_count": len(materialized["coordinates"]),
    }
    manifest["freeze_sha256"] = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    _write_json(MANIFEST, manifest)
    result = {
        "schema_version": 1,
        "authorized": True,
        "candidate_count": len(materialized["coordinates"]),
        "locked_validation_content_sha256": validation["content_sha256"],
    }
    _write_json(STUDY_ROOT / "conditional_decision.json", result)
    write_index()
    return result


def analyze() -> dict[str, Any]:
    manifest = _verify_manifest()
    frozen = _read_json(FROZEN_HEURISTIC)
    measured = [
        _measured_row(manifest, row) for row in manifest["coordinates"]
    ]
    locked = _read_json(STUDY_ROOT / "locked_validation.json")
    conditional_rows = [
        row for row in measured if row["stage"] == CONDITIONAL_STAGE
    ]
    conditional_comparisons = []
    for row in conditional_rows:
        cell_id = (
            f"{row['coverage_deg']}deg-"
            f"{row['round_mouth_diameter_mm']}mm")
        key = f"A{row['throat_angle_deg']}-E{row['extension_mm']}"
        predicted = frozen["locked_and_conditional_predictions"][cell_id][key]
        conditional_comparisons.append({
            "id": row["id"],
            "cell": cell_id,
            "coordinate": key,
            "predicted": predicted,
            "observed": {
                diagnostic: float(row["responses"][diagnostic])
                for diagnostic in DIAGNOSTICS
            },
            "errors": {
                diagnostic: float(row["responses"][diagnostic])
                - float(predicted[diagnostic])
                for diagnostic in DIAGNOSTICS
            },
            "response_sha256": row["response_sha256"],
        })
    result = {
        "schema_version": 1,
        "study_id": "extension-throat-angle-heuristics-v1",
        "candidate_count": len(measured),
        "hard_candidate_cap": MAX_CANDIDATES,
        "frozen_heuristic_sha256": frozen["freeze_sha256"],
        "evidence": sorted(measured, key=lambda row: row["id"]),
        "locked_validation": locked,
        "conditional_validation": conditional_comparisons,
        "throat_impedance": {
            "reported_for_every_candidate": True,
            "included_in_surface_score": False,
            "included_in_ranking": False,
            "included_in_expansion_gate": False,
        },
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "results.json", result)
    write_index()
    return result


def write_index() -> Path:
    if not MANIFEST.is_file():
        return STUDY_ROOT / "index.html"
    from .report_extension_throat_angle_study import refresh_index
    return refresh_index(STUDY_ROOT)


def _parse_stage(value: str) -> tuple[str, ...]:
    choices = {
        "development": DEVELOPMENT_STAGES,
        "locked": (LOCKED_STAGE,),
        "conditional": (CONDITIONAL_STAGE,),
        "all-initial": (*DEVELOPMENT_STAGES, LOCKED_STAGE),
    }
    return choices[value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "prepare", "preflight", "run", "freeze", "validate-locked",
        "prepare-conditional", "analyze", "index",
    ))
    parser.add_argument(
        "--stage", choices=(
            "development", "locked", "conditional", "all-initial"),
        default="development",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "preflight":
        result = preflight(_parse_stage(args.stage))
    elif args.command == "run":
        result = run(_parse_stage(args.stage))
    elif args.command == "freeze":
        result = freeze_heuristic()
    elif args.command == "validate-locked":
        result = validate_locked()
    elif args.command == "prepare-conditional":
        result = prepare_conditional()
    elif args.command == "analyze":
        result = analyze()
    else:
        result = {"index": str(write_index())}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
