#!/usr/bin/env python3
"""Guard the running Batch 1 and launch the committed Batch 2 coordinator."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def batch_one_handoff_ready(project_root: Path) -> bool:
    try:
        state = json.loads((project_root / "domain_mapping_state.json").read_text(
            encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return state.get("phase") == "domain-map-batch-2"


TERMINAL_SEARCH_STATUSES = {
    "complete", "failed", "geometry-rejected", "stopped", "recovery-incomplete",
}


def search_finished(project_root: Path, relative_search: str) -> bool:
    try:
        state = json.loads((project_root / relative_search /
                            "search_state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return state.get("status") in TERMINAL_SEARCH_STATUSES


def truncate_batch_one(project_root: Path,
                       completed_searches: list[str]) -> None:
    state_path = project_root / "domain_mapping_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    terminal_cells: set[tuple[int, int]] = set()
    for relative in completed_searches:
        parts = Path(relative).parts
        terminal_cells.add((int(parts[0].removesuffix("deg")),
                            int(parts[1].split("x", 1)[0])))
    abandoned = 0
    for item in state.get("planned_slots", []):
        if int(item.get("batch", 0)) != 1:
            continue
        cell = (int(item["coverage_deg"]), int(item["mouth_mm"]))
        if cell in terminal_cells:
            item["status"] = "complete-before-truncation"
            continue
        search = (project_root / f"{cell[0]}deg" /
                  f"{cell[1]}x{cell[1]}-domain-map-b01" / "search_state.json")
        try:
            search_state = json.loads(search.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            search_state = {}
        if search_state.get("status") == "complete":
            item["status"] = "complete-before-truncation"
        else:
            item["status"] = "abandoned-redundant-boundary"
            abandoned += 1
    state.update(
        phase="domain-map-batch-2",
        batch_1_status="truncated-after-active-searches",
        batch_1_decision={
            "reason": ("remote extremes only reconfirmed already-known bad "
                       "boundaries; response-surface identification has higher value"),
            "finished_in_flight_searches": completed_searches,
            "abandoned_candidate_slots": abandoned,
            "decided_at_unix": time.time(),
        },
    )
    _write_json(state_path, state)


def run_handoff(project_root: Path, legacy_pgid: int, slots: int = 2,
                solver_workers: int = 10, poll_seconds: float = 1.0,
                finish_searches: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    status_path = project_root / "phase4_handoff_state.json"
    log_path = project_root / "phase4_batch2.log"
    _write_json(status_path, {
        "status": ("waiting-for-active-searches" if finish_searches
                   else "guarding-batch-1"),
        "legacy_pgid": legacy_pgid,
        "replacement": "face-centered-response-surface",
        "finish_searches": finish_searches or [],
        "started_at_unix": time.time(),
    })
    while process_group_alive(legacy_pgid):
        if finish_searches and all(
                search_finished(project_root, path) for path in finish_searches):
            truncate_batch_one(project_root, finish_searches)
            os.killpg(legacy_pgid, signal.SIGTERM)
            break
        time.sleep(poll_seconds)
    while process_group_alive(legacy_pgid):
        time.sleep(poll_seconds)
    if not batch_one_handoff_ready(project_root):
        _write_json(status_path, {
            "status": "blocked", "legacy_pgid": legacy_pgid,
            "reason": "legacy coordinator exited before publishing Batch-1 completion",
            "stopped_at_unix": time.time(),
        })
        return 2
    command = [
        sys.executable, "-m", "app.tools.run_bem_domain_mapping_program",
        str(project_root), "--slots", str(slots),
        "--solver-workers", str(solver_workers), "--start-batch", "2",
    ]
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=repo_root, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        _write_json(status_path, {
            "status": "batch-2-running", "legacy_pgid": legacy_pgid,
            "batch_2_pid": process.pid, "command": command,
            "launched_at_unix": time.time(), "log": str(log_path),
        })
        return_code = process.wait()
    _write_json(status_path, {
        "status": "complete" if return_code == 0 else "failed",
        "legacy_pgid": legacy_pgid, "batch_2_pid": process.pid,
        "return_code": return_code, "finished_at_unix": time.time(),
        "log": str(log_path),
    })
    return return_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--legacy-pgid", type=int, required=True)
    parser.add_argument("--slots", type=int, default=2)
    parser.add_argument("--solver-workers", type=int, default=10)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument(
        "--finish-search", action="append", default=[],
        help="relative Batch-1 search directory to finish before truncating Batch 1")
    args = parser.parse_args()
    raise SystemExit(run_handoff(
        args.project_root, args.legacy_pgid, args.slots,
        args.solver_workers, args.poll_seconds, args.finish_search))


if __name__ == "__main__":
    main()
