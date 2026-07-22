#!/usr/bin/env python3
"""Run adaptive, evidence-driven BEM learning batches unattended."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from statistics import median
import time
from typing import Any

from .generate_mouth_size_coverage_grid_report import generate_report
from .learn_bem_response import (
    leave_cell_out_analysis, plan_controlled_learning_batch, render_markdown,
)
from .run_bem_domain_mapping_program import (
    Proposal, _run_paths, _write_json, materialize_cell_search,
    retire_superseded_batch_two,
)


PROGRAM_STATE = "learning_program_state.json"
MINIMUM_MEDIAN_RELATIVE_RMSE_IMPROVEMENT = 0.02


def _validation_change(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes = {}
    improvements = []
    for name, old in before["diagnostic_validation"].items():
        old_rmse = float(old["rmse"])
        new_rmse = float(after["diagnostic_validation"][name]["rmse"])
        relative = (old_rmse - new_rmse) / max(old_rmse, 1e-12)
        changes[name] = {
            "before_rmse": old_rmse, "after_rmse": new_rmse,
            "relative_improvement": relative,
        }
        improvements.append(relative)
    return {
        "diagnostics": changes,
        "median_relative_rmse_improvement": median(improvements),
    }


def _materialize_manifest(root: Path, manifest: dict[str, Any],
                          solver_workers: int) -> list[Path]:
    proposals = [Proposal(**item["proposal"]) for item in manifest["candidates"]]
    grouped: dict[tuple[int, int], list[Proposal]] = {}
    for proposal in proposals:
        grouped.setdefault(
            (proposal.coverage_deg, proposal.mouth_mm), []).append(proposal)
    return [materialize_cell_search(root, group, solver_workers)
            for _, group in sorted(grouped.items())]


def run_learning_program(root: Path, slots: int = 2, solver_workers: int = 10,
                         batch_size: int = 30, max_rounds: int = 3
                         ) -> dict[str, Any]:
    retire_superseded_batch_two(root)
    state_path = root / PROGRAM_STATE
    state: dict[str, Any] = {
        "schema_version": 1, "status": "running",
        "phase": "controlled-learning-initializing",
        "method": "held-cell-error-controlled-physical-contrasts",
        "started_at_unix": time.time(), "rounds": [],
        "stop_rule": {
            "maximum_rounds": max_rounds,
            "minimum_median_relative_rmse_improvement":
                MINIMUM_MEDIAN_RELATIVE_RMSE_IMPROVEMENT,
        },
    }
    _write_json(state_path, state)
    for learning_round in range(1, max_rounds + 1):
        before = leave_cell_out_analysis(root)
        manifest = plan_controlled_learning_batch(
            root, before, batch_size, learning_round)
        if not manifest["candidates"]:
            state.update(status="complete", phase="controlled-learning-complete",
                         stop_reason="no physically novel contrasts")
            break
        manifest_path = root / f"learning_batch_r{learning_round:02d}.json"
        _write_json(manifest_path, manifest)
        before_path = root / f"learning_analysis_before_r{learning_round:02d}.json"
        _write_json(before_path, before)
        paths = _materialize_manifest(root, manifest, solver_workers)
        round_state = {
            "round": learning_round, "status": "running",
            "candidate_count": manifest["batch_size"],
            "control_counts": manifest["control_counts"],
            "direction_counts": manifest["direction_counts"],
            "searches": [str(path.relative_to(root)) for path in paths],
            "manifest": manifest_path.name,
        }
        state["rounds"].append(round_state)
        state["active_round"] = learning_round
        state["phase"] = f"controlled-learning-round-{learning_round}"
        _write_json(state_path, state)
        generate_report(root, root / "index.html")
        scheduler_state = {
            "completed_searches": 0, "active_round": learning_round,
        }
        _run_paths(root, paths, slots, scheduler_state,
                   root / "learning_scheduler_state.json")
        after = leave_cell_out_analysis(root)
        after_path = root / f"learning_analysis_after_r{learning_round:02d}.json"
        _write_json(after_path, after)
        markdown_path = root / f"learning_analysis_after_r{learning_round:02d}.md"
        markdown_path.write_text(render_markdown(after), encoding="utf-8")
        validation = _validation_change(before, after)
        round_state.update(status="complete", validation_change=validation)
        _write_json(state_path, state)
        generate_report(root, root / "index.html")
        if (validation["median_relative_rmse_improvement"] <
                MINIMUM_MEDIAN_RELATIVE_RMSE_IMPROVEMENT):
            state.update(
                status="complete",
                phase="controlled-learning-complete",
                stop_reason="held-cell prediction improvement plateaued",
                completed_at_unix=time.time(),
            )
            break
    else:
        state.update(status="complete", phase="controlled-learning-complete",
                     stop_reason="maximum learning rounds reached",
                     completed_at_unix=time.time())
    state.pop("active_round", None)
    _write_json(state_path, state)
    generate_report(root, root / "index.html")
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--slots", type=int, default=2)
    parser.add_argument("--solver-workers", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--max-rounds", type=int, default=3)
    args = parser.parse_args()
    run_learning_program(args.root, args.slots, args.solver_workers,
                         args.batch_size, args.max_rounds)


if __name__ == "__main__":
    main()
