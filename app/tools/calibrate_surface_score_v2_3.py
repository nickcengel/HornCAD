#!/usr/bin/env python3
"""Calibrate a general surface score with a local core and soft guardrails."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.stats import spearmanr

from .analyze_surface_score_weights_broad_rankings import (
    DEFAULT_CELL_ROOT,
    DEFAULT_PRIOR_ROOT,
    _load_rounds,
)
from .fit_surface_score_weights_to_cell_rankings import (
    ROOT,
    _load_cells,
    fit_weights,
)
from .surface_diagnostics import (
    SURFACE_SCORE_V2_3_CONTAINMENT_EXPONENT,
    SURFACE_SCORE_V2_3_CONTAINMENT_THRESHOLD,
    SURFACE_SCORE_V2_3_CORE_FRACTION,
    SURFACE_SCORE_V2_3_CORE_WEIGHTS,
    SURFACE_SCORE_V2_3_OUTWARD_RISE_EXPONENT,
    SURFACE_SCORE_V2_3_OUTWARD_RISE_SCORE_THRESHOLD,
    surface_score_v2_fraction,
)


OUTPUT_NAME = "surface_score_v2_3_calibration.json"
REPORT_NAME = "surface_score_v2_3_calibration.md"
CORE_COMPONENTS = (
    "profile_rms",
    "slice_energy",
    "minus_six_line",
    "beamwidth_quality",
)
V1_WEIGHTS = {
    "profile_rms": 0.30,
    "slice_energy": 0.25,
    "mean_containment": 0.20,
    "outward_rise": 0.15,
    "minus_six_line": 0.10,
    "beamwidth_quality": 0.0,
}
V2_WEIGHTS = {
    "profile_rms": 0.30,
    "slice_energy": 0.20,
    "mean_containment": 0.05,
    "outward_rise": 0.05,
    "minus_six_line": 0.0,
    "beamwidth_quality": 0.40,
}


@dataclass(frozen=True)
class Guardrail:
    core_fraction: float
    containment_threshold: float
    outward_rise_threshold: float
    containment_exponent: float
    outward_rise_exponent: float

    @property
    def name(self) -> str:
        return (
            f"b{self.core_fraction:g}"
            f"-c{self.containment_threshold:g}"
            f"-o{self.outward_rise_threshold:g}"
            f"-ce{self.containment_exponent:g}"
            f"-oe{self.outward_rise_exponent:g}"
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "v2_3_core_fraction": self.core_fraction,
            "containment_threshold_percent":
                self.containment_threshold,
            "outward_rise_score_threshold_percent":
                self.outward_rise_threshold,
            "containment_exponent": self.containment_exponent,
            "outward_rise_exponent": self.outward_rise_exponent,
        }


def _guard_factor(value: float, threshold: float, exponent: float) -> float:
    if threshold <= 0 or exponent <= 0:
        return 1.0
    ratio = min(1.0, max(0.0, value / threshold))
    return float(ratio ** exponent)


def score_candidate(
    features: dict[str, float],
    core_weights: np.ndarray,
    guardrail: Guardrail,
    baseline_score: float,
) -> float:
    core = float(sum(
        weight * features[component]
        for component, weight in zip(
            CORE_COMPONENTS, core_weights, strict=True
        )
    ))
    containment_factor = _guard_factor(
        features["mean_containment"],
        guardrail.containment_threshold,
        guardrail.containment_exponent,
    )
    outward_factor = _guard_factor(
        features["outward_rise"],
        guardrail.outward_rise_threshold,
        guardrail.outward_rise_exponent,
    )
    guarded_core = core * containment_factor * outward_factor
    return (
        (1.0 - guardrail.core_fraction) * baseline_score
        + guardrail.core_fraction * guarded_core
    )


def _rank_statistics(
    order: list[str], score: Callable[[str], float]
) -> dict[str, Any]:
    predicted = sorted(order, key=lambda item: (-score(item), item))
    ranks = {item: index for index, item in enumerate(predicted)}
    rho = float(spearmanr(
        range(len(order)), [ranks[item] for item in order]
    ).statistic)
    pair_count = len(order) * (len(order) - 1) // 2
    agreement = sum(
        ranks[order[left]] < ranks[order[right]]
        for left in range(len(order))
        for right in range(left + 1, len(order))
    ) / pair_count
    return {
        "spearman": rho,
        "pairwise_agreement": agreement,
        "top_1_match": predicted[0] == order[0],
        "human_winner_score_rank": ranks[order[0]] + 1,
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "group_count": len(results),
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


def _evaluate_guardrail(
    groups: list[dict[str, Any]],
    core_weights: np.ndarray,
    guardrail: Guardrail,
) -> dict[str, Any]:
    results = []
    for group in groups:
        features = group["features"]
        if "fixed_scores" in group:
            baseline = {
                item: group["fixed_scores"][item]["v2_2"]
                for item in group["order"]
            }
        else:
            baseline = {
                item: _v2_2_score(
                    features[item], group["coverage_deg"]
                )
                for item in group["order"]
            }
        results.append({
            "group": group.get("cell_id", group.get("round")),
            **_rank_statistics(
                group["order"],
                lambda item: score_candidate(
                    features[item],
                    core_weights,
                    guardrail,
                    baseline[item],
                ),
            ),
        })
    return {"summary": _summary(results), "groups": results}


def _evaluate_fixed(
    groups: list[dict[str, Any]], score_name: str
) -> dict[str, Any]:
    results = []
    for group in groups:
        fixed = group["fixed_scores"]
        results.append({
            "group": group["round"],
            **_rank_statistics(
                group["order"],
                lambda item: fixed[item][score_name],
            ),
        })
    return {"summary": _summary(results), "groups": results}


def _v2_2_score(features: dict[str, float], coverage: float) -> float:
    fraction = surface_score_v2_fraction(coverage, "v2.2")
    return float(sum(
        (
            fraction * V2_WEIGHTS[component]
            + (1.0 - fraction) * V1_WEIGHTS[component]
        ) * features[component]
        for component in V1_WEIGHTS
    ))


def _evaluate_cell_v2_2(cells: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for cell in cells:
        results.append({
            "group": cell["cell_id"],
            **_rank_statistics(
                cell["order"],
                lambda item: _v2_2_score(
                    cell["features"][item], cell["coverage_deg"]
                ),
            ),
        })
    return {"summary": _summary(results), "groups": results}


def _candidate_grid() -> list[Guardrail]:
    return [
        Guardrail(
            core_fraction,
            c_threshold,
            o_threshold,
            c_exponent,
            o_exponent,
        )
        for core_fraction in (0.10, 0.20, 0.30, 0.40, 0.50)
        for c_threshold in (75.0, 80.0, 85.0, 90.0)
        for o_threshold in (60.0, 70.0, 80.0, 90.0)
        for c_exponent in (0.125, 0.25, 0.5, 1.0)
        for o_exponent in (0.125, 0.25, 0.5, 1.0)
    ]


def _broad_sort_key(item: dict[str, Any]) -> tuple[float, ...]:
    summary = item["broad"]["summary"]
    guardrail = item["guardrail"]
    return (
        summary["mean_spearman"],
        summary["mean_pairwise_agreement"],
        -guardrail["containment_exponent"],
        -guardrail["outward_rise_exponent"],
        -guardrail["containment_threshold_percent"],
        -guardrail["outward_rise_score_threshold_percent"],
        -guardrail["v2_3_core_fraction"],
    )


def _general_sort_key(item: dict[str, Any]) -> tuple[float, ...]:
    summaries = [
        item[population]["summary"]
        for population in ("broad", "close", "cell")
    ]
    guardrail = item["guardrail"]
    return (
        float(np.mean([
            summary["mean_spearman"] for summary in summaries
        ])),
        float(np.mean([
            summary["mean_pairwise_agreement"] for summary in summaries
        ])),
        -guardrail["v2_3_core_fraction"],
        -guardrail["containment_exponent"],
        -guardrail["outward_rise_exponent"],
    )


def _fit_core(cells: list[dict[str, Any]]) -> np.ndarray:
    return fit_weights(
        cells,
        CORE_COMPONENTS,
        np.asarray([0.40, 0.30, 0.10, 0.20]),
    )


def _cell_leave_one_out(
    cells: list[dict[str, Any]], guardrail: Guardrail
) -> dict[str, Any]:
    held_out = []
    weight_rows = []
    for index, cell in enumerate(cells):
        weights = _fit_core([
            other for other_index, other in enumerate(cells)
            if other_index != index
        ])
        weight_rows.append(weights)
        features = cell["features"]
        baseline = {
            item: _v2_2_score(
                features[item], cell["coverage_deg"]
            )
            for item in cell["order"]
        }
        held_out.append({
            "group": cell["cell_id"],
            "weights": dict(zip(
                CORE_COMPONENTS, weights, strict=True
            )),
            **_rank_statistics(
                cell["order"],
                lambda item: score_candidate(
                    features[item],
                    weights,
                    guardrail,
                    baseline[item],
                ),
            ),
        })
    matrix = np.asarray(weight_rows)
    return {
        "summary": _summary(held_out),
        "weight_mean": dict(zip(
            CORE_COMPONENTS, np.mean(matrix, axis=0), strict=True
        )),
        "weight_min": dict(zip(
            CORE_COMPONENTS, np.min(matrix, axis=0), strict=True
        )),
        "weight_max": dict(zip(
            CORE_COMPONENTS, np.max(matrix, axis=0), strict=True
        )),
        "held_out_cells": held_out,
    }


def _broad_nested_selection(
    broad: list[dict[str, Any]],
    core_weights: np.ndarray,
    candidates: list[Guardrail],
) -> dict[str, Any]:
    held_out = []
    selections: dict[str, int] = {}
    for index, group in enumerate(broad):
        training = [
            other for other_index, other in enumerate(broad)
            if other_index != index
        ]
        rows = [
            {
                "guardrail": candidate.as_dict(),
                "broad": _evaluate_guardrail(
                    training, core_weights, candidate
                ),
                "_candidate": candidate,
            }
            for candidate in candidates
        ]
        selected_row = max(rows, key=_broad_sort_key)
        selected = selected_row["_candidate"]
        selections[selected.name] = selections.get(selected.name, 0) + 1
        features = group["features"]
        baseline = {
            item: group["fixed_scores"][item]["v2_2"]
            for item in group["order"]
        }
        held_out.append({
            "group": group["round"],
            "selected_guardrail": selected.as_dict(),
            **_rank_statistics(
                group["order"],
                lambda item: score_candidate(
                    features[item],
                    core_weights,
                    selected,
                    baseline[item],
                ),
            ),
        })
    return {
        "summary": _summary(held_out),
        "selection_counts": selections,
        "held_out_rounds": held_out,
    }


def _trigger_summary(
    groups: list[dict[str, Any]], guardrail: Guardrail
) -> dict[str, Any]:
    rows = [
        group["features"][item]
        for group in groups
        for item in group["order"]
    ]
    containment = np.asarray([
        row["mean_containment"] for row in rows
    ])
    outward = np.asarray([row["outward_rise"] for row in rows])
    return {
        "candidate_count": len(rows),
        "containment_trigger_count": int(np.sum(
            containment < guardrail.containment_threshold
        )),
        "outward_rise_trigger_count": int(np.sum(
            outward < guardrail.outward_rise_threshold
        )),
        "either_trigger_count": int(np.sum(
            (containment < guardrail.containment_threshold)
            | (outward < guardrail.outward_rise_threshold)
        )),
    }


def _paired_comparison(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    seed: int,
) -> dict[str, Any]:
    metrics = (
        "spearman",
        "pairwise_agreement",
        "top_1_match",
        "human_winner_score_rank",
    )
    candidate_rows = candidate["groups"]
    baseline_rows = baseline["groups"]
    if [row["group"] for row in candidate_rows] != [
        row["group"] for row in baseline_rows
    ]:
        raise ValueError("paired comparison groups do not align")
    rng = np.random.default_rng(seed)
    indices = rng.integers(
        0, len(candidate_rows), size=(20_000, len(candidate_rows))
    )
    result = {}
    for metric in metrics:
        differences = np.asarray([
            float(candidate_row[metric]) - float(baseline_row[metric])
            for candidate_row, baseline_row
            in zip(candidate_rows, baseline_rows, strict=True)
        ])
        samples = np.mean(differences[indices], axis=1)
        result[metric] = {
            "mean_delta": float(np.mean(differences)),
            "bootstrap_95_percent_interval": [
                float(np.percentile(samples, 2.5)),
                float(np.percentile(samples, 97.5)),
            ],
        }
    return result


def calibrate(
    prior_root: Path = DEFAULT_PRIOR_ROOT,
    cell_root: Path = DEFAULT_CELL_ROOT,
) -> dict[str, Any]:
    prior = _load_rounds(prior_root)
    broad = prior[:10]
    close = prior[10:]
    cells = _load_cells(cell_root)
    core_weights = _fit_core(cells)
    grid = _candidate_grid()
    rows = [
        {
            "guardrail": candidate.as_dict(),
            "broad": _evaluate_guardrail(
                broad, core_weights, candidate
            ),
            "close": _evaluate_guardrail(
                close, core_weights, candidate
            ),
            "cell": _evaluate_guardrail(
                cells, core_weights, candidate
            ),
            "_candidate": candidate,
        }
        for candidate in grid
    ]
    baseline_v2_2 = {
        "broad": _evaluate_fixed(broad, "v2_2"),
        "close": _evaluate_fixed(close, "v2_2"),
        "cell": _evaluate_cell_v2_2(cells),
    }
    eligible = [
        row for row in rows
        if all(
            row[population]["summary"]["mean_spearman"]
            >= baseline_v2_2[population]["summary"]["mean_spearman"] - 0.005
            and row[population]["summary"]["mean_pairwise_agreement"]
            >= baseline_v2_2[population]["summary"][
                "mean_pairwise_agreement"
            ] - 0.005
            for population in ("broad", "close", "cell")
        )
    ]
    if not eligible:
        raise ValueError("no candidate passed the general-score guardrails")
    selected_row = max(eligible, key=_general_sort_key)
    selected = selected_row["_candidate"]
    implemented_guardrail = Guardrail(
        SURFACE_SCORE_V2_3_CORE_FRACTION,
        SURFACE_SCORE_V2_3_CONTAINMENT_THRESHOLD,
        SURFACE_SCORE_V2_3_OUTWARD_RISE_SCORE_THRESHOLD,
        SURFACE_SCORE_V2_3_CONTAINMENT_EXPONENT,
        SURFACE_SCORE_V2_3_OUTWARD_RISE_EXPONENT,
    )
    if selected != implemented_guardrail:
        raise ValueError(
            "selected calibration guardrail does not match implementation"
        )
    if not np.allclose(
        core_weights,
        np.asarray([
            SURFACE_SCORE_V2_3_CORE_WEIGHTS[name]
            for name in CORE_COMPONENTS
        ]),
        rtol=0,
        atol=1e-6,
    ):
        raise ValueError(
            "selected calibration core does not match implementation"
        )
    selected_broad = _evaluate_guardrail(
        broad, core_weights, selected
    )
    selected_close = _evaluate_guardrail(
        close, core_weights, selected
    )
    selected_cells = _evaluate_guardrail(
        cells, core_weights, selected
    )
    no_guard = Guardrail(1.0, 0.0, 0.0, 0.0, 0.0)
    ranked_rows = sorted(eligible, key=_general_sort_key, reverse=True)
    candidate_table = [
        {
            "rank": index,
            "guardrail": row["guardrail"],
            "broad": row["broad"]["summary"],
            "close": row["close"]["summary"],
            "cell": row["cell"]["summary"],
        }
        for index, row in enumerate(ranked_rows[:25], start=1)
    ]
    return {
        "schema_version": 1,
        "status": "diagnostic_of_record_not_independently_validated",
        "promoted_on": "2026-07-24",
        "ranking_authority": "surface_score_v2.3",
        "study_id": "surface-score-v2-3-general-diagnostic-calibration",
        "implementation_sha256": hashlib.sha256(
            (ROOT / "app/tools/surface_diagnostics.py").read_bytes()
        ).hexdigest(),
        "calibration_script_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "method": {
            "core": (
                "Four-component nonnegative sum-to-one pairwise-logistic "
                "fit on per-cell rankings."
            ),
            "guardrail": (
                "Multiplicative one-sided power penalties below explicit "
                "containment and outward-rise score thresholds."
            ),
            "selection": (
                "Finite preregistered-style grid selected on broad rounds; "
                "lower thresholds and exponents break exact metric ties."
            ),
            "guardrail_formula": (
                "(1-core_fraction)*v2.2 + core_fraction*core"
                "*min(1, containment/threshold)^containment_exponent"
                "*min(1, outward_score/threshold)^outward_exponent"
            ),
            "promotion_constraint": (
                "No population may lose more than 0.005 mean Spearman or "
                "pairwise agreement relative to v2.2."
            ),
        },
        "evidence": {
            "broad": "10 prior rounds spanning v1 score deciles",
            "close": "10 prior rounds containing nearby v1 scores",
            "cell": "25 mouth/coverage cells, 10 high-scoring candidates each",
            "total_ranked_candidates": 450,
            "total_pairwise_preferences": 2025,
        },
        "core_components": list(CORE_COMPONENTS),
        "core_weights": dict(zip(
            CORE_COMPONENTS, core_weights, strict=True
        )),
        "selected_guardrail": selected.as_dict(),
        "baselines": {
            "v1": {
                "broad": _evaluate_fixed(broad, "v1")["summary"],
                "close": _evaluate_fixed(close, "v1")["summary"],
            },
            "v2_2": {
                "broad": baseline_v2_2["broad"]["summary"],
                "close": baseline_v2_2["close"]["summary"],
                "cell": baseline_v2_2["cell"]["summary"],
            },
            "v2_3_core_without_guardrails": {
                "broad": _evaluate_guardrail(
                    broad, core_weights, no_guard
                )["summary"],
                "close": _evaluate_guardrail(
                    close, core_weights, no_guard
                )["summary"],
                "cell_in_sample": _evaluate_guardrail(
                    cells, core_weights, no_guard
                )["summary"],
                "cell_leave_one_out": _cell_leave_one_out(
                    cells, no_guard
                )["summary"],
            },
        },
        "selected_candidate": {
            "broad_in_sample": selected_broad,
            "broad_nested_guardrail_selection": _broad_nested_selection(
                broad, core_weights, grid
            ),
            "close_transfer": selected_close,
            "cell_in_sample": selected_cells,
            "cell_leave_one_out_core_fit": _cell_leave_one_out(
                cells, selected
            ),
            "guardrail_triggers": {
                "broad": _trigger_summary(broad, selected),
                "close": _trigger_summary(close, selected),
                "cell": _trigger_summary(cells, selected),
            },
        },
        "paired_comparison_to_v2_2": {
            "broad": _paired_comparison(
                selected_broad, baseline_v2_2["broad"], seed=2301
            ),
            "close": _paired_comparison(
                selected_close, baseline_v2_2["close"], seed=2302
            ),
            "cell": _paired_comparison(
                selected_cells, baseline_v2_2["cell"], seed=2303
            ),
        },
        "top_grid_candidates": candidate_table,
        "limitations": [
            "The broad rankings previously influenced the v2 beamwidth "
            "component design and are not pristine independent validation.",
            "The per-cell rankings fit the core weights; whole-cell "
            "cross-validation estimates rather than eliminates selection bias.",
            "The ranking games forced total orders without confidence or ties.",
            "The project owner selected this score as diagnostic of record on "
            "2026-07-24 despite the absence of a new blinded mixed-quality set.",
        ],
    }


def _markdown(result: dict[str, Any]) -> str:
    v2_2 = result["baselines"]["v2_2"]
    selected = result["selected_candidate"]
    candidate = {
        "broad": selected["broad_in_sample"]["summary"],
        "close": selected["close_transfer"]["summary"],
        "cell": selected["cell_in_sample"]["summary"],
    }
    labels = {
        "broad": "Broad rounds",
        "close": "Close-score rounds",
        "cell": "Per-cell rankings",
    }
    rows = []
    for population in ("broad", "close", "cell"):
        rows.append(
            f"| {labels[population]} | "
            f"{v2_2[population]['mean_spearman']:.3f} | "
            f"{candidate[population]['mean_spearman']:.3f} | "
            f"{100 * v2_2[population]['mean_pairwise_agreement']:.1f}% | "
            f"{100 * candidate[population]['mean_pairwise_agreement']:.1f}% | "
            f"{v2_2[population]['top_1_matches']} | "
            f"{candidate[population]['top_1_matches']} |"
        )
    weights = result["core_weights"]
    guardrail = result["selected_guardrail"]
    comparisons = result["paired_comparison_to_v2_2"]
    uncertainty = []
    for population in ("broad", "close", "cell"):
        evidence = comparisons[population]["spearman"]
        low, high = evidence["bootstrap_95_percent_interval"]
        uncertainty.append(
            f"| {labels[population]} | "
            f"{evidence['mean_delta']:+.3f} | {low:+.3f} to {high:+.3f} |"
        )
    triggers = selected["guardrail_triggers"]
    trigger_rows = [
        f"| {labels[population]} | "
        f"{triggers[population]['either_trigger_count']} / "
        f"{triggers[population]['candidate_count']} |"
        for population in ("broad", "close", "cell")
    ]
    return f"""# Surface score v2.3 calibration

