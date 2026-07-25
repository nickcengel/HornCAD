#!/usr/bin/env python3
"""Prepare, run, and analyze the fixed non-round transfer study."""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
from statistics import median
import threading
import time
from typing import Any

import yaml

from app.design_api import DesignIntent, RoundControlHeuristics

from .run_bem_search import materialize_candidate, run_search
from .run_stage_aware_bem_queue import run_queue, validate_queue


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/non-round-transfer-study"
HEURISTICS = ROOT / "models/round_control_heuristics_v1"
BASE_PROJECT = (
    ROOT / "examples/control-decoupling/searches/core-axis/40deg/350x350"
    / "candidates/candidate-000/project.yaml")
DEVELOPMENT_MANIFEST = STUDY_ROOT / "development_manifest.json"
DEVELOPMENT_RESULTS = STUDY_ROOT / "development_results.json"
PREFERENCE = STUDY_ROOT / "preferred_length_rule.json"
LOCKED_MANIFEST = STUDY_ROOT / "locked_manifest.json"
LOCKED_RESULTS = STUDY_ROOT / "locked_results.json"
CLOSURE_MANIFEST = STUDY_ROOT / "closure_manifest.json"
RESULTS = STUDY_ROOT / "results.json"
QUEUE_WORKERS = 8
NUMCALC_PROCESSES = 20
EPSILON = 1e-6

EQUAL_SQUARE = (
    ("Q1", 250, 30),
    ("Q2", 250, 50),
    ("Q3", 450, 30),
    ("Q4", 450, 50),
    ("Q5", 300, 35),
    ("Q6", 350, 40),
    ("Q7", 400, 45),
    ("Q8", 450, 40),
)
DEVELOPMENT_INTENTS = (
    ("D1", 400, 280, 50, 35, "primary-anchor"),
    ("D2", 360, 252, 50, 35, "smaller-scale"),
    ("D3", 450, 315, 50, 35, "larger-scale"),
    ("D4", 450, 250, 45, 35, "high-aspect"),
    ("D5", 400, 320, 45, 35, "moderate-aspect"),
    ("D6", 400, 280, 40, 40, "equal-coverage-anisotropy"),
    ("D7", 350, 300, 35, 45, "reversed-unequal-coverage"),
)
LOCKED_INTENTS = (
    ("L1", 350, 250, 50, 35, "near-anchor"),
    ("L2", 450, 350, 50, 35, "large-unequal-aperture"),
    ("L3", 400, 250, 45, 30, "high-aspect-lower-v-coverage"),
    ("L4", 450, 300, 40, 40, "equal-coverage-anisotropy"),
    ("L5", 400, 350, 35, 45, "reversed-coverage"),
    ("L6", 300, 400, 35, 50, "portrait-orientation"),
)
SHAPES = ("elliptical", "square")
LENGTH_RULES = ("weighted", "s-balanced")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _verify_manifest(path: Path, expected_count: int | None = None) -> dict[str, Any]:
    manifest = _read_json(path)
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError(f"manifest freeze hash changed: {path}")
    if (expected_count is not None
            and int(manifest["candidate_count"]) != expected_count):
        raise ValueError(f"candidate count changed: {path}")
    for item in manifest["inputs"].values():
        for kind in ("project", "search"):
            source = ROOT / item[kind]
            if _file_hash(source) != item[f"{kind}_sha256"]:
                raise ValueError(f"frozen input changed: {source}")
    return manifest


def _heuristics() -> RoundControlHeuristics:
    return RoundControlHeuristics.load(HEURISTICS)


def _axis_score(rules: RoundControlHeuristics, source_cell: str) -> float:
    return float(
        rules.artifact["active_measured_cell_seeds"][source_cell][
            "surface_score_v2_3"])


