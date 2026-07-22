#!/usr/bin/env python3
"""Run the frozen control-decoupling study after an explicit launch review.

The planner and materializer are intentionally separate from this command.  This
runner refuses to start if the reviewed manifest changed, keeps two search slots
fed, isolates individual search failures, and records every pruning decision.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

import yaml

from .materialize_control_decoupling_study import WAVES
from .report_control_decoupling_study import refresh_index
from .run_bem_search import run_search


RUNTIME_STATE = "runtime_state.json"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _manifest_hash(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load_frozen(root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "execution_plan.json").read_text(encoding="utf-8"))
    digest = _manifest_hash(manifest)
    if plan.get("manifest_sha256") != digest:
        raise RuntimeError("execution plan does not match the frozen manifest")
    return manifest, plan, digest


def _search_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads((path / "search_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def search_status(path: Path) -> str:
    return str(_search_state(path).get("status", "not-started"))


def _same_values(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ("length_mm", "osse_coverage_h_deg", "osse_coverage_v_deg",
            "k_h", "k_v", "n_h", "n_v")
    try:
        return all(math.isclose(float(left[key]), float(right[key]),
                                rel_tol=0.0, abs_tol=2e-5) for key in keys)
    except (KeyError, TypeError, ValueError):
        return False


def _coordinate_records(search_dir: Path) -> dict[str, dict[str, Any]]:
    """Match completed records to frozen coordinates by physical values."""
    config = yaml.safe_load((search_dir / "search.yaml").read_text(
        encoding="utf-8"))["bem_candidate_search"]
    rows = config["control_decoupling"]["coordinates"]
    records = _search_state(search_dir).get("candidates", [])
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        expected = {
            "length_mm": row["length_mm"],
            "osse_coverage_h_deg": row["coverage_deg"],
            "osse_coverage_v_deg": row["coverage_deg"],
            "k_h": row["k"], "k_v": row["k"],
            "n_h": row["n"], "n_v": row["n"],
        }
        matches = [record for record in records
                   if _same_values(record.get("values", {}), expected)]
        if len(matches) == 1:
            output[row["id"]] = matches[0]
    return output


def _mean_axis(result: dict[str, Any], path: tuple[str, ...]) -> float | None:
    values = []
    for axis in ("horizontal", "vertical"):
        selected: Any = result.get(axis, {})
        for key in path:
            selected = selected.get(key) if isinstance(selected, dict) else None
        if not isinstance(selected, (int, float)) or not math.isfinite(selected):
            return None
        values.append(float(selected))
    return sum(values) / 2


def _diagnostics(record: dict[str, Any]) -> dict[str, float] | None:
    if record.get("status") != "complete":
        return None
    result = record.get("surface_diagnostics", {})
    score = (result.get("score") or {}).get("overall_percent")
    values = {
        "score": float(score) if isinstance(score, (int, float)) else None,
        "containment_percent": _mean_axis(
            result, ("containment", "mean_fraction")),
        "profile_rms_db": _mean_axis(
            result, ("distribution", "rms_profile_error_db")),
        "slice_rms_db": _mean_axis(
            result, ("slice_energy_stability", "rms_departure_db")),
        "outward_rise_db": _mean_axis(
            result, ("distribution", "rms_outward_rise_violation_db")),
        "minus_six_rms_deg": _mean_axis(
            result, ("minus_six_line", "rms_coverage_error_deg")),
    }
    if any(value is None or not math.isfinite(value)
           for value in values.values()):
        return None
    values["containment_percent"] *= 100.0
    return {key: float(value) for key, value in values.items()}


def material_improvement(endpoint: dict[str, float],
                         center: dict[str, float]) -> bool:
    """Use the preregistered practical score/diagnostic thresholds."""
    return (
        endpoint["score"] >= center["score"] + 0.5 or
        endpoint["containment_percent"] >= center["containment_percent"] + 0.5 or
        endpoint["profile_rms_db"] <= center["profile_rms_db"] - 0.1 or
        endpoint["slice_rms_db"] <= center["slice_rms_db"] - 0.1 or
        endpoint["outward_rise_db"] <= center["outward_rise_db"] - 0.1 or
        endpoint["minus_six_rms_deg"] <= center["minus_six_rms_deg"] - 0.5)


def axis_closure_decisions(root: Path, manifest: dict[str, Any]
                           ) -> dict[str, dict[str, Any]]:
    """Decide which hard-boundary probes are justified by inner endpoints."""
    records: dict[str, dict[str, Any]] = {}
    for wave in ("core-axis", "boundary-sentinel"):
        wave_root = root / "searches" / wave
        if not wave_root.exists():
            continue
        for search_path in wave_root.rglob("search.yaml"):
            records.update(_coordinate_records(search_path.parent))
    center_id = lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-L+0-K+0-N+0"
    endpoint_templates = {
        ("L", "low"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-boundary-L1",
        ("L", "high"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-boundary-L2",
        ("K", "low"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-L+0-K-1-N+0",
        ("K", "high"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-L+0-K+1-N+0",
        ("N", "low"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-L+0-K+0-N-1",
        ("N", "high"): lambda row: f"{row['coverage_deg']}d-{row['mouth_mm']}mm-L+0-K+0-N+1",
    }
    decisions = {}
    for row in manifest["coordinates"]:
        if row.get("status") != "conditional" or row.get("stage") != "axis-closure":
            continue
        endpoint_id = endpoint_templates[
            (row["closure_axis"], row["closure_direction"])](row)
        center_record, endpoint_record = records.get(center_id(row)), records.get(endpoint_id)
        center = _diagnostics(center_record) if center_record else None
        endpoint = _diagnostics(endpoint_record) if endpoint_record else None
        if center is None or endpoint is None:
            decisions[row["id"]] = {
                "decision": "skip-missing-evidence", "center": center_id(row),
                "inner_endpoint": endpoint_id,
            }
            continue
        run = material_improvement(endpoint, center)
        decisions[row["id"]] = {
            "decision": "run" if run else "closed-at-inner-endpoint",
            "center": center_id(row), "inner_endpoint": endpoint_id,
            "score_change": endpoint["score"] - center["score"],
            "material_diagnostic_improvement": run and (
                endpoint["score"] < center["score"] + 0.5),
        }
    return decisions


def _run_queue(paths: list[Path], slots: int, task: Callable[[Path], Any],
               event: Callable[[Path, str, str | None], None]) -> None:
    pending = list(paths)
    futures: dict[Any, Path] = {}
    with ThreadPoolExecutor(max_workers=slots) as executor:
        while pending or futures:
            while pending and len(futures) < slots:
                path = pending.pop(0)
                event(path, "started", None)
                futures[executor.submit(task, path)] = path
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                path = futures.pop(future)
                try:
                    future.result()
                except Exception as error:  # preserve capacity and audit failure
                    event(path, "failed", f"{type(error).__name__}: {error}")
                else:
                    event(path, "complete", None)


def run_study(root: Path, reviewed_sha256: str, slots: int = 2) -> dict[str, Any]:
    manifest, plan, digest = _load_frozen(root)
    if reviewed_sha256 != digest:
        raise RuntimeError(
            "launch confirmation does not match manifest; review the current plan")
    state: dict[str, Any] = {
        "schema_version": 1, "status": "running", "manifest_sha256": digest,
        "started_at_unix": time.time(), "slots": slots, "events": [],
        "skipped_searches": [], "axis_closure_decisions": {},
    }
    state_path = root / RUNTIME_STATE

    def record(path: Path, status: str, error: str | None) -> None:
        item = {"time_unix": time.time(), "wave": state.get("wave"),
                "search": str(path.relative_to(root)), "status": status}
        if error:
            item["error"] = error
        state["events"].append(item)
        _write_json(state_path, state)
        refresh_index(root)

    _write_json(state_path, state)
    for wave in WAVES:
        state["wave"] = wave
        _write_json(state_path, state)
        planned = [item for item in plan["searches"] if item["wave"] == wave]
        if wave == "axis-closure":
            decisions = state["axis_closure_decisions"]
            retained = []
            for item in planned:
                decision = decisions.get(item["coordinate_ids"][0], {})
                if decision.get("decision") == "run":
                    retained.append(item)
                else:
                    state["skipped_searches"].append({
                        "wave": wave, "search": item["path"],
                        "coordinate_ids": item["coordinate_ids"],
                        "reason": decision.get("decision", "closure not triggered"),
                    })
            planned = retained
        paths = [root / item["path"] for item in planned
                 if search_status(root / item["path"]) != "complete"]
        _run_queue(paths, slots,
                   lambda path: run_search(path / "search.yaml", path, None),
                   record)
        if wave == "boundary-sentinel":
            state["axis_closure_decisions"] = axis_closure_decisions(
                root, manifest)
            _write_json(state_path, state)
            refresh_index(root)
    failures = [event for event in state["events"]
                if event["status"] == "failed"]
    state.update(
        status="blocked" if failures else "complete",
        completed_at_unix=time.time(), failure_count=len(failures))
    state.pop("wave", None)
    _write_json(state_path, state)
    refresh_index(root)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path,
                        default=Path("examples/control-decoupling"), nargs="?")
    parser.add_argument("--reviewed-manifest-sha256", required=True,
                        help="Exact digest printed during the launch review")
    parser.add_argument("--slots", type=int, default=2)
    args = parser.parse_args()
    result = run_study(args.root, args.reviewed_manifest_sha256, args.slots)
    if result["status"] != "complete":
        raise RuntimeError(
            f"study ended with {result['failure_count']} isolated failures")


if __name__ == "__main__":
    main()
