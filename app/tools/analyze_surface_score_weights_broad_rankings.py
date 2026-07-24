#!/usr/bin/env python3
"""Test cell-ranking weight fits against the earlier broad ranking experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from .fit_surface_score_weights_to_cell_rankings import (
    FAMILIES,
    ROOT,
    STARTS,
    _component_vector,
    fit_weights,
)
from .generate_surface_score_rank_comparison import _evaluation_grid
from .interactive_results import load_run
from .surface_diagnostics import surface_diagnostics, surface_score_v2


DEFAULT_PRIOR_ROOT = ROOT / "examples/surface-diagnostic-ranking-experiment"
DEFAULT_CELL_ROOT = ROOT / "examples/surface-score-v2-2-cell-ranking-game"
OUTPUT_NAME = "broad_range_weight_test.json"
V2_WEIGHTS = {
    "profile_rms": 0.30,
    "slice_energy": 0.20,
    "mean_containment": 0.05,
    "outward_rise": 0.05,
    "beamwidth_quality": 0.40,
}


def _without_weights(*excluded: str) -> dict[str, float]:
    retained = {
        key: value for key, value in V2_WEIGHTS.items()
        if key not in excluded
    }
    total = sum(retained.values())
    return {
        key: (value / total if key in retained else 0.0)
        for key, value in V2_WEIGHTS.items()
    }


def _load_rounds(prior_root: Path) -> list[dict[str, Any]]:
    experiment = json.loads((prior_root / "experiment.json").read_text())
    private = json.loads((prior_root / "private_manifest.json").read_text())
    rankings = json.loads((prior_root / "rankings.json").read_text())
    features: dict[str, dict[str, float]] = {}
    fixed_scores: dict[str, dict[str, float]] = {}
    for plot_id, item in private["plots"].items():
        run = load_run((ROOT / item["source_path"]).parent)
        result = surface_diagnostics(run, _evaluation_grid(run), fixed_band=True)
        if result["status"] != "available":
            raise ValueError(f"{plot_id}: surface diagnostics unavailable")
        features[plot_id] = _component_vector(result, run)
        fixed_scores[plot_id] = {
            "v1": float(result["score_v1"]["overall_percent"]),
            "v2": float(surface_score_v2(
                result,
                run.get("mouth_dimensions_mm"),
                candidate_name="contour_forward",
                revision="v2",
            )["overall_percent"]),
            "v2_2": float(surface_score_v2(
                result,
                run.get("mouth_dimensions_mm"),
                candidate_name="contour_forward",
                revision="v2.2",
            )["overall_percent"]),
        }
        for name, weights in {
            "v2_without_containment": _without_weights(
                "mean_containment"
            ),
            "v2_without_outward_rise": _without_weights("outward_rise"),
            "v2_without_both": _without_weights(
                "mean_containment", "outward_rise"
            ),
        }.items():
            fixed_scores[plot_id][name] = float(surface_score_v2(
                result,
                run.get("mouth_dimensions_mm"),
                weights=weights,
                candidate_name=name,
                revision="v2",
            )["overall_percent"])
    rounds = []
    for item in experiment["rounds"]:
        number = int(item["round"])
        rounds.append({
            "round": number,
            "population": "broad" if number <= 10 else "close",
            "order": rankings["orders"][str(number)],
            "features": features,
            "fixed_scores": fixed_scores,
        })
    return rounds


def _evaluate_scores(
    ranking: list[str], scores: dict[str, float]
) -> dict[str, Any]:
    score_order = sorted(ranking, key=lambda plot_id: (-scores[plot_id], plot_id))
    rank = {plot_id: index for index, plot_id in enumerate(score_order)}
    rho = float(spearmanr(
        range(len(ranking)), [rank[plot_id] for plot_id in ranking]
    ).statistic)
    pair_count = len(ranking) * (len(ranking) - 1) // 2
    concordant = sum(
        rank[ranking[left]] < rank[ranking[right]]
        for left in range(len(ranking))
        for right in range(left + 1, len(ranking))
    )
    return {
        "spearman": rho,
        "pairwise_agreement": concordant / pair_count,
        "top_1_match": score_order[0] == ranking[0],
        "human_winner_score_rank": rank[ranking[0]] + 1,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "round_count": len(results),
        "mean_spearman": float(np.mean([
            item["spearman"] for item in results
        ])),
        "mean_pairwise_agreement": float(np.mean([
            item["pairwise_agreement"] for item in results
        ])),
        "top_1_matches": int(sum(item["top_1_match"] for item in results)),
        "mean_human_winner_score_rank": float(np.mean([
            item["human_winner_score_rank"] for item in results
        ])),
    }


def _weighted_scores(
    round_item: dict[str, Any],
    components: tuple[str, ...],
    weights: np.ndarray,
) -> dict[str, float]:
    return {
        plot_id: float(sum(
            weight * round_item["features"][plot_id][component]
            for component, weight in zip(components, weights, strict=True)
        ))
        for plot_id in round_item["order"]
    }


def _evaluate_weights(
    rounds: list[dict[str, Any]],
    components: tuple[str, ...],
    weights: np.ndarray,
) -> dict[str, Any]:
    results = [
        {
            "round": item["round"],
            **_evaluate_scores(
                item["order"],
                _weighted_scores(item, components, weights),
            ),
        }
        for item in rounds
    ]
    return {"summary": _summarize(results), "rounds": results}


def _fit_rounds(
    rounds: list[dict[str, Any]],
    components: tuple[str, ...],
    start: np.ndarray,
) -> np.ndarray:
    cells = [
        {"order": item["order"], "features": item["features"]}
        for item in rounds
    ]
    return fit_weights(cells, components, start)


def _leave_one_round_out(
    rounds: list[dict[str, Any]],
    components: tuple[str, ...],
    start: np.ndarray,
) -> dict[str, Any]:
    held_out = []
    weights = []
    for index, item in enumerate(rounds):
        fitted = _fit_rounds(
            [other for other_index, other in enumerate(rounds)
             if other_index != index],
            components,
            start,
        )
        weights.append(fitted)
        held_out.append({
            "round": item["round"],
            "weights": dict(zip(components, fitted, strict=True)),
            **_evaluate_scores(
                item["order"], _weighted_scores(item, components, fitted)
            ),
        })
    weight_matrix = np.asarray(weights)
    return {
        "summary": _summarize(held_out),
        "weight_mean": dict(zip(
            components, np.mean(weight_matrix, axis=0), strict=True
        )),
        "weight_min": dict(zip(
            components, np.min(weight_matrix, axis=0), strict=True
        )),
        "weight_max": dict(zip(
            components, np.max(weight_matrix, axis=0), strict=True
        )),
        "held_out_rounds": held_out,
    }


def _fixed_score_test(
    rounds: list[dict[str, Any]], name: str
) -> dict[str, Any]:
    results = [
        {
            "round": item["round"],
            **_evaluate_scores(
                item["order"],
                {
                    plot_id: item["fixed_scores"][plot_id][name]
                    for plot_id in item["order"]
                },
            ),
        }
        for item in rounds
    ]
    return {"summary": _summarize(results), "rounds": results}


def analyze(prior_root: Path, cell_root: Path) -> dict[str, Any]:
    rounds = _load_rounds(prior_root)
    broad = [item for item in rounds if item["population"] == "broad"]
    close = [item for item in rounds if item["population"] == "close"]
    cell_fit = json.loads((cell_root / "weight_fit.json").read_text())
    family = cell_fit["families"]["combined_components"]
    all_components = tuple(family["components"])
    cell_weights = np.asarray([
        family["global_weights"][component] for component in all_components
    ])
    reduced_components = tuple(
        component for component in all_components
        if component not in {"mean_containment", "outward_rise"}
    )
    reduced_start = np.asarray([
        STARTS["combined_components"][all_components.index(component)]
        for component in reduced_components
    ])
    reduced_start /= np.sum(reduced_start)

    broad_fit = _fit_rounds(
        broad, all_components, STARTS["combined_components"]
    )
    broad_reduced_fit = _fit_rounds(
        broad, reduced_components, reduced_start
    )
    fixed = {
        name: {
            "broad": _fixed_score_test(broad, name),
            "close": _fixed_score_test(close, name),
        }
        for name in (
            "v1",
            "v2",
            "v2_2",
            "v2_without_containment",
            "v2_without_outward_rise",
            "v2_without_both",
        )
    }
    return {
        "schema_version": 1,
        "status": "diagnostic_only_no_score_change",
        "study_id": "surface-score-broad-range-weight-test",
        "evidence": {
            "broad_rounds": (
                "Prior ranking rounds 1-10; each round sampled one candidate "
                "from every v1 score decile."
            ),
            "close_rounds": (
                "Prior ranking rounds 11-20; each round sampled ten nearby "
                "v1 scores around one quantile."
            ),
            "candidate_count": 200,
            "pair_count_per_population": 450,
        },
        "fixed_score_tests": fixed,
        "v2_ablation_weights": {
            "v2": V2_WEIGHTS,
            "v2_without_containment": _without_weights(
                "mean_containment"
            ),
            "v2_without_outward_rise": _without_weights("outward_rise"),
            "v2_without_both": _without_weights(
                "mean_containment", "outward_rise"
            ),
        },
        "cell_fit_out_of_sample": {
            "weights": dict(zip(
                all_components, cell_weights, strict=True
            )),
            "broad": _evaluate_weights(
                broad, all_components, cell_weights
            ),
            "close": _evaluate_weights(
                close, all_components, cell_weights
            ),
        },
        "broad_fit_all_components": {
            "weights": dict(zip(
                all_components, broad_fit, strict=True
            )),
            "broad_in_sample": _evaluate_weights(
                broad, all_components, broad_fit
            ),
            "close_out_of_sample": _evaluate_weights(
                close, all_components, broad_fit
            ),
            "broad_leave_one_round_out": _leave_one_round_out(
                broad, all_components, STARTS["combined_components"]
            ),
        },
        "broad_fit_without_containment_or_rise": {
            "weights": dict(zip(
                reduced_components, broad_reduced_fit, strict=True
            )),
            "broad_in_sample": _evaluate_weights(
                broad, reduced_components, broad_reduced_fit
            ),
            "close_out_of_sample": _evaluate_weights(
                close, reduced_components, broad_reduced_fit
            ),
            "broad_leave_one_round_out": _leave_one_round_out(
                broad, reduced_components, reduced_start
            ),
        },
        "interpretation_guardrail": (
            "Broad rankings were previously used to select the v2 contour "
            "diagnostic, so this is independent of the later cell-weight fit "
            "but not independent of v2 component design."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prior_root", type=Path, nargs="?", default=DEFAULT_PRIOR_ROOT
    )
    parser.add_argument(
        "--cell-root", type=Path, default=DEFAULT_CELL_ROOT
    )
    args = parser.parse_args()
    result = analyze(args.prior_root.resolve(), args.cell_root.resolve())
    output = args.prior_root / OUTPUT_NAME
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    main()