def common_lengths(
    rules: RoundControlHeuristics,
    intent: DesignIntent,
) -> dict[str, float]:
    seed = rules.recommend(intent)
    weighted = float(seed.flat_profile_length_mm)
    h = seed.horizontal
    v = seed.vertical
    if math.isclose(
            h.profile_length_mm, v.profile_length_mm, abs_tol=1e-12):
        balanced = h.profile_length_mm
    else:
        h_target = rules._s_at_length(
            h.mouth_mm, h.coverage_deg, h.profile_length_mm, h.k, h.n)
        v_target = rules._s_at_length(
            v.mouth_mm, v.coverage_deg, v.profile_length_mm, v.k, v.n)

        def residual(length: float) -> float:
            h_s = rules._s_at_length(
                h.mouth_mm, h.coverage_deg, length, h.k, h.n)
            v_s = rules._s_at_length(
                v.mouth_mm, v.coverage_deg, length, v.k, v.n)
            if min(h_target, v_target) <= 0.0:
                raise ValueError(
                    "independent axis seed has nonpositive derived S")
            if min(h_s, v_s) <= 0.0:
                # S decreases monotonically with common length. The log-space
                # residual tends to -infinity at the positive-S boundary, so
                # this remains a valid upper bracket without evaluating log(0).
                return -math.inf
            return (
                intent.mouth_width_mm*math.log(h_s/h_target)
                + intent.mouth_height_mm*math.log(v_s/v_target)
            )

        low = min(h.profile_length_mm, v.profile_length_mm)
        high = max(h.profile_length_mm, v.profile_length_mm)
        low_value, high_value = residual(low), residual(high)
        if low_value*high_value > 0.0:
            raise ValueError("independent axis lengths do not bracket S balance")
        for _ in range(80):
            middle = (low+high)/2.0
            value = residual(middle)
            if low_value*value <= 0.0:
                high, high_value = middle, value
            else:
                low, low_value = middle, value
        balanced = (low+high)/2.0
    return {"weighted": weighted, "s-balanced": float(balanced)}


def _fixed_search(
    coordinate_id: str,
    values: dict[str, float],
    coverage_h: float,
    coverage_v: float,
) -> dict[str, Any]:
    bounds = {
        name: [float(value)-EPSILON, float(value)+EPSILON]
        for name, value in values.items()
    }
    return {
        "bem_candidate_search": {
            "version": 1,
            "seed_yaml": "project.yaml",
            "intended_coverage_h_deg": float(coverage_h),
            "intended_coverage_v_deg": float(coverage_v),
            "lower_frequency_hz": 500.0,
            "crossover_hz": 750.0,
            "upper_frequency_hz": 8000.0,
            "max_evaluations": 1,
            "initial_candidates": 0,
            "minimum_candidate_distance": 0.001,
            "derived_s_bounds": [0.0, 4.0],
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
            "non_round_transfer_study": {
                "study_id": "non-round-transfer-study-v1",
                "coordinate_id": coordinate_id,
            },
        }
    }


