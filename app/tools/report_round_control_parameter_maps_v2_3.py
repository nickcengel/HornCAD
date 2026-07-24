#!/usr/bin/env python3
"""Build measured round-control parameter maps ranked by surface score v2.3."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
from typing import Any

from .generate_surface_score_rank_comparison import _evaluation_grid
from .interactive_results import load_run
from .report_round_control_parameter_maps import COVERAGES, MOUTHS
from .report_round_control_parameter_maps_v2_1 import (
    DEFAULT_RIDGE_RESULTS,
    DEFAULT_SOURCE,
    PARAMETERS,
    _content_hash,
    _file_hash,
    _ridge_candidates,
    _winner,
    render as render_v2_1,
)
from .surface_diagnostics import surface_diagnostics, surface_score_v2_3


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "examples/round-control-parameter-maps-v2-3"
DEFAULT_CALIBRATION = (
    ROOT
    / "examples/surface-score-v2-2-cell-ranking-game"
    / "surface_score_v2_3_calibration.json"
)
DEFAULT_WIDE_CLOSURE_RESULTS = (
    ROOT / "examples/round-control-wide-coverage-closure/initial_results.json"
)


def _score_candidate(row: dict[str, Any]) -> float:
    response = ROOT / row["source_path"]
    run = load_run(response.parent)
    diagnostics = surface_diagnostics(
        run, _evaluation_grid(run), fixed_band=True
    )
    if diagnostics["status"] != "available":
        raise ValueError(f"{row['id']}: surface diagnostics unavailable")
    score = surface_score_v2_3(
        diagnostics, run.get("mouth_dimensions_mm")
    )
    if score is None:
        raise ValueError(f"{row['id']}: surface score v2.3 unavailable")
    return float(score["overall_percent"])


def _score_population(
    rows: list[dict[str, Any]], workers: int
) -> list[dict[str, Any]]:
    if workers <= 1:
        return [
            {**row, "score_v2_3": _score_candidate(row)}
            for row in rows
        ]
    completed = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _score_candidate,
                {
                    "id": row["id"],
                    "source_path": row["source_path"],
                },
            ): row
            for row in rows
        }
        for count, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            completed.append({
                **row,
                "score_v2_3": future.result(),
            })
            if count % 100 == 0 or count == len(rows):
                print(
                    f"scored {count}/{len(rows)} retained responses",
                    flush=True,
                )
    return completed


def assemble(
    source_path: Path = DEFAULT_SOURCE,
    ridge_results_path: Path = DEFAULT_RIDGE_RESULTS,
    calibration_path: Path = DEFAULT_CALIBRATION,
    wide_closure_results_path: Path | None = DEFAULT_WIDE_CLOSURE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
    *,
    workers: int = 8,
) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    grids = dict(source["grids"])
    candidates_by_hash = {
        row["response_sha256"]: dict(row) for row in source["candidates"]
    }
    for row in _ridge_candidates(ridge_results_path, output, grids):
        candidates_by_hash[row["response_sha256"]] = row
    if (wide_closure_results_path is not None
            and wide_closure_results_path.is_file()):
        for row in _ridge_candidates(
                wide_closure_results_path, output, grids):
            candidates_by_hash[row["response_sha256"]] = row
    population = _score_population(
        sorted(candidates_by_hash.values(), key=lambda row: row["id"]),
        workers,
    )
    cells: dict[str, Any] = {}
    winner_fields = (
        "id",
        "response_sha256",
        "report_link",
        "source_path",
        "length_mm",
        "k",
        "n",
        "s",
        "score_v1",
        "score_v2_3",
        "grid_id",
        "heatmap_b64",
    )
    for coverage in COVERAGES:
        for mouth in MOUTHS:
            candidates = [
                row for row in population
                if float(row["coverage_deg"]) == coverage
                and float(row["mouth_mm"]) == mouth
            ]
            if not candidates:
                raise ValueError(f"no evidence for {coverage}deg-{mouth}mm")
            v1 = _winner(candidates, "score_v1")
            v2_3 = _winner(candidates, "score_v2_3")
            deltas = {
                key: float(v2_3[key]) - float(v1[key])
                for key, *_ in PARAMETERS
            }
            deltas["score"] = (
                float(v2_3["score_v2_3"]) - float(v1["score_v2_3"])
            )
            cell_id = f"{coverage}deg-{mouth}mm"
            cells[cell_id] = {
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "evidence_count": len(candidates),
                "v1_winner": {
                    key: v1[key] for key in winner_fields
                },
                "v2_3_winner": {
                    key: v2_3[key] for key in winner_fields
                },
                "v2_3_minus_v1_winner": deltas,
                "winner_changed": (
                    v1["response_sha256"] != v2_3["response_sha256"]
                ),
            }
    artifact = {
        "schema_version": 1,
        "study_id": "round-control-parameter-maps-v2-3",
        "status": "complete",
        "score_version": "v2.3",
        "score_status": (
            "diagnostic_of_record_not_independently_validated"
        ),
        "selection_rule": (
            "maximum measured surface score v2.3 per mouth/coverage cell; "
            "exact-response-deduplicated evidence; lexical id tie-break"
        ),
        "sources": [
            {
                "path": str(source_path.relative_to(ROOT)),
                "sha256": _file_hash(source_path),
                "content_sha256": source["content_sha256"],
            },
            {
                "path": str(ridge_results_path.relative_to(ROOT)),
                "sha256": _file_hash(ridge_results_path),
                "content_sha256": json.loads(
                    ridge_results_path.read_text(encoding="utf-8")
                )["content_sha256"],
            },
            {
                "path": str(calibration_path.relative_to(ROOT)),
                "sha256": _file_hash(calibration_path),
                "implementation_sha256":
                    calibration["implementation_sha256"],
                "calibration_script_sha256":
                    calibration["calibration_script_sha256"],
            },
        ],
        "population_count": len(population),
        "grids": grids,
        "heatmap_encoding": source["heatmap_encoding"],
        "cells": cells,
    }
    if (wide_closure_results_path is not None
            and wide_closure_results_path.is_file()):
        artifact["sources"].append({
            "path": str(wide_closure_results_path.relative_to(ROOT)),
            "sha256": _file_hash(wide_closure_results_path),
            "content_sha256": json.loads(
                wide_closure_results_path.read_text(encoding="utf-8")
            )["content_sha256"],
        })
    artifact["content_sha256"] = _content_hash(artifact)
    return artifact


def _render_adapter(artifact: dict[str, Any]) -> dict[str, Any]:
    adapted = {
        key: value for key, value in artifact.items() if key != "cells"
    }
    cells = {}
    for cell_id, cell in artifact["cells"].items():
        old = dict(cell["v1_winner"])
        new = dict(cell["v2_3_winner"])
        old["score_v2_1"] = old["score_v2_3"]
        new["score_v2_1"] = new["score_v2_3"]
        cells[cell_id] = {
            **cell,
            "v1_winner": old,
            "v2_1_winner": new,
            "v2_1_minus_v1_winner": cell["v2_3_minus_v1_winner"],
        }
    adapted["cells"] = cells
    return adapted


def render(artifact: dict[str, Any]) -> str:
    document = render_v2_1(_render_adapter(artifact))
    document = (
        document.replace("v2_1", "v2_3")
        .replace("V2.1", "V2.3")
        .replace("v2.1", "v2.3")
    )
    stale = (
        "<p class='muted'>This grid begins at 30°. V2.3’s narrow-coverage "
        "correction\nends at 30°, so the correction itself does not alter "
        "these scores; selection\nhere reflects the contour-forward v2 terms "
        "now retained by v2.3.</p>"
    )
    current = (
        "<p class='muted'>V2.3 preserves v2.2 broad-quality discrimination "
        "and adds a guarded local-ranking refinement. Containment and "
        "outward-rise remain continuous v2.2 inputs and also gate the local "
        "branch below their calibrated floors. It is the diagnostic of record "
        "and authoritative ranking score.</p>"
    )
    if stale not in document:
        raise ValueError("v2.1 report template description changed")
    return document.replace(stale, current)


def write(
    source: Path = DEFAULT_SOURCE,
    ridge_results: Path = DEFAULT_RIDGE_RESULTS,
    calibration: Path = DEFAULT_CALIBRATION,
    wide_closure_results: Path | None = DEFAULT_WIDE_CLOSURE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
    *,
    workers: int = 8,
) -> Path:
    artifact = assemble(
        source,
        ridge_results,
        calibration,
        wide_closure_results,
        output,
        workers=workers,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "winners.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "index.html").write_text(
        render(artifact), encoding="utf-8"
    )
    return output / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--ridge-results", type=Path, default=DEFAULT_RIDGE_RESULTS
    )
    parser.add_argument(
        "--calibration", type=Path, default=DEFAULT_CALIBRATION
    )
    parser.add_argument(
        "--wide-closure-results",
        type=Path,
        default=DEFAULT_WIDE_CLOSURE_RESULTS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(16, os.cpu_count() or 1),
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    print(write(
        args.source.resolve(),
        args.ridge_results.resolve(),
        args.calibration.resolve(),
        args.wide_closure_results.resolve(),
        args.output.resolve(),
        workers=args.workers,
    ))


if __name__ == "__main__":
    main()
