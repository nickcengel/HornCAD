#!/usr/bin/env python3
"""Run the complete BEM study as one dependency-aware, two-slot queue."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

from .generate_mouth_size_coverage_grid_report import generate_report
from .run_bem_search import run_search
from .run_coupled_kn_length_program import (
    anchor_selection, materialize_canonical_s_extension, run_anchor,
)
from .run_s_boundary_closure_program import (
    authored_sentinel, baseline_searches, close_baseline, completed_points,
    closure_status,
)


PHASE_ORDER = (
    "baseline-and-s-closure", "kn-grids-and-canonical-extensions", "coupled",
)
ANGLE_PRIORITY = {40: 0, 45: 1, 50: 2, 30: 3, 35: 4, 25: 5}


def search_status(search_dir: Path) -> str:
    state_path = search_dir / "search_state.json"
    if not state_path.exists():
        return "not-started"
    try:
        return str(json.loads(state_path.read_text(encoding="utf-8")).get(
            "status", "unknown"))
    except (OSError, json.JSONDecodeError):
        return "unreadable"


def _priority(path: Path) -> tuple[int, int, str]:
    angle = int(path.parent.name.removesuffix("deg"))
    mouth = int(path.name.split("x", 1)[0])
    return ANGLE_PRIORITY.get(angle, 99), abs(mouth - 400), path.name


def _needs_s_work(baseline: Path) -> bool:
    if search_status(baseline) != "complete":
        return True
    rounds = sorted(baseline.parent.glob(
        baseline.name.removesuffix("-s-grid") + "-s-boundary-r*"))
    if any(search_status(path) == "geometry-rejected" for path in rounds):
        return False
    points = completed_points([baseline, *rounds])
    if not points:
        return True
    status, _ = closure_status(points)
    sentinel = authored_sentinel(baseline)
    return status != "closed" or not any(
        abs(point[0] - sentinel) <= 0.02 for point in points)


def ordered_baselines(root: Path) -> list[Path]:
    """Prioritize useful unfinished chains; defer 25° evidence cleanup."""
    return sorted(baseline_searches(root), key=lambda path: (
        not _needs_s_work(path), *_priority(path)))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _run_baseline_chain(root: Path, baseline: Path) -> dict[str, Any]:
    if search_status(baseline) != "complete":
        run_search(baseline / "search.yaml", baseline, None)
    return close_baseline(root, baseline)


def run_dynamic_queue(
        paths: list[Path], task: Callable[[Path], Any], *, workers: int,
        poll_seconds: float, progress: Callable[[Path, str], None] | None = None,
        count_external_running: bool = True) -> list[Any]:
    """Run tasks while counting already-running search directories as slots."""
    pending = list(paths)
    results = []
    futures: dict[Any, Path] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while pending or futures:
            external = ([path for path in pending if search_status(path) == "running"]
                        if count_external_running else [])
            capacity = max(0, workers - len(external) - len(futures))
            available = [path for path in pending if path not in external]
            for path in available[:capacity]:
                pending.remove(path)
                if progress:
                    progress(path, "started")
                futures[executor.submit(task, path)] = path
            if futures:
                done, _ = wait(futures, timeout=poll_seconds,
                               return_when=FIRST_COMPLETED)
                for future in done:
                    path = futures.pop(future)
                    results.append(future.result())
                    if progress:
                        progress(path, "complete")
            elif pending:
                time.sleep(poll_seconds)
    return results


def _configured_kn_grids(root: Path) -> list[Path]:
    return sorted((path.parent for path in root.glob("*deg/*-kn-grid/search.yaml")),
                  key=_priority)


def run_program(root: Path, workers: int = 2,
                poll_seconds: float = 15) -> dict[str, Any]:
    state_path = root / "study_program_state.json"
    state: dict[str, Any] = {
        "status": "running", "phase": PHASE_ORDER[0], "events": [],
        "workers": workers, "started_at_unix": time.time(),
    }

    def record(path: Path, status: str) -> None:
        state["events"].append({
            "time_unix": time.time(), "phase": state["phase"],
            "task": str(path.relative_to(root)), "status": status,
        })
        _write_json(state_path, state)

    _write_json(state_path, state)
    baselines = ordered_baselines(root)
    closure_results = run_dynamic_queue(
        baselines, lambda path: _run_baseline_chain(root, path),
        workers=workers, poll_seconds=poll_seconds, progress=record)
    closure_results.sort(key=lambda item: item["baseline"])
    acceptable_closures = {"closed", "geometry-limited"}
    certificate = {
        "status": ("complete" if all(item["status"] in acceptable_closures
                                     for item in closure_results) else "blocked"),
        "results": closure_results,
    }
    _write_json(root / "s_boundary_closure.json", certificate)
    if certificate["status"] != "complete":
        state.update(status="blocked", reason="S boundary closure is incomplete")
        _write_json(state_path, state)
        return state

    state["phase"] = PHASE_ORDER[1]
    _write_json(state_path, state)
    refinement_paths = [path for path in _configured_kn_grids(root)
                        if search_status(path) != "complete"]
    for mouth in (300, 350, 400, 450, 500):
        baseline = root / "45deg" / f"{mouth}x{mouth}-s-grid"
        output = baseline.with_name(f"{mouth}x{mouth}-canonical-s")
        try:
            refinement_paths.append(materialize_canonical_s_extension(
                baseline, output))
        except ValueError as error:
            if "no missing canonical S targets" not in str(error):
                raise
    refinement_paths = list(dict.fromkeys(refinement_paths))
    run_dynamic_queue(
        refinement_paths, lambda path: run_search(path / "search.yaml", path, None),
        workers=workers, poll_seconds=poll_seconds, progress=record,
        count_external_running=False)

    state["phase"] = PHASE_ORDER[2]
    _write_json(state_path, state)
    anchors, anchor_evidence = anchor_selection(root)
    _write_json(root / "coupled_anchor_selection.json", {
        "schema_version": 1,
        "policy": "400 mm matched controls plus distinct mouths gaining at least 0.75 points",
        "anchors": anchor_evidence,
    })
    run_dynamic_queue(
        anchors, lambda path: run_anchor(root, path), workers=workers,
        poll_seconds=poll_seconds, progress=record,
        count_external_running=False)
    state.update(status="complete", completed_at_unix=time.time())
    _write_json(state_path, state)
    generate_report(root, root / "index.html")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--workers", type=int, default=2,
                        help="Total concurrent ten-core search slots")
    parser.add_argument("--poll-seconds", type=float, default=15)
    args = parser.parse_args()
    result = run_program(args.project_root, args.workers, args.poll_seconds)
    if result["status"] != "complete":
        raise RuntimeError(result.get("reason", "study program did not complete"))


if __name__ == "__main__":
    main()
