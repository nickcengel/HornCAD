"""Validate surface-diagnostic v2 against the completed blinded rankings."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.stats import spearmanr

from .interactive_results import load_run
from .surface_diagnostics import (
    BEAMWIDTH_REFERENCE_SCALE,
    SURFACE_SCORE_V2_CANDIDATE_WEIGHTS,
    beamwidth_quality_at_reference_scale,
    surface_diagnostics,
    surface_score_v2,
)


BOOTSTRAP_SEED = 20260723
BOOTSTRAP_SAMPLES = 20_000
BROAD_ROUNDS = tuple(range(1, 11))
CLOSE_ROUNDS = tuple(range(11, 21))
ALL_ROUNDS = BROAD_ROUNDS + CLOSE_ROUNDS
REFERENCE_SCALES = (1.0, 1.5, 2.0, 2.5, 3.0)


def _round_statistics(order: list[str], values: dict[str, float]) -> dict[str, float]:
    measurements = np.asarray([values[plot_id] for plot_id in order], dtype=float)
    rho = float(spearmanr(-np.arange(len(order)), measurements).statistic)
    agreement = 0.0
    pairs = 0
    for left in range(len(order)):
        for right in range(left + 1, len(order)):
            difference = measurements[left] - measurements[right]
            agreement += 1.0 if difference > 0 else 0.5 if difference == 0 else 0.0
            pairs += 1
    return {"spearman": rho, "pairwise_agreement": agreement / pairs}


def _bootstrap_interval(values: list[float], rng: np.random.Generator) -> list[float]:
    samples = rng.choice(
        np.asarray(values), size=(BOOTSTRAP_SAMPLES, len(values)), replace=True
    ).mean(axis=1)
    return [float(value) for value in np.quantile(samples, [0.025, 0.975])]


def _summarize(
    per_round: dict[str, dict[str, dict[str, float]]],
    metric: str,
    rounds: Iterable[int],
    rng: np.random.Generator,
) -> dict[str, Any]:
    selected = [per_round[str(number)][metric] for number in rounds]
    rhos = [row["spearman"] for row in selected]
    agreements = [row["pairwise_agreement"] for row in selected]
    return {
        "mean_spearman": float(np.mean(rhos)),
        "median_spearman": float(np.median(rhos)),
        "spearman_95_percent_interval": _bootstrap_interval(rhos, rng),
        "mean_pairwise_agreement": float(np.mean(agreements)),
        "pairwise_95_percent_interval": _bootstrap_interval(agreements, rng),
    }


def _candidate_selection(
    per_round: dict[str, dict[str, dict[str, float]]],
    training_rounds: set[int],
) -> str:
    broad = sorted(training_rounds.intersection(BROAD_ROUNDS))
    close = sorted(training_rounds.intersection(CLOSE_ROUNDS))

    def mean(metric: str, rounds: list[int], key: str) -> float:
        return float(np.mean([
            per_round[str(number)][metric][key] for number in rounds
        ]))

    v1_broad = mean("v1", broad, "spearman")
    eligible = []
    for candidate in SURFACE_SCORE_V2_CANDIDATE_WEIGHTS:
        if mean(candidate, broad, "spearman") >= v1_broad - 0.05:
            eligible.append(candidate)
    if not eligible:
        eligible = list(SURFACE_SCORE_V2_CANDIDATE_WEIGHTS)
    return max(
        eligible,
        key=lambda candidate: (
            mean(candidate, close, "spearman"),
            mean(candidate, close, "pairwise_agreement"),
            mean(candidate, broad, "spearman"),
            candidate,
        ),
    )


def _reference_scale_selection(
    per_round: dict[str, dict[str, dict[str, float]]],
    training_rounds: set[int],
) -> str:
    broad = sorted(training_rounds.intersection(BROAD_ROUNDS))
    close = sorted(training_rounds.intersection(CLOSE_ROUNDS))
    candidates = [f"contour_forward_scale_{scale:g}" for scale in REFERENCE_SCALES]

    def mean(metric: str, rounds: list[int], key: str) -> float:
        return float(np.mean([
            per_round[str(number)][metric][key] for number in rounds
        ]))

    v1_broad = mean("v1", broad, "spearman")
    eligible = [
        metric for metric in candidates
        if mean(metric, broad, "spearman") >= v1_broad - 0.05
    ]
    return max(
        eligible or candidates,
        key=lambda metric: (
            mean(metric, close, "spearman"),
            mean(metric, close, "pairwise_agreement"),
            mean(metric, broad, "spearman"),
            metric,
        ),
    )


def _load_scores(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = json.loads((root / "rankings.json").read_text())
    if not state.get("complete"):
        raise ValueError("the ranking experiment is not complete")
    private = json.loads((root / "private_manifest.json").read_text())
    plot_scores: dict[str, Any] = {}
    for plot_id, item in sorted(private["plots"].items()):
        run = load_run(Path(item["source_path"]).parent, item["candidate_id"])
        result = surface_diagnostics(run)
        beamwidth = float(np.mean([
            result[plane]["beamwidth_quality"]["overall_percent"]
            for plane in ("horizontal", "vertical")
        ]))
        sensitivity = {}
        for scale in REFERENCE_SCALES:
            variant = {
                **result,
                **{
                    plane: {
                        **result[plane],
                        "beamwidth_quality": beamwidth_quality_at_reference_scale(
                            result[plane]["contours"], scale
                        ),
                    }
                    for plane in ("horizontal", "vertical")
                },
            }
            sensitivity[f"contour_forward_scale_{scale:g}"] = float(
                surface_score_v2(
                    variant,
                    run.get("mouth_dimensions_mm"),
                    candidate_name="contour_forward",
                )["overall_percent"]
            )
        plot_scores[plot_id] = {
            "candidate_id": item["candidate_id"],
            "response_sha256": item["response_sha256"],
            "v1": float(result["score_v1"]["overall_percent"]),
            "beamwidth_quality": beamwidth,
            **{
                name: float(score["overall_percent"])
                for name, score in result["score_v2_candidates"].items()
            },
            **sensitivity,
            "beamwidth_planes": {
                plane: result[plane]["beamwidth_quality"]
                for plane in ("horizontal", "vertical")
            },
        }
    return state, private, plot_scores


def calibrate(root: Path) -> dict[str, Any]:
    state, private, plot_scores = _load_scores(root)
    metrics = [
        "v1",
        "beamwidth_quality",
        *SURFACE_SCORE_V2_CANDIDATE_WEIGHTS,
        *[f"contour_forward_scale_{scale:g}" for scale in REFERENCE_SCALES],
    ]
    values = {
        metric: {
            plot_id: float(scores[metric])
            for plot_id, scores in plot_scores.items()
        }
        for metric in metrics
    }
    per_round = {
        str(round_number): {
            metric: _round_statistics(
                state["orders"][str(round_number)], values[metric]
            )
            for metric in metrics
        }
        for round_number in ALL_ROUNDS
    }
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    summaries = {
        metric: {
            "broad": _summarize(per_round, metric, BROAD_ROUNDS, rng),
            "close": _summarize(per_round, metric, CLOSE_ROUNDS, rng),
            "all": _summarize(per_round, metric, ALL_ROUNDS, rng),
        }
        for metric in metrics
    }
    folds = []
    for held_out in ALL_ROUNDS:
        selected = _candidate_selection(
            per_round, set(ALL_ROUNDS).difference({held_out})
        )
        folds.append({
            "held_out_round": held_out,
            "cohort": "broad" if held_out in BROAD_ROUNDS else "close",
            "selected_candidate": selected,
            **per_round[str(held_out)][selected],
        })
    selection_counts = Counter(fold["selected_candidate"] for fold in folds)
    final_candidate = _candidate_selection(per_round, set(ALL_ROUNDS))
    scale_folds = []
    for held_out in ALL_ROUNDS:
        selected = _reference_scale_selection(
            per_round, set(ALL_ROUNDS).difference({held_out})
        )
        scale_folds.append({
            "held_out_round": held_out,
            "cohort": "broad" if held_out in BROAD_ROUNDS else "close",
            "selected_metric": selected,
            **per_round[str(held_out)][selected],
        })
    scale_selection_counts = Counter(
        fold["selected_metric"] for fold in scale_folds
    )
    selected_scale_metric = _reference_scale_selection(
        per_round, set(ALL_ROUNDS)
    )
    selected_scale = float(selected_scale_metric.rsplit("_", 1)[-1])
    if not np.isclose(selected_scale, BEAMWIDTH_REFERENCE_SCALE):
        raise ValueError(
            "active beamwidth reference scale does not match calibration selection"
        )
    selected_summary = summaries[final_candidate]
    baseline = summaries["v1"]
    criteria = {
        "close_mean_spearman_at_least_0_25": (
            selected_summary["close"]["mean_spearman"] >= 0.25
        ),
        "close_better_than_v1": (
            selected_summary["close"]["mean_spearman"]
            > baseline["close"]["mean_spearman"]
        ),
        "close_pairwise_above_0_60": (
            selected_summary["close"]["mean_pairwise_agreement"] > 0.60
        ),
        "broad_drop_no_more_than_0_05": (
            selected_summary["broad"]["mean_spearman"]
            >= baseline["broad"]["mean_spearman"] - 0.05
        ),
    }
    source_path = Path(__file__).with_name("surface_diagnostics.py")
    return {
        "schema_version": 1,
        "experiment_id": private["experiment_id"],
        "implementation_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "samples": BOOTSTRAP_SAMPLES,
            "unit": "complete ten-plot round",
        },
        "metrics": metrics,
        "candidate_weights": SURFACE_SCORE_V2_CANDIDATE_WEIGHTS,
        "summaries": summaries,
        "per_round": per_round,
        "leave_one_round_out": {
            "folds": folds,
            "selection_counts": dict(sorted(selection_counts.items())),
        },
        "reference_sensitivity": {
            "scales": REFERENCE_SCALES,
            "selected_scale": selected_scale,
            "selected_metric": selected_scale_metric,
            "folds": scale_folds,
            "selection_counts": dict(sorted(scale_selection_counts.items())),
        },
        "release_decision": {
            "selected_candidate": final_candidate,
            "criteria": criteria,
            "passes_promotion_criteria": all(criteria.values()),
            "promote_v2": False,
            "activation_status": "not-activated; v1 remains primary",
        },
        "plot_scores": plot_scores,
        "notes": state.get("notes", {}),
    }


def _percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def write_report(root: Path, result: dict[str, Any]) -> Path:
    labels = {
        "v1": "Surface score v1",
        "beamwidth_quality": "Beamwidth quality alone",
        "conservative": "V2 conservative",
        "balanced": "V2 balanced",
        "smoothness": "V2 smoothness",
        "contour_forward": "V2 contour-forward",
    }
    labels.update({
        f"contour_forward_scale_{scale:g}": (
            f"V2 contour-forward · reference scale {scale:g}×"
        )
        for scale in REFERENCE_SCALES
    })
    summary_rows = []
    for metric in result["metrics"]:
        summary = result["summaries"][metric]
        summary_rows.append(
            f"<tr><th>{html.escape(labels[metric])}</th>"
            f"<td>{summary['broad']['mean_spearman']:+.3f}</td>"
            f"<td>{_percent(summary['broad']['mean_pairwise_agreement'])}</td>"
            f"<td>{summary['close']['mean_spearman']:+.3f}</td>"
            f"<td>{_percent(summary['close']['mean_pairwise_agreement'])}</td>"
            f"<td>{summary['all']['mean_spearman']:+.3f}</td>"
            f"<td>{_percent(summary['all']['mean_pairwise_agreement'])}</td></tr>"
        )
    round_rows = []
    chosen = result["release_decision"]["selected_candidate"]
    for number in ALL_ROUNDS:
        row = result["per_round"][str(number)]
        round_rows.append(
            f"<tr><th>{number}</th><td>{'Broad' if number <= 10 else 'Close'}</td>"
            f"<td>{row['v1']['spearman']:+.3f}</td>"
            f"<td>{row[chosen]['spearman']:+.3f}</td>"
            f"<td>{_percent(row['v1']['pairwise_agreement'])}</td>"
            f"<td>{_percent(row[chosen]['pairwise_agreement'])}</td></tr>"
        )
    criteria_rows = "".join(
        f"<tr><th>{html.escape(name.replace('_', ' '))}</th>"
        f"<td class='{'pass' if passed else 'fail'}'>{'PASS' if passed else 'FAIL'}</td></tr>"
        for name, passed in result["release_decision"]["criteria"].items()
    )
    notes = []
    for plot_id, note in result["notes"].items():
        candidate = result["plot_scores"][plot_id]["candidate_id"]
        notes.append(
            f"<tr><th>{html.escape(plot_id)}</th><td>{html.escape(candidate)}</td>"
            f"<td>{html.escape(note)}</td></tr>"
        )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Surface diagnostic v2 calibration</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#cbd5e1;--paper:#f8fafc;--good:#047857;--bad:#b91c1c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.45 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:32px}}
section{{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin:20px 0;
overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 10px;
border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}.pass{{color:var(--good);
font-weight:700}}.fail{{color:var(--bad);font-weight:700}}code{{font-size:.92em}}
</style></head><body><main><h1>Surface diagnostic v2 calibration</h1>
<p>Completed 20-round blinded ranking experiment; ten broad-range and ten
close-score rounds. Confidence intervals resample complete rounds.</p>
<section><h2>Validation outcome</h2><p>Selected preregistered candidate:
<strong>{html.escape(chosen)}</strong>. The candidate
<strong>{'passes' if result['release_decision']['passes_promotion_criteria'] else 'does not pass'}</strong>
the registered comparison criteria. Activation status:
<strong>NOT ACTIVATED — V1 REMAINS PRIMARY</strong>.</p>
<table>{criteria_rows}</table></section>
<section><h2>Agreement summary</h2><table><thead><tr><th>Metric</th>
<th>Broad ρ</th><th>Broad pairs</th><th>Close ρ</th><th>Close pairs</th>
<th>All ρ</th><th>All pairs</th></tr></thead><tbody>{''.join(summary_rows)}</tbody></table></section>
<section><h2>Per-round v1 versus selected v2</h2><table><thead><tr><th>Round</th>
<th>Type</th><th>V1 ρ</th><th>V2 ρ</th><th>V1 pairs</th><th>V2 pairs</th>
</tr></thead><tbody>{''.join(round_rows)}</tbody></table></section>
<section><h2>Leave-one-round-out selection</h2><p>Candidate selections:
<code>{html.escape(json.dumps(result['leave_one_round_out']['selection_counts'], sort_keys=True))}</code>.
Each held-out round was evaluated with the candidate selected using the other
19 rounds.</p><p>Reference-scale selections:
<code>{html.escape(json.dumps(result['reference_sensitivity']['selection_counts'], sort_keys=True))}</code>.
The selected experimental scale is <strong>{result['reference_sensitivity']['selected_scale']:g}×</strong>.</p></section>
<section><h2>Written qualitative checks</h2><table><thead><tr><th>Plot</th>
<th>Candidate</th><th>Note</th></tr></thead><tbody>{''.join(notes)}</tbody></table></section>
<p>Implementation SHA-256: <code>{result['implementation_sha256']}</code></p>
</main></body></html>"""
    path = root / "surface_diagnostic_v2_calibration.html"
    path.write_text(document)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment",
        type=Path,
        nargs="?",
        default=Path("examples/surface-diagnostic-ranking-experiment"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = calibrate(args.experiment)
    json_path = args.experiment / "surface_diagnostic_v2_calibration.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(write_report(args.experiment, result))


if __name__ == "__main__":
    main()