def _candidate(
    coordinate_id: str,
    intent: DesignIntent,
    shape: str,
    length_rule: str,
    length_mm: float,
    *,
    phase: str,
    purpose: str,
    source_intent_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rules = _heuristics()
    seed = rules.recommend(intent)
    source = yaml.safe_load(BASE_PROJECT.read_text(encoding="utf-8"))
    config = source["horncad_config"]
    global_config = config["global"]
    global_config.update({
        "mouth_width": float(intent.mouth_width_mm),
        "mouth_height": float(intent.mouth_height_mm),
        "throat_angle_deg": 6.0,
        "conical_extension_length": 0.0,
        "mouth_sag": 0.0,
        "mouth_sag_h_enabled": False,
        "mouth_sag_v_enabled": False,
    })
    config["section_modifier"]["mouth_squareness"] = (
        0.0 if shape == "elliptical" else 1.0)
    values = {
        "length_mm": float(length_mm),
        "extension_mm": 0.0,
        "osse_coverage_h_deg": float(intent.horizontal_coverage_deg),
        "osse_coverage_v_deg": float(intent.vertical_coverage_deg),
        "k_h": float(seed.k_horizontal),
        "k_v": float(seed.k_vertical),
        "n_h": float(seed.n_horizontal),
        "n_v": float(seed.n_vertical),
    }
    search = _fixed_search(
        coordinate_id, values,
        intent.horizontal_coverage_deg, intent.vertical_coverage_deg)
    project, derived = materialize_candidate(
        copy.deepcopy(source), values, search["bem_candidate_search"])
    reference_score = (
        intent.mouth_width_mm*_axis_score(rules, seed.horizontal.source_cell)
        + intent.mouth_height_mm*_axis_score(rules, seed.vertical.source_cell)
    )/(intent.mouth_width_mm+intent.mouth_height_mm)
    row = {
        "id": coordinate_id,
        "phase": phase,
        "purpose": purpose,
        "source_intent_id": source_intent_id,
        "mouth_width_mm": float(intent.mouth_width_mm),
        "mouth_height_mm": float(intent.mouth_height_mm),
        "horizontal_coverage_deg": float(intent.horizontal_coverage_deg),
        "vertical_coverage_deg": float(intent.vertical_coverage_deg),
        "throat_angle_deg": 6.0,
        "shape": shape,
        "mouth_squareness": 0.0 if shape == "elliptical" else 1.0,
        "sag_axes": "none",
        "sag_mm": 0.0,
        "extension_mm": 0.0,
        "length_rule": length_rule,
        "length_mm": float(length_mm),
        "k_h": values["k_h"],
        "k_v": values["k_v"],
        "n_h": values["n_h"],
        "n_v": values["n_v"],
        "s_h": float(derived["s_h"]),
        "s_v": float(derived["s_v"]),
        "horizontal_source_cell": seed.horizontal.source_cell,
        "vertical_source_cell": seed.vertical.source_cell,
        "independent_horizontal_length_mm":
            float(seed.horizontal.profile_length_mm),
        "independent_vertical_length_mm":
            float(seed.vertical.profile_length_mm),
        "independent_axis_reference_surface_v2_3": float(reference_score),
    }
    search["bem_candidate_search"]["non_round_transfer_study"].update({
        "phase": phase,
        "shape": shape,
        "length_rule": length_rule,
        "source_intent_id": source_intent_id,
    })
    return project, search, row


def _write_coordinate(
    row: dict[str, Any],
    project: dict[str, Any],
    search: dict[str, Any],
) -> dict[str, str]:
    directory = STUDY_ROOT / "searches" / row["id"]
    project_path = directory / "project.yaml"
    search_path = directory / "search.yaml"
    _write_yaml(project_path, project)
    _write_yaml(search_path, search)
    return {
        "project": str(project_path.relative_to(ROOT)),
        "project_sha256": _file_hash(project_path),
        "search": str(search_path.relative_to(ROOT)),
        "search_sha256": _file_hash(search_path),
    }


def _manifest(
    study_id: str,
    phase: str,
    rows: list[dict[str, Any]],
    inputs: dict[str, Any],
    cap: int,
    **metadata: Any,
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "study_id": study_id,
        "phase": phase,
        "status": "prepared-not-run",
        "candidate_count": len(rows),
        "phase_candidate_cap": cap,
        "scheduler": {
            "type": "stage-aware",
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
            "search_sharding": "one fixed candidate per search",
        },
        "fixed_geometry": {
            "extension_mm": 0,
            "sag_axes": "none",
            "sag_mm": 0,
            "throat_angle_deg": 6,
            "intended_equals_osse_coverage": True,
            "surface_score_version": "v2.3",
            "throat_impedance_version": "2.3.0",
        },
        "coordinates": rows,
        "inputs": inputs,
        **metadata,
    }
    value["coordinate_sha256"] = _content_hash(rows)
    value["freeze_sha256"] = _content_hash(value)
    return value


def prepare_development() -> dict[str, Any]:
    if DEVELOPMENT_MANIFEST.exists():
        raise FileExistsError(DEVELOPMENT_MANIFEST)
    rules = _heuristics()
    rows: list[dict[str, Any]] = []
    inputs = {}
    for intent_id, mouth, coverage in EQUAL_SQUARE:
        intent = DesignIntent.round(mouth, coverage)
        axis = rules.axis_length(mouth, coverage)
        candidate_id = f"{intent_id.lower()}-equal-square"
        project, search, row = _candidate(
            candidate_id, intent, "square", "independent-equal",
            axis.profile_length_mm, phase="development",
            purpose="equal-HV-corner-transform",
            source_intent_id=intent_id)
        row["round_parent"] = copy.deepcopy(
            rules.artifact["active_measured_cell_seeds"][axis.source_cell])
        rows.append(row)
        inputs[candidate_id] = _write_coordinate(row, project, search)
    for item in DEVELOPMENT_INTENTS:
        intent_id, width, height, coverage_h, coverage_v, purpose = item
        intent = DesignIntent(width, height, coverage_h, coverage_v)
        lengths = common_lengths(rules, intent)
        for shape in SHAPES:
            for length_rule in LENGTH_RULES:
                candidate_id = (
                    f"{intent_id.lower()}-{shape}-{length_rule}")
                project, search, row = _candidate(
                    candidate_id, intent, shape, length_rule,
                    lengths[length_rule], phase="development",
                    purpose=purpose, source_intent_id=intent_id)
                row["common_lengths_mm"] = lengths
                rows.append(row)
                inputs[candidate_id] = _write_coordinate(row, project, search)
    if len(rows) != 36:
        raise ValueError("development must contain 36 candidates")
    manifest = _manifest(
        "non-round-transfer-development-v1", "development",
        rows, inputs, 36,
        allocation={
            "equal_hv_square": 8,
            "unequal_hv": 28,
            "absolute_study_cap": 64,
        },
        heuristic_sha256=_file_hash(HEURISTICS / "heuristics.json"),
        selection_rule={
            "response": "surface_score_v2_3",
            "comparison": "median paired s-balanced minus weighted",
            "weighted_tie_window_points": 0.5,
        },
    )
    _write_json(DEVELOPMENT_MANIFEST, manifest)
    refresh_index()
    return manifest


def _search_paths(manifest: dict[str, Any]) -> list[Path]:
    return [ROOT / manifest["inputs"][row["id"]]["search"]
            for row in manifest["coordinates"]]


def preflight(path: Path, expected_count: int | None = None) -> dict[str, Any]:
    manifest = _verify_manifest(path, expected_count)
    paths = _search_paths(manifest)
    scheduler = (
        validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
        if paths else {
            "search_count": 0,
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
            "configured_workers": {},
        }
    )
    statuses = []
    for search_path in paths:
        state = run_search(
            search_path, search_path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        status = (
            state.get("status") == "preflight"
            and len(candidates) == 1
            and candidates[0].get("status") == "preflight"
        )
        if not status:
            raise ValueError(f"geometry preflight failed: {search_path}")
        statuses.append(str(search_path.relative_to(ROOT)))
    result = {
        "schema_version": 1,
        "status": "passed",
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": statuses,
    }
    _write_json(STUDY_ROOT / f"{manifest['phase']}_preflight.json", result)
    refresh_index()
    return result


def run_phase(path: Path, expected_count: int | None = None) -> dict[str, Any]:
    manifest = _verify_manifest(path, expected_count)
    preflight_path = STUDY_ROOT / f"{manifest['phase']}_preflight.json"
    if not preflight_path.is_file():
        raise ValueError(f"phase has not passed preflight: {manifest['phase']}")
    pending = []
    for search_path in _search_paths(manifest):
        state_path = search_path.parent / "search_state.json"
        state = _read_json(state_path) if state_path.is_file() else {}
        if state.get("status") != "complete":
            pending.append(search_path)
    if not pending:
        all_paths = _search_paths(manifest)
        result = {
            "schema_version": 1,
            "status": "complete",
            "scheduler": (
                validate_queue(
                    all_paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
                if all_paths else {
                    "search_count": 0,
                    "queue_workers": QUEUE_WORKERS,
                    "numcalc_process_capacity": NUMCALC_PROCESSES,
                    "configured_workers": {},
                }
            ),
            "events": [],
            "reused_complete_search_count": len(all_paths),
        }
        _write_json(
            STUDY_ROOT / f"{manifest['phase']}_runtime.json", result)
        refresh_index()
        return result
    stop_refresh = threading.Event()

    def refresh_while_running() -> None:
        while not stop_refresh.wait(3):
            refresh_index()

    refresher = threading.Thread(
        target=refresh_while_running,
        name=f"{manifest['phase']}-index-refresher",
        daemon=True,
    )
    refresher.start()
    try:
        return run_queue(
            pending,
            STUDY_ROOT / f"{manifest['phase']}_runtime.json",
            queue_workers=QUEUE_WORKERS,
            numcalc_processes=NUMCALC_PROCESSES,
            on_event=lambda _event: refresh_index(),
        )
    finally:
        stop_refresh.set()
        refresher.join()
        refresh_index()


def _measured(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for coordinate in manifest["coordinates"]:
        search = ROOT / manifest["inputs"][coordinate["id"]]["search"]
        state = _read_json(search.parent / "search_state.json")
        if state.get("status") != "complete":
            raise ValueError(f"incomplete coordinate: {coordinate['id']}")
        record = state["candidates"][0]
        surface = record["surface_diagnostics"]["score"]
        impedance = record["throat_impedance_diagnostics"]
        if (surface.get("version") != "v2.3"
                or impedance.get("diagnostic_version") != "2.3.0"):
            raise ValueError(f"stale diagnostics: {coordinate['id']}")
        response = (
            search.parent / "candidates" / record["id"]
            / "bem" / "responses.npz")
        reports = sorted(response.parent.glob("*_Report.html"))
        rows.append({
            **coordinate,
            "surface_score_v2_3": float(surface["overall_percent"]),
            "throat_impedance_score_v2_3_0":
                float(impedance["overall_percent"]),
            "surface_reference_delta_points": (
                float(surface["overall_percent"])
                - coordinate["independent_axis_reference_surface_v2_3"]
            ),
            "response_path": str(response.relative_to(ROOT)),
            "response_sha256": _file_hash(response),
            "report_path": str((
                reports[0] if reports else search.parent / "search_report.html"
            ).relative_to(ROOT)),
        })
    return rows


def analyze_development() -> dict[str, Any]:
    manifest = _verify_manifest(DEVELOPMENT_MANIFEST, 36)
    evidence = _measured(manifest)
    unequal = [
        row for row in evidence
        if row["purpose"] != "equal-HV-corner-transform"
    ]
    pairs = []
    for intent_id, *_rest in DEVELOPMENT_INTENTS:
        for shape in SHAPES:
            rows = [
                row for row in unequal
                if row["source_intent_id"] == intent_id
                and row["shape"] == shape
            ]
            by_rule = {row["length_rule"]: row for row in rows}
            pairs.append({
                "intent_id": intent_id,
                "shape": shape,
                "s_balanced_minus_weighted_surface_points": (
                    by_rule["s-balanced"]["surface_score_v2_3"]
                    - by_rule["weighted"]["surface_score_v2_3"]
                ),
                "weighted": by_rule["weighted"],
                "s-balanced": by_rule["s-balanced"],
            })
    differences = [
        row["s_balanced_minus_weighted_surface_points"] for row in pairs
    ]
    paired_median = float(median(differences))
    preferred = (
        "weighted" if abs(paired_median) <= 0.5
        else "s-balanced" if paired_median > 0.0 else "weighted"
    )
    preference = {
        "schema_version": 1,
        "status": "frozen-from-development",
        "preferred_length_rule": preferred,
        "alternate_length_rule": (
            "s-balanced" if preferred == "weighted" else "weighted"),
        "paired_comparison_count": len(pairs),
        "s_balanced_minus_weighted_median_surface_points": paired_median,
        "s_balanced_win_count": sum(value > 0.0 for value in differences),
        "weighted_win_count": sum(value < 0.0 for value in differences),
        "tie_count": sum(math.isclose(value, 0.0, abs_tol=1e-12)
                         for value in differences),
        "tie_window_points": 0.5,
        "selection_rule": (
            "weighted wins when the paired median lies within ±0.5 point; "
            "otherwise the sign of the paired median selects the rule"
        ),
        "development_coordinate_sha256": manifest["coordinate_sha256"],
    }
    preference["content_sha256"] = _content_hash(preference)
    result = {
        "schema_version": 1,
        "status": "complete",
        "candidate_count": len(evidence),
        "equal_hv_square_count": sum(
            row["purpose"] == "equal-HV-corner-transform"
            for row in evidence),
        "unequal_hv_count": len(unequal),
        "preference": preference,
        "length_pairs": pairs,
        "evidence": evidence,
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(DEVELOPMENT_RESULTS, result)
    _write_json(PREFERENCE, preference)
    refresh_index()
    return result


def prepare_locked() -> dict[str, Any]:
    if LOCKED_MANIFEST.exists():
        raise FileExistsError(LOCKED_MANIFEST)
    preference = _read_json(PREFERENCE)
    preferred = preference["preferred_length_rule"]
    rules = _heuristics()
    rows = []
    inputs = {}
    for item in LOCKED_INTENTS:
        intent_id, width, height, coverage_h, coverage_v, purpose = item
        intent = DesignIntent(width, height, coverage_h, coverage_v)
        lengths = common_lengths(rules, intent)
        for shape in SHAPES:
            candidate_id = f"{intent_id.lower()}-{shape}-{preferred}"
            project, search, row = _candidate(
                candidate_id, intent, shape, preferred, lengths[preferred],
                phase="locked", purpose=purpose,
                source_intent_id=intent_id)
            row["common_lengths_mm"] = lengths
            rows.append(row)
            inputs[candidate_id] = _write_coordinate(row, project, search)
    if len(rows) != 12:
        raise ValueError("locked phase must contain 12 candidates")
    manifest = _manifest(
        "non-round-transfer-locked-v1", "locked", rows, inputs, 12,
        preferred_length_rule=preferred,
        preference_sha256=_file_hash(PREFERENCE),
        failure_rule={
            "maximum_deficit_points": -3.0,
            "intent_score": "better measured elliptical/square surface v2.3",
            "reference": "width/height-weighted independent-axis score",
            "maximum_closure_intents": 4,
        },
    )
    _write_json(LOCKED_MANIFEST, manifest)
    refresh_index()
    return manifest


def analyze_locked() -> dict[str, Any]:
    manifest = _verify_manifest(LOCKED_MANIFEST, 12)
    evidence = _measured(manifest)
    intents = {}
    failed = []
    for intent_id, *_rest in LOCKED_INTENTS:
        rows = [row for row in evidence if row["source_intent_id"] == intent_id]
        reference = float(rows[0]["independent_axis_reference_surface_v2_3"])
        best = max(rows, key=lambda row: row["surface_score_v2_3"])
        deficit = float(best["surface_score_v2_3"]-reference)
        value = {
            "reference_surface_v2_3": reference,
            "best_candidate_id": best["id"],
            "best_surface_v2_3": best["surface_score_v2_3"],
            "best_minus_reference_points": deficit,
            "failed_transfer": deficit < -3.0,
            "candidates": rows,
        }
        intents[intent_id] = value
        if value["failed_transfer"]:
            failed.append({"intent_id": intent_id, "deficit_points": deficit})
    selected = sorted(
        failed, key=lambda row: (row["deficit_points"], row["intent_id"]))[:4]
    result = {
        "schema_version": 1,
        "status": "complete",
        "candidate_count": len(evidence),
        "failed_intent_count": len(failed),
        "closure_selected_intents": selected,
        "intents": intents,
        "evidence": evidence,
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(LOCKED_RESULTS, result)
    refresh_index()
    return result


def prepare_closure() -> dict[str, Any]:
    if CLOSURE_MANIFEST.exists():
        raise FileExistsError(CLOSURE_MANIFEST)
    locked = _read_json(LOCKED_RESULTS)
    preference = _read_json(PREFERENCE)
    preferred = preference["preferred_length_rule"]
    alternate = preference["alternate_length_rule"]
    rules = _heuristics()
    selected = {
        row["intent_id"] for row in locked["closure_selected_intents"]
    }
    rows = []
    inputs = {}
    for item in LOCKED_INTENTS:
        intent_id, width, height, coverage_h, coverage_v, purpose = item
        if intent_id not in selected:
            continue
        intent = DesignIntent(width, height, coverage_h, coverage_v)
        lengths = common_lengths(rules, intent)
        constructions = (
            ("elliptical", alternate, lengths[alternate], "alternate-ellipse"),
            ("square", alternate, lengths[alternate], "alternate-square"),
            ("square", "preferred-short-0.9", lengths[preferred]*0.9,
             "square-short-bracket"),
            ("square", "preferred-long-1.1", lengths[preferred]*1.1,
             "square-long-bracket"),
        )
        for shape, rule, length, suffix in constructions:
            candidate_id = f"{intent_id.lower()}-closure-{suffix}"
            project, search, row = _candidate(
                candidate_id, intent, shape, rule, length,
                phase="closure", purpose=purpose,
                source_intent_id=intent_id)
            row["preferred_length_rule"] = preferred
            row["alternate_length_rule"] = alternate
            rows.append(row)
            inputs[candidate_id] = _write_coordinate(row, project, search)
    if len(rows) > 16 or len(rows) != 4*len(selected):
        raise ValueError("conditional closure exceeds registered allocation")
    manifest = _manifest(
        "non-round-transfer-closure-v1", "closure", rows, inputs, 16,
        selected_intents=sorted(selected),
        preferred_length_rule=preferred,
        alternate_length_rule=alternate,
        conditional_candidate_count=len(rows),
        absolute_study_cap=64,
    )
    _write_json(CLOSURE_MANIFEST, manifest)
    refresh_index()
    return manifest


def analyze_final() -> dict[str, Any]:
    development = _read_json(DEVELOPMENT_RESULTS)
    locked = _read_json(LOCKED_RESULTS)
    closure_manifest = _verify_manifest(CLOSURE_MANIFEST)
    closure_evidence = (
        _measured(closure_manifest) if closure_manifest["coordinates"] else [])
    preference = _read_json(PREFERENCE)
    total_new = (
        development["candidate_count"]+locked["candidate_count"]
        + len(closure_evidence)
    )
    if total_new > 64:
        raise ValueError("absolute study cap exceeded")
    equal_rows = [
        row for row in development["evidence"]
        if row["purpose"] == "equal-HV-corner-transform"
    ]
    corner_deltas = [
        row["surface_score_v2_3"]-row["round_parent"]["surface_score_v2_3"]
        for row in equal_rows
    ]
    result = {
        "schema_version": 1,
        "study_id": "non-round-transfer-study-v1",
        "status": "complete",
        "initial_candidate_count": 48,
        "conditional_candidate_count": len(closure_evidence),
        "total_new_simulation_count": total_new,
        "absolute_simulation_cap": 64,
        "preferred_length_rule": preference["preferred_length_rule"],
        "length_preference": preference,
        "equal_hv_square_summary": {
            "candidate_count": len(equal_rows),
            "median_surface_delta_from_round_points":
                float(median(corner_deltas)),
            "square_better_count": sum(value > 0.0 for value in corner_deltas),
            "cells": {
                row["source_intent_id"]: {
                    "surface_delta_from_round_points": (
                        row["surface_score_v2_3"]
                        - row["round_parent"]["surface_score_v2_3"]),
                    "candidate": row,
                }
                for row in equal_rows
            },
        },
        "locked_summary": {
            "failed_intent_count": locked["failed_intent_count"],
            "closure_selected_intents": locked["closure_selected_intents"],
            "intents": locked["intents"],
        },
        "development_evidence": development["evidence"],
        "locked_evidence": locked["evidence"],
        "closure_evidence": closure_evidence,
        "promotion": {
            "independent_hv_k_n": (
                "retain independent measured H/V K and N; never average axes"),
            "common_length_rule": preference["preferred_length_rule"],
            "square_corner_policy": (
                "use measured equal-H/V corner deltas and locked square "
                "responses as support warnings, not a global score correction"),
            "wider_first_round_intents": [
                row["intent_id"]
                for row in locked["closure_selected_intents"]
            ],
        },
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(RESULTS, result)
    refresh_index()
    return result


def _state_for(
    manifest: dict[str, Any], row: dict[str, Any],
) -> dict[str, Any]:
    search = ROOT / manifest["inputs"][row["id"]]["search"]
    state_path = search.parent / "search_state.json"
    if not state_path.is_file():
        return {"status": "planned", "surface": None, "impedance": None}
    state = _read_json(state_path)
    candidate = (state.get("candidates") or [{}])[0]
    surface = candidate.get("surface_diagnostics", {}).get("score", {})
    impedance = candidate.get("throat_impedance_diagnostics", {})
    return {
        "status": str(candidate.get(
            "status", state.get("status", "planned"))),
        "surface": (
            float(surface["overall_percent"])
            if surface.get("version") == "v2.3" else None),
        "impedance": (
            float(impedance["overall_percent"])
            if impedance.get("diagnostic_version") == "2.3.0" else None),
    }


def refresh_index() -> Path:
    phases = []
    for path in (DEVELOPMENT_MANIFEST, LOCKED_MANIFEST, CLOSURE_MANIFEST):
        if path.is_file():
            phases.append(_read_json(path))
    rows = []
    completed = 0
    total = 0
    for manifest in phases:
        for row in manifest["coordinates"]:
            measured = _state_for(manifest, row)
            status = measured["status"]
            completed += status == "complete"
            total += 1
            report = (
                STUDY_ROOT / "searches" / row["id"] / "search_report.html")
            label = (
                f"<a href='{html.escape(str(report.relative_to(STUDY_ROOT)))}'>"
                f"{html.escape(row['id'])}</a>"
                if report.is_file() else html.escape(row["id"])
            )
            surface_display = (
                "" if measured["surface"] is None
                else f"{measured['surface']:.4f}")
            impedance_display = (
                "" if measured["impedance"] is None
                else f"{measured['impedance']:.4f}")
            rows.append(
                "<tr>"
                f"<td data-sort-value='{html.escape(row['id'])}'>{label}</td>"
                f"<td>{html.escape(row['phase'])}</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{surface_display}</td>"
                f"<td>{impedance_display}</td>"
                f"<td data-sort-value='{row['mouth_width_mm'] * 1_000_000 + row['mouth_height_mm']:.6f}'>"
                f"{row['mouth_width_mm']:g}×{row['mouth_height_mm']:g}</td>"
                f"<td data-sort-value='{row['horizontal_coverage_deg'] * 1_000_000 + row['vertical_coverage_deg']:.6f}'>"
                f"{row['horizontal_coverage_deg']:g}×"
                f"{row['vertical_coverage_deg']:g}</td>"
                f"<td>{html.escape(row['shape'])}</td>"
                f"<td>{html.escape(row['length_rule'])}</td>"
                f"<td>{row['length_mm']:.3f}</td>"
                f"<td data-sort-value='{row['k_h'] * 1_000_000 + row['k_v']:.6f}'>"
                f"{row['k_h']:g}/{row['k_v']:g}</td>"
                f"<td data-sort-value='{row['n_h'] * 1_000_000 + row['n_v']:.6f}'>"
                f"{row['n_h']:g}/{row['n_v']:g}</td>"
                "</tr>"
            )
    preference = (
        _read_json(PREFERENCE).get("preferred_length_rule")
        if PREFERENCE.is_file() else "not selected")
    final = _read_json(RESULTS) if RESULTS.is_file() else None
    refresh = "" if final else "<meta http-equiv='refresh' content='5'>"
    updated = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    document = f"""<!doctype html>
<meta charset="utf-8">{refresh}<title>Non-round transfer study</title>
<style>
body{{font:15px system-ui,sans-serif;margin:20px;background:#10161d;color:#e8edf2}}
section{{background:#17212a;border:1px solid #34414c;border-radius:9px;padding:14px;margin:14px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}
th,td{{padding:7px 9px;border-bottom:1px solid #34414c;text-align:right}}
th{{background:#202c36;cursor:pointer;user-select:none}}
th::after{{content:" ↕";color:#83909b;font-size:.8em}}
th[aria-sort="ascending"]::after{{content:" ↑";color:#7bd7cb}}
th[aria-sort="descending"]::after{{content:" ↓";color:#7bd7cb}}
th:first-child,td:first-child{{text-align:left}}
a{{color:#7bd7cb}}code{{color:#f6c177}}
</style>
<h1>Non-round H/V and square-mouth transfer study</h1>
<section><strong>Progress:</strong> {completed}/{total} prepared coordinates
complete · <strong>preferred common length:</strong>
<code>{html.escape(str(preference))}</code> · <strong>hard cap:</strong> 64
· <strong>updated:</strong> <span id="updated-at">{html.escape(updated)}</span>
</section>
<section><table class="sortable"><thead><tr>
<th data-sort="text">Candidate</th><th data-sort="text">Phase</th>
<th data-sort="text">Status</th><th data-sort="number">Surface v2.3</th>
<th data-sort="number">Impedance v2.3.0</th>
<th data-sort="number">Mouth W×H</th>
<th data-sort="number">Coverage H×V</th><th data-sort="text">Shape</th>
<th data-sort="text">Length rule</th><th data-sort="number">Length</th>
<th data-sort="number">K H/V</th><th data-sort="number">N H/V</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody></table></section>
<script>
document.querySelectorAll("table.sortable th[data-sort]").forEach((header, column) => {{
  header.addEventListener("click", () => {{
    const table = header.closest("table");
    const body = table.tBodies[0];
    const direction = header.getAttribute("aria-sort") === "ascending" ? -1 : 1;
    table.querySelectorAll("th").forEach(item => item.removeAttribute("aria-sort"));
    header.setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");
    const kind = header.dataset.sort;
    const rows = Array.from(body.rows);
    rows.sort((left, right) => {{
      const aCell = left.cells[column];
      const bCell = right.cells[column];
      const aRaw = aCell.dataset.sortValue ?? aCell.textContent.trim();
      const bRaw = bCell.dataset.sortValue ?? bCell.textContent.trim();
      const comparison = kind === "number"
        ? (Number(aRaw) - Number(bRaw))
        : aRaw.localeCompare(bRaw, undefined, {{numeric: true, sensitivity: "base"}});
      return direction * comparison;
    }});
    rows.forEach(row => body.appendChild(row));
  }});
}});
</script>
"""
    STUDY_ROOT.mkdir(parents=True, exist_ok=True)
    path = STUDY_ROOT / "index.html"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(path)
    return path


def watch_index() -> Path:
    """Refresh the index while any prepared study phase is running."""
    runtime_paths = tuple(STUDY_ROOT.glob("*_runtime.json"))
    while True:
        path = refresh_index()
        running = any(
            _read_json(runtime).get("status") == "running"
            for runtime in runtime_paths
            if runtime.is_file()
        )
        if not running:
            return path
        time.sleep(3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "prepare-development", "preflight-development", "run-development",
        "analyze-development", "prepare-locked", "preflight-locked",
        "run-locked", "analyze-locked", "prepare-closure",
        "preflight-closure", "run-closure", "analyze", "index",
        "watch-index",
    ))
    args = parser.parse_args()
    if args.command == "prepare-development":
        result = prepare_development()
    elif args.command == "preflight-development":
        result = preflight(DEVELOPMENT_MANIFEST, 36)
    elif args.command == "run-development":
        result = run_phase(DEVELOPMENT_MANIFEST, 36)
    elif args.command == "analyze-development":
        result = analyze_development()
    elif args.command == "prepare-locked":
        result = prepare_locked()
    elif args.command == "preflight-locked":
        result = preflight(LOCKED_MANIFEST, 12)
    elif args.command == "run-locked":
        result = run_phase(LOCKED_MANIFEST, 12)
    elif args.command == "analyze-locked":
        result = analyze_locked()
    elif args.command == "prepare-closure":
        result = prepare_closure()
    elif args.command == "preflight-closure":
        result = preflight(CLOSURE_MANIFEST)
    elif args.command == "run-closure":
        result = run_phase(CLOSURE_MANIFEST)
    elif args.command == "analyze":
        result = analyze_final()
    elif args.command == "watch-index":
        result = {"index": str(watch_index().relative_to(ROOT))}
    else:
        result = {"index": str(refresh_index().relative_to(ROOT))}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
