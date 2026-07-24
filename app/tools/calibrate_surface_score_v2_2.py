#!/usr/bin/env python3
"""Calibrate v2.2 against per-cell winner preferences and prior pair evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .surface_diagnostics import surface_score_v2_fraction


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WINNERS = (
    ROOT / "examples/round-control-parameter-maps-v2-1/winners.json"
)
DEFAULT_SELECTIONS = (
    ROOT
    / "examples/round-control-parameter-maps-v2-1"
    / "human_winner_selections.json"
)
DEFAULT_COMPARISON = (
    ROOT / "examples/surface-score-v1-v2-rank-comparison/comparison.json"
)
DEFAULT_PAIR_SELECTIONS = (
    ROOT
    / "examples/surface-score-v1-v2-rank-comparison"
    / "surface_score_v1_v2_selections.json"
)
DEFAULT_OUTPUT = ROOT / "examples/surface-score-v2-2-calibration/calibration.json"
CANDIDATE_EXPONENTS = (1.0, 1.5, 2.0, 2.5, 3.0)
CANDIDATE_MAXIMUM_FRACTIONS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
MINIMUM_FRACTION = 0.20


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fraction(coverage: float, exponent: float, maximum: float) -> float:
    position = float(np.clip((coverage - 25.0) / 25.0, 0.0, 1.0))
    return MINIMUM_FRACTION + (
        maximum - MINIMUM_FRACTION
    ) * position ** exponent


def _blend(candidate: dict[str, Any], fraction: float) -> float:
    return (
        (1.0 - fraction) * float(candidate["score_v1"])
        + fraction * float(candidate["score_v2_1"])
    )


def _winner_metrics(
    winners: dict[str, Any],
    selections: dict[str, str],
    exponent: float,
    maximum: float,
) -> dict[str, Any]:
    decisive_correct = 0
    decisive_count = 0
    tie_gaps = []
    identical_ties = 0
    for cell_id, cell in winners["cells"].items():
        choice = selections[cell_id]
        fraction = _fraction(
            float(cell["coverage_deg"]), exponent, maximum
        )
        difference = (
            _blend(cell["v2_1_winner"], fraction)
            - _blend(cell["v1_winner"], fraction)
        )
        if choice == "tie":
            tie_gaps.append(abs(difference))
            if not cell["winner_changed"]:
                identical_ties += 1
        else:
            decisive_count += 1
            decisive_correct += (
                (difference > 0.0) == (choice == "v2.1")
            )
    return {
        "decisive_correct": decisive_correct,
        "decisive_count": decisive_count,
        "decisive_agreement": decisive_correct / decisive_count,
        "tie_count": len(tie_gaps),
        "mean_absolute_tie_score_gap": float(np.mean(tie_gaps)),
        "identical_winner_ties": identical_ties,
    }


def _prior_pair_agreement(
    comparison: dict[str, Any],
    selections: dict[str, Any],
    exponent: float,
    maximum: float,
) -> dict[str, Any]:
    by_hash = {
        row["response_sha256"]: row for row in comparison["candidates"]
    }
    correct = 0
    count = 0
    for selection in selections["selections"].values():
        if selection["choice"] == "tie":
            continue
        candidates = [
            by_hash[selection[key]["response_sha256"]]
            for key in ("plot_1", "plot_2")
        ]
        scores = []
        for candidate in candidates:
            fraction = _fraction(
                float(candidate["coverage_deg"]), exponent, maximum
            )
            scores.append(
                (1.0 - fraction) * float(candidate["score_v1"])
                + fraction * float(candidate["score_v2"])
            )
        correct += (
            (scores[0] > scores[1])
            == (selection["choice"] == "plot_1")
        )
        count += 1
    return {
        "correct": correct,
        "count": count,
        "agreement": correct / count,
    }


def calibrate(
    winners_path: Path = DEFAULT_WINNERS,
    selections_path: Path = DEFAULT_SELECTIONS,
    comparison_path: Path = DEFAULT_COMPARISON,
    pair_selections_path: Path = DEFAULT_PAIR_SELECTIONS,
) -> dict[str, Any]:
    winners = json.loads(winners_path.read_text(encoding="utf-8"))
    selections = json.loads(selections_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    pair_selections = json.loads(
        pair_selections_path.read_text(encoding="utf-8")
    )
    if (
        selections["winner_artifact_content_sha256"]
        != winners["content_sha256"]
    ):
        raise ValueError("winner selections do not match winners artifact")
    candidates = []
    for exponent in CANDIDATE_EXPONENTS:
        for maximum in CANDIDATE_MAXIMUM_FRACTIONS:
            candidates.append({
                "exponent": exponent,
                "maximum_v2_fraction": maximum,
                "winner_preferences": _winner_metrics(
                    winners,
                    selections["selections"],
                    exponent,
                    maximum,
                ),
                "prior_pair_preferences": _prior_pair_agreement(
                    comparison,
                    pair_selections,
                    exponent,
                    maximum,
                ),
            })
    selected = max(candidates, key=lambda row: (
        row["winner_preferences"]["decisive_agreement"],
        row["prior_pair_preferences"]["agreement"],
        -row["exponent"],
        -row["maximum_v2_fraction"],
    ))
    implemented_fractions = {
        str(coverage): surface_score_v2_fraction(coverage, "v2.2")
        for coverage in (25, 30, 35, 40, 45, 50)
    }
    return {
        "schema_version": 1,
        "status": "calibrated_not_independently_validated",
        "score_revision": "v2.2",
        "source_hashes": {
            str(path.relative_to(ROOT)): _file_hash(path)
            for path in (
                winners_path,
                selections_path,
                comparison_path,
                pair_selections_path,
            )
        },
        "candidate_family": {
            "formula": (
                "0.20 + (maximum - 0.20) * "
                "clip((coverage_deg - 25) / 25, 0, 1) ** exponent"
            ),
            "exponents": list(CANDIDATE_EXPONENTS),
            "maximum_v2_fractions":
                list(CANDIDATE_MAXIMUM_FRACTIONS),
            "selection_order": [
                "winner decisive agreement descending",
                "prior pair agreement descending",
                "exponent ascending",
                "maximum v2 fraction ascending",
            ],
        },
        "selected": selected,
        "implemented_fractions": implemented_fractions,
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = calibrate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
