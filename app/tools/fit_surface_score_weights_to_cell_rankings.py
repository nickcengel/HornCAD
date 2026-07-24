#!/usr/bin/env python3
"""Fit constrained surface-score component weights to completed cell rankings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import spearmanr

from .generate_surface_score_rank_comparison import _evaluation_grid
from .interactive_results import load_run
from .surface_diagnostics import surface_diagnostics, surface_score_v2


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "examples/surface-score-v2-2-cell-ranking-game"
FAMILIES = {
    "v1_components": (
        "profile_rms",
        "slice_energy",
        "mean_containment",
        "outward_rise",
        "minus_six_line",
    ),
    "v2_components": (
        "profile_rms",
        "slice_energy",
        "mean_containment",
        "outward_rise",
        "beamwidth_quality",
    ),
    "combined_components": (
        "profile_rms",
        "slice_energy",
        "mean_containment",
        "outward_rise",
        "minus_six_line",
        "beamwidth_quality",
    ),
}
STARTS = {
    "v1_components": np.asarray([0.30, 0.25, 0.20, 0.15, 0.10]),
    "v2_components": np.asarray([0.30, 0.20, 0.05, 0.05, 0.40]),
    "combined_components": np.asarray(
        [0.25, 0.20, 0.10, 0.10, 0.10, 0.25]
    ),
}


def _component_vector(
    result: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, float]:
    original_v2 = surface_score_v2(
        result,
        run.get("mouth_dimensions_mm"),
        candidate_name="contour_forward",
        revision="v2",
    )
    axis = original_v2["axis_weights"]
    values = {}
    for component in FAMILIES["combined_components"]:
        source = (
            result["score_v1"] if component == "minus_six_line"
            else original_v2
        )
        values[component] = float(sum(
            axis[plane] * source[plane]["components"][component]
            for plane in ("horizontal", "vertical")
        ))
    return values


def _load_cells(root: Path) -> list[dict[str, Any]]:
    experiment = json.loads((root / "experiment.json").read_text())
    private = json.loads((root / "private_manifest.json").read_text())
    rankings = json.loads(
        (root / "surface_score_v2_2_cell_rankings.json").read_text()
    )
    mapping = private["plots"]
    features = {}
    for plot_id, item in mapping.items():
        run = load_run((ROOT / item["source_path"]).parent)
        result = surface_diagnostics(
            run, _evaluation_grid(run), fixed_band=True
        )
        if result["status"] != "available":
            raise ValueError(f"{plot_id}: surface diagnostics unavailable")
        features[plot_id] = _component_vector(result, run)
    cells = []
    for round_item in experiment["rounds"]:
        order = rankings["orders"][str(round_item["round"])]
        cells.append({
            "cell_id": round_item["cell_id"],
            "coverage_deg": round_item["coverage_deg"],
            "mouth_mm": round_item["mouth_mm"],
            "order": order,
            "features": features,
        })
    return cells


def _pair_differences(
    cells: list[dict[str, Any]],
    components: tuple[str, ...],
) -> np.ndarray:
    differences = []
    for cell in cells:
        matrix = np.asarray([
            [cell["features"][plot_id][name] for name in components]
            for plot_id in cell["order"]
        ])
        differences.extend(
            matrix[left] - matrix[right]
            for left in range(len(matrix))
            for right in range(left + 1, len(matrix))
        )
    return np.asarray(differences)


def fit_weights(
    cells: list[dict[str, Any]],
    components: tuple[str, ...],
    start: np.ndarray | None = None,
) -> np.ndarray:
    differences = _pair_differences(cells, components)
    if not len(differences):
        raise ValueError("no ranking pairs available")
    initial = (
        np.asarray(start, dtype=float)
        if start is not None
        else np.full(len(components), 1.0 / len(components))
    )
    initial = initial / np.sum(initial)

    def loss(weights: np.ndarray) -> float:
        margins = differences @ weights
        return float(np.mean(np.logaddexp(0.0, -margins)))

    result = minimize(
        loss,
        initial,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * len(components),
        constraints=[{
            "type": "eq",
            "fun": lambda weights: float(np.sum(weights) - 1.0),
        }],
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    if not result.success:
        raise ValueError(f"weight fit failed: {result.message}")
    weights = np.maximum(0.0, np.asarray(result.x))
    return weights / np.sum(weights)


def _evaluate_cell(
    cell: dict[str, Any],
    components: tuple[str, ...],
    weights: np.ndarray,
) -> dict[str, Any]:
    order = cell["order"]
    scores = {
        plot_id: float(sum(
            weight * cell["features"][plot_id][component]
            for component, weight in zip(components, weights, strict=True)
        ))
        for plot_id in order
    }
    score_order = sorted(order, key=lambda plot_id: (-scores[plot_id], plot_id))
    rank = {plot_id: index for index, plot_id in enumerate(score_order)}
    rho = float(spearmanr(
        range(len(order)), [rank[plot_id] for plot_id in order]
    ).statistic)
    concordant = sum(
        rank[order[left]] < rank[order[right]]
        for left in range(len(order))
        for right in range(left + 1, len(order))
    )
    return {
        "spearman": rho,
        "pairwise_agreement": concordant / 45,
        "top_1_match": score_order[0] == order[0],
        "human_winner_score_rank": rank[order[0]] + 1,
    }


def _summarize(values: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(values),
        "mean_spearman": float(np.mean([
            value["spearman"] for value in values
        ])),
        "median_spearman": float(np.median([
            value["spearman"] for value in values
        ])),
        "mean_pairwise_agreement": float(np.mean([
            value["pairwise_agreement"] for value in values
        ])),
        "top_1_matches": sum(value["top_1_match"] for value in values),
        "mean_human_winner_score_rank": float(np.mean([
            value["human_winner_score_rank"] for value in values
        ])),
    }


def _cross_validate(
    cells: list[dict[str, Any]],
    family: str,
    *,
    coverage_specific: bool,
) -> dict[str, Any]:
    components = FAMILIES[family]
    held_out = []
    for index, cell in enumerate(cells):
        training = [
            other for other_index, other in enumerate(cells)
            if other_index != index
            and (
                not coverage_specific
                or other["coverage_deg"] == cell["coverage_deg"]
            )
        ]
        weights = fit_weights(training, components, STARTS[family])
        held_out.append({
            "cell_id": cell["cell_id"],
            "coverage_deg": cell["coverage_deg"],
            "weights": dict(zip(components, weights, strict=True)),
            **_evaluate_cell(cell, components, weights),
        })
    return {
        "mode": (
            "leave-one-cell-out within coverage"
            if coverage_specific else "leave-one-cell-out global"
        ),
        "summary": _summarize(held_out),
        "held_out_cells": held_out,
    }


def fit(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    cells = _load_cells(root)
    families = {}
    for family, components in FAMILIES.items():
        weights = fit_weights(cells, components, STARTS[family])
        in_sample = [
            _evaluate_cell(cell, components, weights) for cell in cells
        ]
        by_coverage = {}
        for coverage in (30, 35, 40, 45, 50):
            selected = [
                cell for cell in cells if cell["coverage_deg"] == coverage
            ]
            local_weights = fit_weights(
                selected, components, STARTS[family]
            )
            by_coverage[str(coverage)] = {
                "weights": dict(zip(
                    components, local_weights, strict=True
                )),
                "in_sample": _summarize([
                    _evaluate_cell(cell, components, local_weights)
                    for cell in selected
                ]),
            }
        families[family] = {
            "components": list(components),
            "global_weights": dict(zip(
                components, weights, strict=True
            )),
            "global_in_sample": _summarize(in_sample),
            "global_leave_one_cell_out": _cross_validate(
                cells, family, coverage_specific=False
            ),
            "coverage_specific_leave_one_cell_out": _cross_validate(
                cells, family, coverage_specific=True
            ),
            "coverage_specific_full_fit": by_coverage,
        }
    return {
        "schema_version": 1,
        "status": "exploratory_fit_not_released",
        "study_id": "surface-score-v2-2-cell-ranking-weight-fit",
        "cell_count": len(cells),
        "candidate_count": sum(len(cell["order"]) for cell in cells),
        "pair_count": len(cells) * 45,
        "fit_method": (
            "nonnegative weights summing to one; pairwise logistic loss; "
            "whole-cell cross-validation"
        ),
        "families": families,
        "limitations": [
            "The same rankings select and evaluate the candidate weight "
            "families; cross-validation limits but does not remove this bias.",
            "The forced total order contains no ties or confidence values.",
            "Coverage-specific fits have only four training cells per held-out "
            "fold and should be treated as high variance.",
            "The candidate pool was enriched by v1 and v2.2 rather than "
            "sampled randomly.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=DEFAULT_ROOT)
    args = parser.parse_args()
    result = fit(args.root.resolve())
    output = args.root / "weight_fit.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(output)


if __name__ == "__main__":
    main()
