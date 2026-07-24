#!/usr/bin/env python3
"""Restore v1-primary reports from retained NPZ without running BEM."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .interactive_results import load_run, single_report
from .run_bem_search import write_report


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY = ROOT / "examples/extension-throat-angle-heuristics"


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.v1-primary.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _requires_restore(path: Path) -> bool:
    document = json.loads(path.read_text(encoding="utf-8"))
    return any(
        value.get("score", {}).get("version") == "v2"
        for value in document.values()
    )


def _evaluation_grid(run: dict[str, Any]) -> np.ndarray:
    crossover = float(run["crossover_hz"])
    upper = float(run["frequencies"][-1])
    count = int(math.ceil(math.log2(upper / crossover) * 48)) + 1
    return np.geomspace(crossover, upper, count)


def restore(study: Path = DEFAULT_STUDY) -> dict[str, Any]:
    restored = []
    for surface_path in sorted(study.glob(
        "searches/**/candidates/candidate-*/bem/surface_diagnostics.json"
    )):
        if not _requires_restore(surface_path):
            continue
        bem_dir = surface_path.parent
        response = bem_dir / "responses.npz"
        if not response.is_file():
            raise FileNotFoundError(response)
        search_dir = bem_dir.parents[2]
        state_path = search_dir / "search_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        candidate_dir = bem_dir.parent
        record = next(
            row for row in state["candidates"]
            if row["id"] == candidate_dir.name
        )
        report_path = search_dir / record["report_file"]
        run = load_run(bem_dir)
        single_report(
            bem_dir,
            report_path,
            record["artifact_stem"],
            evaluation_frequencies=_evaluation_grid(run),
            fixed_band=True,
        )
        surface_document = json.loads(
            surface_path.read_text(encoding="utf-8")
        )
        result = next(iter(surface_document.values()))
        if result.get("score", {}).get("version") != "v1":
            raise ValueError(f"{surface_path}: v1 restoration failed")
        record["surface_diagnostics"] = result
        _write_json(state_path, state)
        write_report(search_dir, state)
        restored.append(str(surface_path.relative_to(ROOT)))
    return {
        "schema_version": 1,
        "status": "complete",
        "primary_surface_score": "v1",
        "experimental_surface_score": "v2",
        "restored_count": len(restored),
        "restored": restored,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path, nargs="?", default=DEFAULT_STUDY)
    args = parser.parse_args()
    result = restore(args.study)
    audit = args.study / "surface_score_v1_restore.json"
    _write_json(audit, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
