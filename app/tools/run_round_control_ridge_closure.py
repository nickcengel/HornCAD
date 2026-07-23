#!/usr/bin/env python3
"""Prepare, run, and analyze the 48-case round ridge-closure study."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import yaml

from app.design_api import RoundControlHeuristics

from .round_control_model import (
    _content_hash, _digest_file, _normalize_numbers, _rescore,
    _solver_fingerprint, _validate_npz,
)
from .round_control_v2 import _source_project
from .run_bem_search import materialize_candidate, run_search


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/round-control-ridge-closure"
HEURISTICS = ROOT / "models/round_control_heuristics_v1"
MAX_CANDIDATES = 48
LENGTH_MULTIPLIERS = (0.9, 1.0, 1.1)
CELLS = (
    # coverage, mouth, outward K, N, branch
    (30, 250, 1.0, 4.0, "short-low-k"),
    (30, 300, 1.0, 4.0, "short-low-k"),
    (35, 250, 1.0, 8.0, "short-low-k"),
    (35, 300, 1.0, 8.0, "short-low-k"),
    (40, 250, 1.0, 8.0, "short-low-k"),
    (45, 250, 1.0, 8.0, "short-low-k"),
    (30, 400, 7.0, 8.0, "long-high-k"),
    (30, 450, 7.0, 8.0, "long-high-k"),
    (35, 400, 7.0, 8.0, "long-high-k"),
    (35, 450, 7.0, 8.0, "long-high-k"),
    (40, 350, 7.0, 8.0, "long-high-k"),
    (40, 450, 7.0, 8.0, "long-high-k"),
    (45, 300, 7.0, 8.0, "long-high-k"),
    (45, 450, 7.0, 8.0, "long-high-k"),
    (50, 300, 7.0, 8.0, "long-high-k"),
    (50, 450, 7.0, 8.0, "long-high-k"),
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


def _search_dir(coverage: int, mouth: int) -> Path:
    return STUDY_ROOT / "searches" / f"{coverage}deg" / f"{mouth}x{mouth}"


def _coordinate_id(coverage: int, mouth: int, k: float, n: float,
                   multiplier: float) -> str:
    multiplier_label = str(multiplier).replace(".", "p")
    return (
        f"ridge-{coverage}deg-{mouth}mm-K{k:g}-N{n:g}-"
        f"Lx{multiplier_label}"
    )


def _fixed_search(group: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    coverage = float(group["coverage_deg"])
    candidates = group["candidates"]

    def values(candidate: dict[str, Any]) -> dict[str, float]:
        return {
            "length_mm": float(candidate["length_mm"]),
            "extension_mm": 0.0,
            "osse_coverage_h_deg": coverage,
            "osse_coverage_v_deg": coverage,
            "k_h": float(group["k"]),
            "k_v": float(group["k"]),
            "n_h": float(group["n"]),
            "n_v": float(group["n"]),
        }

    seed_values = values(candidates[0])
    pools = [
        {
            "label": candidate["id"],
            "values": values(candidate),
        }
        for candidate in candidates[1:]
    ]
    all_values = [values(candidate) for candidate in candidates]
    bounds = {
        name: [
            min(item[name] for item in all_values)
            - max(1e-6, abs(min(item[name] for item in all_values)) * 1e-9),
            max(item[name] for item in all_values)
            + max(1e-6, abs(max(item[name] for item in all_values)) * 1e-9),
        ]
        for name in seed_values
    }
    search = {
        "version": 1,
        "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage,
        "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": 500.0,
        "crossover_hz": 750.0,
        "upper_frequency_hz": 8000.0,
        "max_evaluations": len(candidates),
        "initial_candidates": len(pools),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.049, 4.001],
        "sampling_stability_points": 2.0,
        "confirmation_points_per_octave": 16.0,
        "adaptive_pruning": {"enabled": False},
        "bounds": bounds,
        "initial_pool": pools,
        "solver": {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 10,
        },
        "round_control_ridge_closure": {
            "role": "measured-heuristic-ridge-closure",
            "branch": group["branch"],
            "candidate_ids": [item["id"] for item in candidates],
            "throat_impedance_used_in_score": False,
        },
    }
    return {"bem_candidate_search": search}, seed_values


def _groups() -> list[dict[str, Any]]:
    heuristics = RoundControlHeuristics.load(HEURISTICS)
    groups = []
    for coverage, mouth, k, n, branch in CELLS:
        center = heuristics.length_for_target_s(mouth, coverage, k, n)
        candidates = []
        for multiplier in LENGTH_MULTIPLIERS:
            length = round(center.profile_length_mm * multiplier, 3)
            candidates.append({
                "id": _coordinate_id(coverage, mouth, k, n, multiplier),
                "length_multiplier": multiplier,
                "length_mm": length,
                "length_factor": length / center.reference_length_mm,
                "derived_s": heuristics._s_at_length(
                    mouth, coverage, length, k, n),
            })
        groups.append({
            "coverage_deg": coverage,
            "mouth_mm": mouth,
            "k": k,
            "n": n,
            "branch": branch,
            "target_s": center.target_s,
            "reference_length_mm": center.reference_length_mm,
            "target_s_length_mm": center.profile_length_mm,
            "candidates": candidates,
        })
    if sum(len(group["candidates"]) for group in groups) != MAX_CANDIDATES:
        raise AssertionError("ridge design must contain exactly 48 candidates")
    return groups


def prepare() -> dict[str, Any]:
    groups = _groups()
    for group in groups:
        coverage = int(group["coverage_deg"])
        mouth = int(group["mouth_mm"])
        directory = _search_dir(coverage, mouth)
        source = yaml.safe_load(
            _source_project(
                _read_json(
                    ROOT / "examples/control-decoupling/model_source/"
                    "training_index.json"),
                coverage,
                mouth,
            ).read_text(encoding="utf-8")
        )
        document, seed_values = _fixed_search(group)
        project, _ = materialize_candidate(
            copy.deepcopy(source),
            seed_values,
            document["bem_candidate_search"],
        )
        _write_yaml(directory / "project.yaml", project)
        _write_yaml(directory / "search.yaml", document)

    inputs = {}
    for group in groups:
        directory = _search_dir(
            int(group["coverage_deg"]), int(group["mouth_mm"]))
        cell_id = f"{group['coverage_deg']}deg-{group['mouth_mm']}mm"
        inputs[cell_id] = {
            "project_sha256": _digest_file(directory / "project.yaml"),
            "search_sha256": _digest_file(directory / "search.yaml"),
        }
    manifest = {
        "schema_version": 1,
        "status": "frozen-not-run",
        "purpose": (
            "close measured short/low-K and long/high-K round-control ridges "
            "for deterministic seed heuristics"
        ),
        "hard_candidate_cap": MAX_CANDIDATES,
        "candidate_count": sum(
            len(group["candidates"]) for group in groups),
        "search_count": len(groups),
        "groups": groups,
        "search_inputs": inputs,
        "heuristics_input_sha256": _digest_file(HEURISTICS / "heuristics.json"),
        "implementation_sha256": _digest_file(Path(__file__)),
        "throat_impedance": {
            "retained": True,
            "included_in_surface_score": False,
            "included_in_candidate_selection": False,
        },
        "outcomes_loaded": False,
        "bem_jobs_scheduled": 0,
    }
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(STUDY_ROOT / "manifest.json", manifest)
    _write_json(STUDY_ROOT / "runtime_state.json", {
        "schema_version": 1,
        "status": "not-started",
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "events": [],
    })
    return manifest


def _verify_freeze() -> dict[str, Any]:
    manifest = _read_json(STUDY_ROOT / "manifest.json")
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if expected != actual:
        raise ValueError("ridge-closure manifest differs from freeze hash")
    if manifest.get("outcomes_loaded"):
        raise ValueError("frozen manifest unexpectedly contains outcomes")
    if manifest["candidate_count"] > manifest["hard_candidate_cap"]:
        raise ValueError("candidate cap exceeded")
    for group in manifest["groups"]:
        cell_id = f"{group['coverage_deg']}deg-{group['mouth_mm']}mm"
        directory = _search_dir(
            int(group["coverage_deg"]), int(group["mouth_mm"]))
        hashes = manifest["search_inputs"][cell_id]
        if _digest_file(directory / "project.yaml") != hashes["project_sha256"]:
            raise ValueError(f"changed frozen project input: {cell_id}")
        if _digest_file(directory / "search.yaml") != hashes["search_sha256"]:
            raise ValueError(f"changed frozen search input: {cell_id}")
    return manifest


def _search_items(
        manifest: dict[str, Any],
) -> list[tuple[str, Path, dict[str, Any]]]:
    return [
        (
            f"{group['coverage_deg']}deg-{group['mouth_mm']}mm",
            _search_dir(int(group["coverage_deg"]), int(group["mouth_mm"])),
            group,
        )
        for group in manifest["groups"]
    ]


def status() -> dict[str, Any]:
    manifest = _verify_freeze()
    rows = []
    for cell_id, directory, group in _search_items(manifest):
        path = directory / "search_state.json"
        state = _read_json(path) if path.is_file() else {}
        rows.append({
            "id": cell_id,
            "status": state.get("status", "not-started"),
            "complete_candidates": sum(
                row.get("status") == "complete"
                for row in state.get("candidates", [])),
            "expected_candidates": len(group["candidates"]),
        })
    return {
        "summary": dict(Counter(row["status"] for row in rows)),
        "complete_candidates": sum(
            row["complete_candidates"] for row in rows),
        "candidate_cap": manifest["hard_candidate_cap"],
        "rows": rows,
    }


def preflight() -> dict[str, Any]:
    manifest = _verify_freeze()
    for _, directory, group in _search_items(manifest):
        state = run_search(
            directory / "search.yaml", directory, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if state.get("status") != "preflight":
            raise ValueError(f"{directory}: preflight failed")
        if len(candidates) != len(group["candidates"]):
            raise ValueError(f"{directory}: wrong preflight candidate count")
        if any(item.get("status") != "preflight" for item in candidates):
            raise ValueError(f"{directory}: incomplete preflight")
    return status()


def _run_one(item: tuple[str, Path, dict[str, Any]]) -> dict[str, Any]:
    cell_id, directory, _ = item
    command = [
        sys.executable,
        "-m",
        "app.tools.run_bem_search",
        str(directory / "search.yaml"),
        "--output-dir",
        str(directory),
    ]
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True)
    return {
        "id": cell_id,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run(slots: int = 2) -> dict[str, Any]:
    if slots < 1 or slots > 2:
        raise ValueError("slots must be one or two; each search uses ten workers")
    manifest = _verify_freeze()
    runtime_path = STUDY_ROOT / "runtime_state.json"
    runtime = _read_json(runtime_path)
    if runtime["manifest_freeze_sha256"] != manifest["freeze_sha256"]:
        raise ValueError("runtime state belongs to another manifest")
    items = []
    for item in _search_items(manifest):
        cell_id, directory, group = item
        path = directory / "search_state.json"
        state = _read_json(path) if path.is_file() else {}
        completed = sum(
            row.get("status") == "complete"
            for row in state.get("candidates", []))
        if state.get("status") == "complete" and completed == len(
                group["candidates"]):
            runtime["events"].append({
                "time_unix": time.time(),
                "id": cell_id,
                "status": "reused-complete",
            })
        else:
            items.append(item)
    scheduled = sum(len(item[2]["candidates"]) for item in items)
    already_complete = status()["complete_candidates"]
    if scheduled + already_complete > manifest["hard_candidate_cap"]:
        raise ValueError("run would exceed frozen candidate cap")
    runtime.update(
        status="running",
        slots=slots,
        scheduled_candidates=scheduled,
        started_at_unix=runtime.get("started_at_unix", time.time()),
    )
    _write_json(runtime_path, runtime)
    failures = []
    with ThreadPoolExecutor(max_workers=slots) as executor:
        futures = {executor.submit(_run_one, item): item for item in items}
        for future in as_completed(futures):
            result = future.result()
            runtime["events"].append({
                "time_unix": time.time(),
                "id": result["id"],
                "status": (
                    "complete" if result["returncode"] == 0 else "failed"),
                "returncode": result["returncode"],
            })
            _write_json(runtime_path, runtime)
            if result["returncode"]:
                failures.append(result)
    current = status()
    runtime["status"] = (
        "complete"
        if current["complete_candidates"] == manifest["candidate_count"]
        else "failed" if failures else "incomplete"
    )
    runtime["completed_at_unix"] = time.time()
    runtime["failures"] = failures
    _write_json(runtime_path, runtime)
    if failures:
        raise RuntimeError(
            "ridge searches failed: "
            + ", ".join(item["id"] for item in failures))
    if runtime["status"] != "complete":
        raise RuntimeError("ridge study did not complete")
    return runtime


def _match_coordinate(
        record: dict[str, Any], group: dict[str, Any]
) -> dict[str, Any]:
    length = float(record["values"]["length_mm"])
    candidate = min(
        group["candidates"],
        key=lambda item: abs(float(item["length_mm"]) - length),
    )
    if abs(float(candidate["length_mm"]) - length) > 0.01:
        raise ValueError(f"unmatched measured length {length}")
    return candidate


def analyze() -> dict[str, Any]:
    manifest = _verify_freeze()
    current = status()
    if current["complete_candidates"] != manifest["candidate_count"]:
        raise ValueError("ridge study is incomplete")
    evidence = []
    solver_fingerprints = set()
    for cell_id, directory, group in _search_items(manifest):
        state = _read_json(directory / "search_state.json")
        complete = [
            row for row in state.get("candidates", [])
            if row.get("status") == "complete"
        ]
        if len(complete) != len(group["candidates"]):
            raise ValueError(f"{cell_id}: incomplete response set")
        search = yaml.safe_load(
            (directory / "search.yaml").read_text(encoding="utf-8")
        )["bem_candidate_search"]
        solver_fingerprints.add(_content_hash(_normalize_numbers(
            _solver_fingerprint(search))))
        for record in complete:
            coordinate = _match_coordinate(record, group)
            response = (
                directory / "candidates" / record["id"]
                / "bem/responses.npz"
            )
            _, _ = _validate_npz(response)
            values, impedance, delta = _rescore(response)
            if delta > 1e-9:
                raise ValueError(
                    f"{coordinate['id']}: stored diagnostics differ by {delta:g}"
                )
            evidence.append({
                "id": coordinate["id"],
                "coverage_deg": group["coverage_deg"],
                "mouth_mm": group["mouth_mm"],
                "reference_length_mm": group["reference_length_mm"],
                "length_mm": coordinate["length_mm"],
                "length_factor": coordinate["length_factor"],
                "length_multiplier": coordinate["length_multiplier"],
                "k": group["k"],
                "n": group["n"],
                "derived_s": coordinate["derived_s"],
                "branch": group["branch"],
                "responses": {**values, **impedance},
                "response_path": str(response.relative_to(ROOT)),
                "response_sha256": _digest_file(response),
            })
    if len(evidence) != manifest["candidate_count"]:
        raise ValueError("wrong analyzed evidence count")
    by_cell = {}
    for group in manifest["groups"]:
        cell_id = f"{group['coverage_deg']}deg-{group['mouth_mm']}mm"
        rows = [row for row in evidence if (
            row["coverage_deg"] == group["coverage_deg"]
            and row["mouth_mm"] == group["mouth_mm"])]
        best = max(rows, key=lambda row: row["responses"]["surface_score"])
        center = next(
            row for row in rows if row["length_multiplier"] == 1.0)
        lower = next(
            row for row in rows if row["length_multiplier"] == 0.9)
        upper = next(
            row for row in rows if row["length_multiplier"] == 1.1)
        by_cell[cell_id] = {
            "branch": group["branch"],
            "k": group["k"],
            "n": group["n"],
            "target_s": group["target_s"],
            "length_bracketed": (
                center["responses"]["surface_score"]
                >= max(
                    lower["responses"]["surface_score"],
                    upper["responses"]["surface_score"],
                )
            ),
            "best": {
                "id": best["id"],
                "surface_score": best["responses"]["surface_score"],
                "length_mm": best["length_mm"],
                "length_factor": best["length_factor"],
                "length_multiplier": best["length_multiplier"],
                "derived_s": best["derived_s"],
            },
            "scores_by_length_multiplier": {
                f"{row['length_multiplier']:.1f}":
                    row["responses"]["surface_score"]
                for row in sorted(rows, key=lambda item: item["length_multiplier"])
            },
        }
    result = {
        "schema_version": 1,
        "study_id": "round-control-ridge-closure-v1",
        "manifest_freeze_sha256": manifest["freeze_sha256"],
        "candidate_count": len(evidence),
        "solver_fingerprint_sha256": sorted(solver_fingerprints),
        "throat_impedance_used_in_surface_score": False,
        "evidence": sorted(evidence, key=lambda row: row["id"]),
        "cells": by_cell,
        "summary": {
            "length_bracketed_cells": sum(
                row["length_bracketed"] for row in by_cell.values()),
            "tested_cells": len(by_cell),
            "low_branch_cells": sum(
                row["branch"] == "short-low-k"
                for row in by_cell.values()),
            "high_branch_cells": sum(
                row["branch"] == "long-high-k"
                for row in by_cell.values()),
        },
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "results.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "preflight", "run", "status", "analyze"))
    parser.add_argument("--slots", type=int, default=2)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "preflight":
        result = preflight()
    elif args.command == "run":
        result = run(args.slots)
    elif args.command == "status":
        result = status()
    else:
        result = analyze()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