Status: diagnostic of record since 2026-07-24; calibrated, not independently validated

V2.3 preserves v2.2 as the broad-quality baseline and adds a guarded
local-ranking refinement. It is the authoritative search-ranking score. V1 and
v2.2 remain reproducible historical comparisons.

## Frozen formula

`v2.3 = {1 - guardrail['v2_3_core_fraction']:.2f} * v2.2 + {guardrail['v2_3_core_fraction']:.2f} * guarded_core`

Local-core weights:

| Component | Weight |
| --- | ---: |
| Profile RMS | {100 * weights['profile_rms']:.4f}% |
| Slice-energy stability | {100 * weights['slice_energy']:.4f}% |
| Full-band -6 dB target | {100 * weights['minus_six_line']:.4f}% |
| Three-contour beamwidth | {100 * weights['beamwidth_quality']:.4f}% |

The local branch receives full credit at or above
{guardrail['containment_threshold_percent']:.0f}% mean containment and
{guardrail['outward_rise_score_threshold_percent']:.0f}% outward-rise score.
Below those floors it is multiplied by containment ratio exponent
{guardrail['containment_exponent']:g} and outward-rise ratio exponent
{guardrail['outward_rise_exponent']:g}.

## Ranking evidence

| Population | V2.2 rho | V2.3 rho | V2.2 pairs | V2.3 pairs | V2.2 top | V2.3 top |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

