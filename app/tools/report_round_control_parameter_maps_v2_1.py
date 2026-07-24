#!/usr/bin/env python3
"""Build measured round-control parameter maps ranked by surface score v2.1."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any, Callable

from .calibrate_surface_score_v2_pairwise import _revised_score
from .generate_surface_score_rank_comparison import _evaluation_grid
from .interactive_results import load_run
from .report_round_control_parameter_maps import COVERAGES, MOUTHS, _color
from .surface_diagnostics import surface_diagnostics


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = (
    ROOT / "examples/surface-score-v1-v2-rank-comparison/comparison.json"
)
DEFAULT_RIDGE_RESULTS = ROOT / "examples/round-control-ridge-closure/results.json"
DEFAULT_OUTPUT = ROOT / "examples/round-control-parameter-maps-v2-1"
PARAMETERS = (
    ("length_mm", "Length", "mm", 1),
    ("k", "K", "", 2),
    ("n", "N", "", 2),
    ("s", "S", "", 3),
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _winner(
    candidates: list[dict[str, Any]], score_key: str
) -> dict[str, Any]:
    return min(
        candidates,
        key=lambda row: (-float(row[score_key]), row["id"]),
    )


def _ridge_candidates(
    ridge_results_path: Path,
    output: Path,
) -> list[dict[str, Any]]:
    ridge = json.loads(ridge_results_path.read_text(encoding="utf-8"))
    candidates = []
    for row in ridge["evidence"]:
        response = ROOT / row["response_path"]
        run = load_run(response.parent)
        diagnostics = surface_diagnostics(
            run, _evaluation_grid(run), fixed_band=True
        )
        if diagnostics["status"] != "available":
            raise ValueError(f"{row['id']}: surface diagnostics unavailable")
        reports = sorted(response.parent.glob("*_Report.html"))
        report_link = (
            Path(os.path.relpath(reports[0], output)).as_posix()
            if reports else None
        )
        candidates.append({
            "id": row["id"],
            "response_sha256": row["response_sha256"],
            "report_link": report_link,
            "source_path": row["response_path"],
            "coverage_deg": float(row["coverage_deg"]),
            "mouth_mm": float(row["mouth_mm"]),
            "length_mm": float(row["length_mm"]),
            "k": float(row["k"]),
            "n": float(row["n"]),
            "s": float(row["derived_s"]),
            "score_v1": float(
                diagnostics["score_v1"]["overall_percent"]
            ),
            "score_v2_1": float(
                diagnostics["score_v2_candidates"]["contour_forward"][
                    "overall_percent"
                ]
            ),
        })
    return candidates


def assemble(
    source_path: Path = DEFAULT_SOURCE,
    ridge_results_path: Path = DEFAULT_RIDGE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    candidates_by_hash = {
        row["response_sha256"]: {**row, "score_v2_1": _revised_score(row)}
        for row in source["candidates"]
    }
    for row in _ridge_candidates(ridge_results_path, output):
        candidates_by_hash[row["response_sha256"]] = row
    population = sorted(candidates_by_hash.values(), key=lambda row: row["id"])
    cells: dict[str, Any] = {}
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
            v2_1 = _winner(candidates, "score_v2_1")
            deltas = {
                key: float(v2_1[key]) - float(v1[key])
                for key, *_ in PARAMETERS
            }
            deltas["score"] = (
                float(v2_1["score_v2_1"]) - float(v1["score_v2_1"])
            )
            cell_id = f"{coverage}deg-{mouth}mm"
            cells[cell_id] = {
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "evidence_count": len(candidates),
                "v1_winner": {
                    key: v1[key] for key in (
                        "id", "response_sha256", "report_link", "source_path",
                        "length_mm", "k", "n", "s", "score_v1", "score_v2_1",
                    )
                },
                "v2_1_winner": {
                    key: v2_1[key] for key in (
                        "id", "response_sha256", "report_link", "source_path",
                        "length_mm", "k", "n", "s", "score_v1", "score_v2_1",
                    )
                },
                "v2_1_minus_v1_winner": deltas,
                "winner_changed": (
                    v1["response_sha256"] != v2_1["response_sha256"]
                ),
            }
    artifact = {
        "schema_version": 1,
        "study_id": "round-control-parameter-maps-v2-1",
        "status": "complete",
        "score_version": "v2.1",
        "selection_rule": (
            "maximum measured surface score v2.1 per mouth/coverage cell; "
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
        ],
        "population_count": len(population),
        "cells": cells,
    }
    artifact["content_sha256"] = _content_hash(artifact)
    return artifact


def _format(value: float, digits: int, suffix: str = "") -> str:
    return f"{value:.{digits}f}{suffix}"


def _signed(value: float, digits: int, suffix: str = "") -> str:
    threshold = 0.5 * 10 ** -digits
    if abs(value) < threshold:
        value = 0.0
    return f"{value:+.{digits}f}{suffix}"


def _map(
    cells: dict[str, Any],
    *,
    title: str,
    description: str,
    value_for: Callable[[dict[str, Any]], float],
    label_for: Callable[[dict[str, Any]], str],
    link: bool = False,
) -> str:
    values = [
        value_for(cells[f"{coverage}deg-{mouth}mm"])
        for mouth in MOUTHS for coverage in COVERAGES
    ]
    minimum, maximum = min(values), max(values)
    rows = []
    for mouth in MOUTHS:
        columns = []
        for coverage in COVERAGES:
            cell = cells[f"{coverage}deg-{mouth}mm"]
            winner = cell["v2_1_winner"]
            label = html.escape(label_for(cell))
            if link and winner.get("report_link"):
                label = (
                    f"<a href='{html.escape(winner['report_link'])}'>"
                    f"{label}</a>"
                )
            columns.append(
                f"<td class='map-cell' "
                f"style='background:{_color(value_for(cell), minimum, maximum)}' "
                f"title='{html.escape(winner['id'])} · "
                f"v2.1 {winner['score_v2_1']:.2f} · "
                f"{cell['evidence_count']} measured responses'>"
                f"<strong>{label}</strong></td>"
            )
        rows.append(f"<tr><th>{mouth} mm</th>{''.join(columns)}</tr>")
    return (
        "<article class='map-card'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(description)}</p>"
        "<table class='heatmap'><thead><tr>"
        "<th>Mouth ↓<br>Coverage →</th>"
        + "".join(f"<th>{coverage}°</th>" for coverage in COVERAGES)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><div class='scale'>"
        f"<span>{minimum:.3g}</span><i></i><span>{maximum:.3g}</span>"
        "</div></article>"
    )


def render(artifact: dict[str, Any]) -> str:
    cells = artifact["cells"]
    changed = sum(cell["winner_changed"] for cell in cells.values())
    absolute_maps = "".join(
        _map(
            cells,
            title=title,
            description=f"Measured v2.1 winner {title.lower()}.",
            value_for=lambda cell, key=key: float(
                cell["v2_1_winner"][key]
            ),
            label_for=lambda cell, key=key, digits=digits, suffix=suffix:
                _format(float(cell["v2_1_winner"][key]), digits, suffix),
        )
        for key, title, suffix, digits in PARAMETERS
    )
    score_map = _map(
        cells,
        title="Surface score v2.1",
        description=(
            "Measured winning score. Values link to the retained candidate "
            "report where available."
        ),
        value_for=lambda cell: float(cell["v2_1_winner"]["score_v2_1"]),
        label_for=lambda cell: (
            f"{float(cell['v2_1_winner']['score_v2_1']):.2f}%"
        ),
        link=True,
    )
    delta_maps = "".join(
        _map(
            cells,
            title=f"Δ {title}",
            description=(
                f"V2.1 winner {title.lower()} minus v1 winner "
                f"{title.lower()} in the same cell."
            ),
            value_for=lambda cell, key=key: float(
                cell["v2_1_minus_v1_winner"][key]
            ),
            label_for=lambda cell, key=key, digits=digits, suffix=suffix:
                _signed(
                    float(cell["v2_1_minus_v1_winner"][key]),
                    digits,
                    suffix,
                ),
        )
        for key, title, suffix, digits in PARAMETERS
    )
    detail_rows = []
    for mouth in MOUTHS:
        for coverage in COVERAGES:
            cell = cells[f"{coverage}deg-{mouth}mm"]
            old = cell["v1_winner"]
            new = cell["v2_1_winner"]
            deltas = cell["v2_1_minus_v1_winner"]
            link = html.escape(new["report_link"] or "")
            new_id = html.escape(new["id"])
            new_label = f"<a href='{link}'>{new_id}</a>" if link else new_id
            detail_rows.append(
                "<tr>"
                f"<td>{mouth}</td><td>{coverage}°</td>"
                f"<td>{'yes' if cell['winner_changed'] else 'no'}</td>"
                f"<td>{html.escape(old['id'])}</td><td>{new_label}</td>"
                f"<td>{old['score_v1']:.2f}</td>"
                f"<td>{new['score_v2_1']:.2f}</td>"
                f"<td>{_signed(deltas['length_mm'], 1)}</td>"
                f"<td>{_signed(deltas['k'], 2)}</td>"
                f"<td>{_signed(deltas['n'], 2)}</td>"
                f"<td>{_signed(deltas['s'], 3)}</td>"
                f"<td>{cell['evidence_count']}</td></tr>"
            )
    source_rows = "".join(
        f"{html.escape(source['path'])}: "
        f"<code>{html.escape(source['sha256'])}</code><br>"
        for source in artifact["sources"]
    )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Round-control parameter maps · surface score v2.1</title>
<style>
:root{{--bg:#0b1015;--panel:#121a22;--panel2:#17212b;--ink:#edf3f6;--muted:#9eacb6;--line:#2b3945;--accent:#72d9ca}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:24px}}h1,h2{{margin:0 0 8px}}p{{line-height:1.45}}a{{color:#a8f4e9}}.muted,.map-card p{{color:var(--muted)}}section,.map-card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0;overflow-x:auto}}.map-grid{{display:grid;grid-template-columns:repeat(2,minmax(500px,1fr));gap:16px}}.map-card{{margin:0}}table{{border-collapse:collapse;width:100%;table-layout:fixed}}th,td{{border:1px solid rgba(255,255,255,.12);text-align:center;padding:10px 6px}}th{{background:var(--panel2)}}th:first-child{{width:105px}}.map-cell{{height:74px}}.map-cell strong{{display:block;font-size:1.15rem;text-shadow:0 1px 3px #000}}.map-cell a{{color:white}}.scale{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;margin-top:9px;color:var(--muted);font-size:.82rem}}.scale i{{height:9px;border-radius:99px;background:linear-gradient(90deg,hsl(220 62% 24%),hsl(131 62% 30.5%),hsl(42 62% 37%))}}.details{{font-size:.78rem;table-layout:auto}}.details td:nth-child(4),.details td:nth-child(5){{text-align:left;max-width:300px;overflow-wrap:anywhere}}code{{overflow-wrap:anywhere}}@media(max-width:1100px){{.map-grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Measured high-scoring round-control parameter maps · v2.1</h1>
<p class='muted'>Each cell selects the highest measured surface score v2.1
from the exact-response-deduplicated retained evidence. These are observations,
not surrogate predictions or proven optima. Hover cells for the winner ID,
score, and evidence count.</p>
<p class='muted'>This grid begins at 30°. V2.1’s narrow-coverage correction
ends at 30°, so the correction itself does not alter these scores; selection
here reflects the contour-forward v2 terms now retained by v2.1.</p>
<section><h2>Winner change summary</h2>
<p><strong>{changed} of 25 cells</strong> select a different measured response
than the maximum-v1 candidate in the same retained population.</p>
<p class='muted'>All delta panels are <strong>v2.1 winner parameter minus v1
winner parameter</strong>. A zero means either the winner is unchanged or the
two different winners share that parameter value.</p></section>
<section><h2>V2.1 winner maps</h2><div class='map-grid'>
{score_map}{absolute_maps}</div></section>
<section><h2>Per-cell parameter deltas: v2.1 − v1</h2>
<div class='map-grid'>{delta_maps}</div></section>
<section><h2>Cell-by-cell audit</h2>
<table class='details'><thead><tr><th>Mouth</th><th>Coverage</th>
<th>Changed</th><th>V1 winner</th><th>V2.1 winner</th>
<th>V1 score</th><th>V2.1 score</th><th>Δ L mm</th><th>Δ K</th>
<th>Δ N</th><th>Δ S</th><th>Evidence</th></tr></thead>
<tbody>{''.join(detail_rows)}</tbody></table></section>
<section><h2>Provenance</h2>
<p class='muted'>Population: {artifact['population_count']} retained,
exact-response-deduplicated responses.<br>
{source_rows}
Winner artifact hash: <code>{html.escape(artifact['content_sha256'])}</code>
</p></section>
</main></body></html>"""


def write(
    source: Path = DEFAULT_SOURCE,
    ridge_results: Path = DEFAULT_RIDGE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
) -> Path:
    artifact = assemble(source, ridge_results, output)
    output.mkdir(parents=True, exist_ok=True)
    winners_path = output / "winners.json"
    winners_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "index.html").write_text(render(artifact), encoding="utf-8")
    return output / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--ridge-results", type=Path, default=DEFAULT_RIDGE_RESULTS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(write(
        args.source.resolve(),
        args.ridge_results.resolve(),
        args.output.resolve(),
    ))


if __name__ == "__main__":
    main()
