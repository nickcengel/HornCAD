#!/usr/bin/env python3
"""Evaluate the v2.1 narrow-coverage correction against saved comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .surface_diagnostics import (
    NARROW_COVERAGE_FULL_CORRECTION_DEG,
    NARROW_COVERAGE_MINIMUM_V2_FRACTION,
    NARROW_COVERAGE_NO_CORRECTION_DEG,
    SURFACE_SCORE_V2_REVISION,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "examples/surface-score-v1-v2-rank-comparison"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _v2_fraction(coverage_deg: float) -> float:
    position = np.clip(
        (
            coverage_deg - NARROW_COVERAGE_FULL_CORRECTION_DEG
        ) / (
            NARROW_COVERAGE_NO_CORRECTION_DEG
            - NARROW_COVERAGE_FULL_CORRECTION_DEG
        ),
        0.0,
        1.0,
    )
    return float(
        NARROW_COVERAGE_MINIMUM_V2_FRACTION
        + (1.0 - NARROW_COVERAGE_MINIMUM_V2_FRACTION) * position
    )


def _revised_score(candidate: dict[str, Any]) -> float:
    fraction = _v2_fraction(float(candidate["coverage_deg"]))
    return float(
        fraction * float(candidate["score_v2"])
        + (1.0 - fraction) * float(candidate["score_v1"])
    )


def _summary(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any]:
    judged = [row for row in rows if row["preferred"] is not None]
    correct = sum(
        (row["scores"][score_key][0] > row["scores"][score_key][1])
        == (row["preferred"] == 0)
        for row in judged
    )
    return {
        "judged_pairs": len(judged),
        "correct_pairs": correct,
        "pairwise_agreement": correct / len(judged) if judged else None,
    }


def calibrate(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    comparison_path = root / "comparison.json"
    selection_path = root / "surface_score_v1_v2_selections.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    selections = json.loads(selection_path.read_text(encoding="utf-8"))
    if selections["artifact_content_sha256"] != comparison["content_sha256"]:
        raise ValueError("selections do not match the comparison artifact")
    by_hash = {
        row["response_sha256"]: row for row in comparison["candidates"]
    }
    rows = []
    for selection in selections["selections"].values():
        candidates = [
            by_hash[selection[key]["response_sha256"]]
            for key in ("plot_1", "plot_2")
        ]
        choice = selection["choice"]
        rows.append({
            "coverage_filter": selection["filter"]["coverage_deg"],
            "preferred": (
                0 if choice == "plot_1" else 1 if choice == "plot_2" else None
            ),
            "scores": {
                "v1": [float(row["score_v1"]) for row in candidates],
                "v2": [float(row["score_v2"]) for row in candidates],
                SURFACE_SCORE_V2_REVISION: [
                    _revised_score(row) for row in candidates
                ],
            },
        })
    groups = {
        "all": rows,
        **{
            f"{coverage}deg": [
                row for row in rows
                if row["coverage_filter"] == str(coverage)
            ]
            for coverage in (25, 30, 35, 40, 45, 50)
        },
    }
    metrics = ("v1", "v2", SURFACE_SCORE_V2_REVISION)
    return {
        "schema_version": 1,
        "status": "calibration_on_recorded_pairs_not_independent_validation",
        "comparison_sha256": _file_hash(comparison_path),
        "selections_sha256": _file_hash(selection_path),
        "selection_counts": dict(Counter(
            selection["choice"]
            for selection in selections["selections"].values()
        )),
        "revision": SURFACE_SCORE_V2_REVISION,
        "adaptation": {
            "full_correction_through_deg":
                NARROW_COVERAGE_FULL_CORRECTION_DEG,
            "no_correction_from_deg": NARROW_COVERAGE_NO_CORRECTION_DEG,
            "minimum_v2_fraction": NARROW_COVERAGE_MINIMUM_V2_FRACTION,
        },
        "results": {
            name: {
                metric: _summary(group, metric) for metric in metrics
            }
            for name, group in groups.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    output = args.root / "surface_score_v2_1_pairwise_calibration.json"
    output.write_text(
        json.dumps(calibrate(args.root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