Whole-cell leave-one-out fitting gives v2.3 mean per-cell rho
{selected['cell_leave_one_out_core_fit']['summary']['mean_spearman']:.3f}.
Nested broad-round guardrail selection gives mean broad rho
{selected['broad_nested_guardrail_selection']['summary']['mean_spearman']:.3f}.

## Paired uncertainty

| Population | Mean rho change | Whole-group bootstrap 95% interval |
| --- | ---: | ---: |
{chr(10).join(uncertainty)}

## Guardrail activity

| Population | Candidates triggering either guardrail |
| --- | ---: |
{chr(10).join(trigger_rows)}

## Interpretation

The broad difference is consistent with no change. Close-score and per-cell
ordering improve on the completed evidence. These are calibration results, not
new blinded validation, because the same ranking programs informed component
or parameter selection.

See [`docs/plans/surface_diagnostic_v2_3.md`](../../docs/plans/surface_diagnostic_v2_3.md)
for the design, selection constraints, semantics, and release policy.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prior-root", type=Path, default=DEFAULT_PRIOR_ROOT
    )
    parser.add_argument(
        "--cell-root", type=Path, default=DEFAULT_CELL_ROOT
    )
    args = parser.parse_args()
    result = calibrate(
        args.prior_root.resolve(), args.cell_root.resolve()
    )
    output = args.cell_root / OUTPUT_NAME
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    report = args.cell_root / REPORT_NAME
    report.write_text(_markdown(result))
    print(output)
    print(report)


if __name__ == "__main__":
    main()
