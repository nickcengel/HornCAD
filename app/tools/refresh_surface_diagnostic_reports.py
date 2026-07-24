#!/usr/bin/env python3
"""Promote active surface diagnostics and refresh retained BEM reports."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .composite_diagnostics import composite_surface_impedance_score
from .interactive_results import load_run, single_report
from .run_bem_search import save_state, write_report
from .surface_diagnostics import (
    ACTIVE_SURFACE_SCORE_VERSION,
    surface_diagnostics,
)
from .throat_impedance_diagnostics import (
    DIAGNOSTIC_VERSION,
    throat_impedance_diagnostics,
)


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_one(task: dict[str, Any]) -> dict[str, Any]:
    response = Path(task["response"])
    report_path = Path(task["report"])
    run = load_run(response.parent, task["artifact_stem"])
    crossover = float(task["crossover_hz"])
    upper = float(task["upper_frequency_hz"])
    count = int(math.ceil(math.log2(upper / crossover) * 48)) + 1
    fixed_grid = np.geomspace(crossover, upper, count)
    radiation = surface_diagnostics(run, fixed_grid, fixed_band=True)
    impedance = throat_impedance_diagnostics(
        run["frequencies"],
        run["normalized_impedance"],
        crossover,
        upper,
    )
    composite = composite_surface_impedance_score(
        radiation["score"], impedance)
    single_report(
        response.parent,
        report_path,
        title=f"BEM {task['artifact_stem']}",
        evaluation_frequencies=fixed_grid,
        fixed_band=True,
        name=task["artifact_stem"],
    )
    return {
        **task,
        "surface_diagnostics": radiation,
        "throat_impedance_diagnostics": impedance,
        "composite_diagnostics": composite,
        "report_sha256": _digest(report_path),
    }


def refresh_reports(
    roots: list[Path],
    *,
    workers: int = 16,
) -> dict[str, Any]:
    responses = sorted({
        response.resolve()
        for root in roots
        for response in root.glob(
            "**/candidates/candidate-*/bem/responses.npz")
    })
    by_search: dict[Path, list[Path]] = {}
    for response in responses:
        by_search.setdefault(response.parents[3], []).append(response)

    if workers < 1:
        raise ValueError("workers must be at least 1")
    refreshed = []
    skipped = []
    states: dict[Path, dict[str, Any]] = {}
    contexts: dict[str, tuple[Path, dict[str, Any]]] = {}
    tasks = []
    for search_dir, search_responses in sorted(
            by_search.items(), key=lambda item: str(item[0])):
        state_path = search_dir / "search_state.json"
        if not state_path.is_file():
            skipped.append({
                "search": str(search_dir.relative_to(ROOT)),
                "reason": "search state absent",
            })
            continue
        state = _read_json(state_path)
        if any(record.get("status") == "running"
               for record in state.get("candidates", [])):
            skipped.append({
                "search": str(search_dir.relative_to(ROOT)),
                "reason": "search currently running",
            })
            continue
        states[search_dir] = state
        records = {
            str(record.get("id")): record
            for record in state.get("candidates", [])
        }
        for response in search_responses:
            candidate_id = response.parents[1].name
            record = records.get(candidate_id)
            if not record or record.get("status") != "complete":
                skipped.append({
                    "response": str(response.relative_to(ROOT)),
                    "reason": "matching complete candidate absent",
                })
                continue
            report_value = record.get("report_file")
            report_path = (
                search_dir / str(report_value)
                if report_value else response.parent /
                f"{record['artifact_stem']}_Report.html"
            )
            run = load_run(response.parent, record.get("artifact_stem"))
            task = {
                "response": str(response),
                "report": str(report_path),
                "search_dir": str(search_dir),
                "candidate_id": candidate_id,
                "artifact_stem": record["artifact_stem"],
                "crossover_hz": float(
                    state.get("crossover_hz", run["crossover_hz"])),
                "upper_frequency_hz": float(state.get(
                    "upper_frequency_hz", run["frequencies"][-1])),
            }
            tasks.append(task)
            contexts[str(response)] = (search_dir, record)

    if workers == 1:
        results = map(_refresh_one, tasks)
    else:
        executor = ProcessPoolExecutor(max_workers=workers)
        results = executor.map(_refresh_one, tasks)
    try:
        for result in results:
            response = Path(result["response"])
            search_dir, record = contexts[str(response)]
            radiation = result["surface_diagnostics"]
            impedance = result["throat_impedance_diagnostics"]
            composite = result["composite_diagnostics"]
            record["surface_diagnostics"] = radiation
            record["throat_impedance_diagnostics"] = impedance
            record["composite_diagnostics"] = composite
            record["report_file"] = str(
                Path(result["report"]).relative_to(search_dir))
            refreshed.append({
                "response": str(response.relative_to(ROOT)),
                "report": str(Path(result["report"]).relative_to(ROOT)),
                "surface_score": float(
                    radiation["score"]["overall_percent"]),
                "throat_impedance_score": float(
                    impedance["overall_percent"]),
                "composite_score": float(
                    composite["overall_percent"]) if composite else None,
                "report_sha256": result["report_sha256"],
            })
    finally:
        if workers != 1:
            executor.shutdown()
    for search_dir, state in states.items():
        save_state(search_dir, state)
        write_report(search_dir, state)
    return {
        "schema_version": 1,
        "status": "complete",
        "active_surface_score_version": ACTIVE_SURFACE_SCORE_VERSION,
        "throat_impedance_version": DIAGNOSTIC_VERSION,
        "ranking_authority": "surface_score",
        "responses_found": len(responses),
        "workers": workers,
        "reports_refreshed": len(refreshed),
        "skipped_count": len(skipped),
        "refreshed": refreshed,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="+", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    result = refresh_reports(
        [path.resolve() for path in args.root],
        workers=args.workers,
    )
    if args.ledger:
        _write_json(args.ledger.resolve(), result)
    print(json.dumps({
        key: value for key, value in result.items()
        if key not in {"refreshed", "skipped"}
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
