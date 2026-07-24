#!/usr/bin/env python3
"""Add and run shorter, parent-S-matched extension-study follow-ups."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import yaml

from .export_horncad import solved_s
from .report_extension_throat_angle_study import refresh_index
from .run_bem_search import run_search
from .run_extension_throat_angle_study import (
    NUMCALC_PROCESSES,
    QUEUE_WORKERS,
    ROOT,
    STUDY_ROOT,
    _content_hash,
    _materialize,
    _read_json,
    _verify_manifest,
    _write_json,
)
from .run_stage_aware_bem_queue import run_queue, validate_queue


STAGE = "s-matched-followup"
CANDIDATE_COUNT = 6
MINIMUM_EXTENDED_COUNT = 2
MANIFEST = STUDY_ROOT / "manifest.json"
RUNTIME = STUDY_ROOT / f"runtime-{STAGE}.json"
PREFLIGHT = STUDY_ROOT / f"preflight-{STAGE}.json"


def _parent(manifest: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    cell = f"{row['coverage_deg']}deg-{row['round_mouth_diameter_mm']}mm"
    return manifest["parents"][row["parent_role"]][cell]


def _candidate_state(
    manifest: dict[str, Any],
    row: dict[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    search = ROOT / manifest["inputs"][row["id"]]["search"]
    state = _read_json(search.parent / "search_state.json")
    records = state.get("candidates", [])
    record = records[0] if isinstance(records, list) and records else {}
    return search, state, record


def _eligible_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    eligible = []
    for row in manifest["coordinates"]:
        if row["stage"] not in {"primary-development", "secondary-transfer"}:
            continue
        search, _, record = _candidate_state(manifest, row)
        if record.get("status") != "complete":
            continue
        surface = (
            (record.get("surface_diagnostics") or {}).get("score") or {}
        ).get("overall_percent")
        parent = _parent(manifest, row)
        project = yaml.safe_load(
            (search.parent / "project.yaml").read_text(encoding="utf-8"))
        candidate_s = float(
            project["horncad_config"]["horizontal_basis"]["solved_s"])
        parent_s = float(parent["s"])
        if (not isinstance(surface, (int, float))
                or float(surface) >= float(row["parent_surface_score"])
                or candidate_s >= parent_s - 1e-9):
            continue
        eligible.append({
            **row,
            "source_coordinate_id": row["id"],
            "source_surface_score": float(surface),
            "surface_delta_points": (
                float(surface) - float(row["parent_surface_score"])),
            "source_derived_s": candidate_s,
            "parent_s": parent_s,
            "source_project": str(
                (search.parent / "project.yaml").relative_to(ROOT)),
        })
    return sorted(
        eligible,
        key=lambda item: (item["surface_delta_points"], item["id"]),
    )


def select_followups(
    eligible: list[dict[str, Any]],
    count: int = CANDIDATE_COUNT,
    minimum_extended: int = MINIMUM_EXTENDED_COUNT,
) -> list[dict[str, Any]]:
    """Select worst low-S losses while retaining nonzero-extension evidence."""
    extended = [row for row in eligible if float(row["extension_mm"]) > 0]
    selected = extended[:minimum_extended]
    selected_ids = {row["id"] for row in selected}
    for row in eligible:
        if row["id"] in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(row["id"])
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError(
            f"need {count} eligible low-S surface losses; found {len(selected)}")
    return sorted(
        selected,
        key=lambda item: (item["surface_delta_points"], item["id"]),
    )


def solve_parent_s_length(
    *,
    original_length_mm: float,
    effective_throat_radius_mm: float,
    coverage_deg: float,
    k: float,
    n: float,
    mouth_radius_mm: float,
    throat_angle_deg: float,
    target_s: float,
) -> float:
    """Solve the shorter OSSE length that restores the measured parent S."""
    def error(length: float) -> float:
        return solved_s(
            length,
            effective_throat_radius_mm,
            coverage_deg,
            k,
            n,
            mouth_radius_mm,
            throat_angle_deg,
        ) - target_s

    upper = float(original_length_mm)
    if error(upper) >= 0:
        raise ValueError("S-matched follow-up does not require a shorter length")
    lower = upper * 0.5
    while lower > 5.0 and error(lower) <= 0:
        lower *= 0.5
    if error(lower) <= 0:
        raise ValueError("could not bracket a shorter parent-S length")
    for _ in range(80):
        middle = 0.5 * (lower + upper)
        if error(middle) > 0:
            lower = middle
        else:
            upper = middle
    length = 0.5 * (lower + upper)
    if not 0 < length < original_length_mm:
        raise ValueError("invalid S-matched length")
    return length


def prepare_followup() -> dict[str, Any]:
    manifest = _verify_manifest()
    existing = manifest.get("s_matched_followup")
    if isinstance(existing, dict) and existing.get("candidate_count"):
        return existing

    selected = select_followups(_eligible_rows(manifest))
    rows = []
    for source in selected:
        parent = _parent(manifest, source)
        source_project = yaml.safe_load(
            (ROOT / source["source_project"]).read_text(encoding="utf-8"))
        global_config = source_project["horncad_config"]["global"]
        length = solve_parent_s_length(
            original_length_mm=float(parent["length_mm"]),
            effective_throat_radius_mm=float(
                global_config["effective_throat_radius"]),
            coverage_deg=float(source["coverage_deg"]),
            k=float(parent["k"]),
            n=float(parent["n"]),
            mouth_radius_mm=0.5 * float(source["round_mouth_diameter_mm"]),
            throat_angle_deg=float(source["throat_angle_deg"]),
            target_s=float(parent["s"]),
        )
        rows.append({
            "id": f"{source['id']}-Sparent",
            "stage": STAGE,
            "coverage_deg": source["coverage_deg"],
            "round_mouth_diameter_mm": source["round_mouth_diameter_mm"],
            "parent_role": source["parent_role"],
            "throat_angle_deg": source["throat_angle_deg"],
            "extension_mm": source["extension_mm"],
            "length_mm": length,
            "outcome_access": "exploratory-development",
            "source_coordinate_id": source["source_coordinate_id"],
            "source_surface_score": source["source_surface_score"],
            "source_surface_delta_points": source["surface_delta_points"],
            "source_derived_s": source["source_derived_s"],
            "target_parent_s": source["parent_s"],
            "original_parent_length_mm": float(parent["length_mm"]),
            "length_reduction_mm": float(parent["length_mm"]) - length,
            "length_reduction_percent": (
                (float(parent["length_mm"]) - length)
                / float(parent["length_mm"]) * 100.0),
        })

    materialized = _materialize(rows, manifest["parents"])
    for row in materialized["coordinates"]:
        if abs(float(row["derived_s"]) - float(row["target_parent_s"])) > 1e-6:
            raise ValueError(f"{row['id']}: materialized S misses parent target")

    previous_freeze = manifest["freeze_sha256"]
    manifest["coordinates"].extend(materialized["coordinates"])
    manifest["inputs"].update(materialized["inputs"])
    manifest["candidate_count"] = len(manifest["coordinates"])
    manifest["hard_candidate_cap"] = int(manifest["hard_candidate_cap"]) + len(rows)
    manifest.setdefault("counts", {})[STAGE] = len(rows)
    manifest["s_matched_followup"] = {
        "schema_version": 1,
        "status": "preflight",
        "candidate_count": len(rows),
        "minimum_nonzero_extension_cases": MINIMUM_EXTENDED_COUNT,
        "selection_rule": (
            "six worst completed surface losses with derived S below the "
            "measured parent S; reserve two cases for nonzero extension"),
        "previous_freeze_sha256": previous_freeze,
        "source_coordinate_ids": [
            row["source_coordinate_id"] for row in rows],
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
    manifest["freeze_sha256"] = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    _write_json(MANIFEST, manifest)

    paths = [
        ROOT / materialized["inputs"][row["id"]]["search"]
        for row in materialized["coordinates"]
    ]
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        if state.get("status") != "preflight":
            raise ValueError(f"follow-up preflight failed: {path}")
    preflight = {
        "schema_version": 1,
        "stage": STAGE,
        "candidate_count": len(paths),
        "scheduler": scheduler,
        "searches": [str(path.relative_to(ROOT)) for path in paths],
    }
    _write_json(PREFLIGHT, preflight)
    refresh_index(STUDY_ROOT)
    return manifest["s_matched_followup"]


def _development_finished() -> bool:
    runtime = _read_json(
        STUDY_ROOT / "runtime-primary-development-secondary-transfer.json")
    return bool(runtime) and runtime.get("status") != "running"


def run_followup(*, wait_for_development: bool = False) -> dict[str, Any]:
    if wait_for_development:
        while not _development_finished():
            time.sleep(30.0)
    elif not _development_finished():
        raise RuntimeError("development queue is still running")
    prepare_followup()
    manifest = _verify_manifest()
    paths = [
        ROOT / manifest["inputs"][row["id"]]["search"]
        for row in manifest["coordinates"] if row["stage"] == STAGE
    ]
    manifest["s_matched_followup"]["status"] = "running"
    manifest["freeze_sha256"] = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    _write_json(MANIFEST, manifest)
    refresh_index(STUDY_ROOT)
    result = run_queue(
        paths,
        RUNTIME,
        queue_workers=QUEUE_WORKERS,
        numcalc_processes=NUMCALC_PROCESSES,
    )
    manifest = _read_json(MANIFEST)
    manifest["s_matched_followup"]["status"] = result["status"]
    manifest["freeze_sha256"] = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    _write_json(MANIFEST, manifest)
    refresh_index(STUDY_ROOT)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "run", "prepare-and-run"))
    parser.add_argument("--wait-for-development", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_followup()
    elif args.action == "run":
        result = run_followup(
            wait_for_development=args.wait_for_development)
    else:
        prepare_followup()
        result = run_followup(
            wait_for_development=args.wait_for_development)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
