#!/usr/bin/env python3
"""Analyze completed blinded per-cell surface-score rankings."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "examples/surface-score-v2-2-cell-ranking-game"
SCORES = ("score_v1", "score_v2_2")


def _rank_statistics(
    human_order: list[str],
    mapping: dict[str, dict[str, Any]],
    score_key: str,
) -> dict[str, Any]:
    score_order = sorted(
        human_order,
        key=lambda plot_id: (-float(mapping[plot_id][score_key]), plot_id),
    )
    human_rank = {
        plot_id: index for index, plot_id in enumerate(human_order)
    }
    score_rank = {
        plot_id: index for index, plot_id in enumerate(score_order)
    }
    rho = float(spearmanr(
        list(range(len(human_order))),
        [score_rank[plot_id] for plot_id in human_order],
    ).statistic)
    concordant = sum(
        score_rank[human_order[left]] < score_rank[human_order[right]]
        for left in range(len(human_order))
        for right in range(left + 1, len(human_order))
    )
    total = len(human_order) * (len(human_order) - 1) // 2
    return {
        "spearman": rho,
        "pairwise_agreement": concordant / total,
        "top_1_match": score_order[0] == human_order[0],
        "human_winner_score_rank": score_rank[human_order[0]] + 1,
        "top_3_overlap": len(set(score_order[:3]) & set(human_order[:3])),
        "score_winner_human_rank": human_rank[score_order[0]] + 1,
    }


def _score_summary(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any]:
    metrics = [row["scores"][score_key] for row in rows]
    return {
        "cell_count": len(rows),
        "mean_spearman": float(np.mean([
            value["spearman"] for value in metrics
        ])),
        "median_spearman": float(np.median([
            value["spearman"] for value in metrics
        ])),
        "mean_pairwise_agreement": float(np.mean([
            value["pairwise_agreement"] for value in metrics
        ])),
        "top_1_matches": sum(value["top_1_match"] for value in metrics),
        "mean_top_3_overlap": float(np.mean([
            value["top_3_overlap"] for value in metrics
        ])),
        "mean_human_winner_score_rank": float(np.mean([
            value["human_winner_score_rank"] for value in metrics
        ])),
        "mean_human_winner_score": float(np.mean([
            row["human_winner"][score_key] for row in rows
        ])),
        "mean_candidate_score": float(np.mean([
            candidate[score_key]
            for row in rows for candidate in row["candidates"]
        ])),
        "mean_within_cell_score_range": float(np.mean([
            max(candidate[score_key] for candidate in row["candidates"])
            - min(candidate[score_key] for candidate in row["candidates"])
            for row in rows
        ])),
    }


def analyze(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    experiment = json.loads((root / "experiment.json").read_text())
    private = json.loads((root / "private_manifest.json").read_text())
    rankings = json.loads(
        (root / "surface_score_v2_2_cell_rankings.json").read_text()
    )
    if rankings["experiment_content_sha256"] != experiment["content_sha256"]:
        raise ValueError("rankings do not match the experiment")
    if set(rankings["completed_rounds"]) != set(range(1, 26)):
        raise ValueError("all 25 rounds must be complete")
    mapping = private["plots"]
    rows = []
    for round_item in experiment["rounds"]:
        order = rankings["orders"][str(round_item["round"])]
        expected = {plot["plot_id"] for plot in round_item["plots"]}
        if len(order) != 10 or set(order) != expected:
            raise ValueError(f"invalid order for round {round_item['round']}")
        candidates = [
            {
                key: mapping[plot_id][key] for key in (
                    "id",
                    "response_sha256",
                    "report_link",
                    "selected_by",
                    "score_v1",
                    "score_v2_2",
                )
            }
            for plot_id in order
        ]
        rows.append({
            "round": round_item["round"],
            "cell_id": round_item["cell_id"],
            "mouth_mm": round_item["mouth_mm"],
            "coverage_deg": round_item["coverage_deg"],
            "human_order": [
                {
                    "rank": index,
                    "plot_id": plot_id,
                    **candidates[index - 1],
                }
                for index, plot_id in enumerate(order, 1)
            ],
            "human_winner": candidates[0],
            "candidates": candidates,
            "scores": {
                score_key: _rank_statistics(order, mapping, score_key)
                for score_key in SCORES
            },
        })
    coverage = {
        str(value): {
            score_key: _score_summary(
                [row for row in rows if row["coverage_deg"] == value],
                score_key,
            )
            for score_key in SCORES
        }
        for value in (30, 35, 40, 45, 50)
    }
    mouth = {
        str(value): {
            score_key: _score_summary(
                [row for row in rows if row["mouth_mm"] == value],
                score_key,
            )
            for score_key in SCORES
        }
        for value in (250, 300, 350, 400, 450)
    }
    cell_wins = Counter()
    for row in rows:
        v1 = row["scores"]["score_v1"]["spearman"]
        v2 = row["scores"]["score_v2_2"]["spearman"]
        cell_wins["v2.2" if v2 > v1 else "v1" if v1 > v2 else "tie"] += 1
    source_counts = Counter(
        row["human_winner"]["selected_by"] for row in rows
    )
    source_ranks = {
        source: float(np.mean([
            ranked["rank"]
            for row in rows for ranked in row["human_order"]
            if ranked["selected_by"] == source
        ]))
        for source in ("v1", "v2.2")
    }
    return {
        "schema_version": 1,
        "status": "complete",
        "study_id": experiment["experiment_id"],
        "experiment_content_sha256": experiment["content_sha256"],
        "ranking_updated_at": rankings["updated_at"],
        "written_note_count": sum(
            bool(note.strip()) for note in rankings["notes"].values()
        ),
        "qualitative_observation": (
            "Wider coverage was consistently worse-performing and harder "
            "to rank."
        ),
        "overall": {
            score_key: _score_summary(rows, score_key)
            for score_key in SCORES
        },
        "cell_spearman_wins": dict(cell_wins),
        "human_winner_selection_source": dict(source_counts),
        "mean_human_rank_by_selection_source": source_ranks,
        "by_coverage": coverage,
        "by_mouth": mouth,
        "cells": rows,
        "interpretation_limits": [
            "The ten candidates in each cell were enriched for high v1 and "
            "v2.2 scores rather than sampled randomly.",
            "A forced total order cannot record ties or ranking confidence.",
            "Ranking difficulty was reported qualitatively; no timing or "
            "confidence measurement was collected.",
            "These rankings calibrate the diagnostic and are not an "
            "independent validation set.",
        ],
    }


def _percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def render(result: dict[str, Any]) -> str:
    overall = result["overall"]
    coverage_rows = []
    for coverage, values in result["by_coverage"].items():
        coverage_rows.append(
            "<tr>"
            f"<td>{coverage}°</td>"
            f"<td>{values['score_v1']['mean_spearman']:.3f}</td>"
            f"<td>{values['score_v2_2']['mean_spearman']:.3f}</td>"
            f"<td>{_percent(values['score_v1']['mean_pairwise_agreement'])}</td>"
            f"<td>{_percent(values['score_v2_2']['mean_pairwise_agreement'])}</td>"
            f"<td>{values['score_v2_2']['mean_human_winner_score']:.2f}</td>"
            f"<td>{values['score_v2_2']['top_1_matches']} / 5</td></tr>"
        )
    cell_rows = []
    for row in result["cells"]:
        winner = row["human_winner"]
        link = html.escape(winner["report_link"] or "")
        label = html.escape(winner["id"])
        if link:
            label = f"<a href='{link}'>{label}</a>"
        cell_rows.append(
            "<tr>"
            f"<td>{row['mouth_mm']}</td><td>{row['coverage_deg']}°</td>"
            f"<td>{row['scores']['score_v1']['spearman']:.3f}</td>"
            f"<td>{row['scores']['score_v2_2']['spearman']:.3f}</td>"
            f"<td>{row['scores']['score_v1']['human_winner_score_rank']}</td>"
            f"<td>{row['scores']['score_v2_2']['human_winner_score_rank']}</td>"
            f"<td>{label}</td></tr>"
        )
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Surface score v2.2 cell-ranking analysis</title>
<style>:root{{--bg:#0b1015;--p:#121a22;--p2:#17212b;--ink:#edf3f6;--muted:#9eacb6;--line:#2b3945;--accent:#72d9ca}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif}}main{{max-width:1250px;margin:auto;padding:24px}}section{{background:var(--p);border:1px solid var(--line);border-radius:10px;padding:15px;margin:15px 0;overflow:auto}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.card{{background:var(--p2);padding:13px;border-radius:8px}}.card strong{{display:block;color:var(--accent);font-size:1.5rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid var(--line);padding:7px;text-align:center}}th{{background:var(--p2)}}a{{color:#a8f4e9}}.muted{{color:var(--muted)}}@media(max-width:800px){{.cards{{grid-template-columns:1fr}}}}</style>
</head><body><main><h1>Surface score v2.2 cell-ranking analysis</h1>
<p class='muted'>Twenty-five completed cells · ten blinded candidates per
cell · 250 ranked plots.</p>
<section><h2>Outcome</h2><div class='cards'>
<div class='card'><strong>{overall['score_v2_2']['mean_spearman']:.3f}</strong>
V2.2 mean within-cell Spearman</div>
<div class='card'><strong>{overall['score_v1']['mean_spearman']:.3f}</strong>
V1 mean within-cell Spearman</div>
<div class='card'><strong>{result['cell_spearman_wins'].get('v2.2', 0)} / 25</strong>
Cells where v2.2 correlation beats v1</div></div>
<p>V2.2 pairwise agreement is
<strong>{_percent(overall['score_v2_2']['mean_pairwise_agreement'])}</strong>
versus <strong>{_percent(overall['score_v1']['mean_pairwise_agreement'])}</strong>
for v1. V2.2 selected the exact human winner in
{overall['score_v2_2']['top_1_matches']} cells; v1 did so in
{overall['score_v1']['top_1_matches']}.</p></section>
<section><h2>Coverage dependence</h2>
<p class='muted'>The reported ranking difficulty was not timed or scored.
The table tests related measurable effects: diagnostic agreement, perceived
winner quality, and exact winner recovery.</p>
<table><thead><tr><th>Coverage</th><th>V1 ρ</th><th>V2.2 ρ</th>
<th>V1 pairs</th><th>V2.2 pairs</th><th>Human winner mean v2.2 score</th>
<th>V2.2 exact winner</th></tr></thead>
<tbody>{''.join(coverage_rows)}</tbody></table></section>
<section><h2>Cell audit</h2><table><thead><tr><th>Mouth</th><th>Coverage</th>
<th>V1 ρ</th><th>V2.2 ρ</th><th>Human winner rank by v1</th>
<th>Human winner rank by v2.2</th><th>Human winner</th></tr></thead>
<tbody>{''.join(cell_rows)}</tbody></table></section>
<section><h2>Interpretation limits</h2><ul>
{''.join(f"<li>{html.escape(item)}</li>" for item in result['interpretation_limits'])}
</ul></section></main></body></html>"""


def write(root: Path = DEFAULT_ROOT) -> Path:
    result = analyze(root)
    (root / "analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    output = root / "analysis.html"
    output.write_text(render(result))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(write(args.root.resolve()))


if __name__ == "__main__":
    main()
