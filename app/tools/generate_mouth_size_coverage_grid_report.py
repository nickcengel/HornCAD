#!/usr/bin/env python3
"""Generate an overview report for the mouth-size/coverage survey grid."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from statistics import fmean
from typing import Any

import yaml


DIAGNOSTIC_KEYS = (
    "coverage_match_percent",
    "coverage_smoothness_percent",
    "waist_stability_percent",
    "window_uniformity_percent",
)


def _candidate_score(candidate: dict[str, Any]) -> float | None:
    diagnostics = candidate.get("diagnostics", {})
    combined = diagnostics.get("combined", {})
    if not isinstance(combined, dict):
        return None
    values = []
    for key in DIAGNOSTIC_KEYS:
        value = combined.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return fmean(values) if values else None


def _search_summary(path: Path) -> dict[str, Any]:
    coverage_dir = path.parent.parent.name
    mouth_dir = path.parent.name
    coverage = float(coverage_dir.removesuffix("deg"))
    mouth = float(mouth_dir.split("x", 1)[0])
    config = yaml.safe_load(path.read_text(encoding="utf-8"))["bem_candidate_search"]
    state_path = path.parent / "search_state.json"
    report_path = path.parent / "search_report.html"
    finalist_path = path.parent / "finalist_comparison.html"
    summary: dict[str, Any] = {
        "coverage": coverage,
        "mouth": mouth,
        "label": f"{coverage:g} deg / {mouth:g} mm",
        "folder": path.parent,
        "search_yaml": path,
        "config": config,
        "state_path": state_path,
        "report_path": report_path if report_path.is_file() else None,
        "finalist_path": finalist_path if finalist_path.is_file() else None,
        "status": "not started",
        "phase": "",
        "counts": {},
        "completed": 0,
        "failed": 0,
        "running": 0,
        "rejected": 0,
        "proposal_count": 0,
        "average_score": None,
        "best_score": None,
        "best_candidate": None,
        "candidates": [],
    }
    if not state_path.is_file():
        return summary
    state = json.loads(state_path.read_text())
    summary["status"] = str(state.get("status", "unknown"))
    summary["phase"] = str(state.get("phase", ""))
    summary["proposal_count"] = int(state.get("proposal_count", 0))
    summary["rejected"] = int(state.get("rejected_count", 0))
    counts: dict[str, int] = {}
    scored_candidates = []
    for candidate in state.get("candidates", []):
        status = str(candidate.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status != "complete":
            continue
        score = _candidate_score(candidate)
        if score is None:
            continue
        scored_candidates.append((score, candidate))
    summary["counts"] = counts
    summary["completed"] = counts.get("complete", 0)
    summary["failed"] = counts.get("failed", 0)
    summary["running"] = counts.get("running", 0)
    summary["average_score"] = (
        fmean(score for score, _ in scored_candidates) if scored_candidates else None
    )
    if scored_candidates:
        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        summary["best_score"] = scored_candidates[0][0]
        summary["best_candidate"] = scored_candidates[0][1]
    summary["candidates"] = scored_candidates
    return summary


def _format_score(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _best_worst_indices(items: list[dict[str, Any]], key: str) -> tuple[int | None, int | None]:
    values = [(index, item[key]) for index, item in enumerate(items) if item[key] is not None]
    if not values:
        return None, None
    best_index = max(values, key=lambda item: item[1])[0]
    worst_index = min(values, key=lambda item: item[1])[0]
    return best_index, worst_index


def _ranking_class(summary: dict[str, Any]) -> str:
    if summary["status"] == "complete":
        return "complete"
    if summary["status"] == "running":
        return "running"
    if summary["status"] == "failed":
        return "failed"
    return "pending"


def generate_report(project_root: Path, output: Path) -> Path:
    search_paths = sorted(project_root.glob("*deg/*x*/search.yaml"))
    summaries = [_search_summary(path) for path in search_paths]
    summaries.sort(
        key=lambda item: (
            item["average_score"] is None,
            -(item["average_score"] or 0.0),
            item["coverage"],
            item["mouth"],
        )
    )
    total = len(summaries)
    started = sum(summary["status"] != "not started" for summary in summaries)
    running = sum(summary["status"] == "running" for summary in summaries)
    complete = sum(summary["status"] == "complete" for summary in summaries)
    completed_candidates = sum(summary["completed"] for summary in summaries)
    candidate_rows = []
    for summary in summaries:
        for candidate_score, candidate in summary["candidates"]:
            diagnostics = candidate["diagnostics"]["combined"]
            candidate_rows.append({
                "search": summary,
                "candidate": candidate,
                "candidate_score": candidate_score,
                "diagnostics": diagnostics,
                "coverage_match_percent": diagnostics.get("coverage_match_percent"),
                "coverage_smoothness_percent": diagnostics.get("coverage_smoothness_percent"),
                "waist_stability_percent": diagnostics.get("waist_stability_percent"),
                "window_uniformity_percent": diagnostics.get("window_uniformity_percent"),
            })
    candidate_rows.sort(
        key=lambda item: (
            -item["candidate_score"],
            item["search"]["coverage"],
            item["search"]["mouth"],
            item["candidate"]["id"],
        )
    )
    for row in candidate_rows:
        candidate = row["candidate"]
        candidate_dir = row["search"]["folder"] / candidate["id"]
        row["project_yaml"] = candidate_dir / "project.yaml"
        row["stl_path"] = candidate_dir / candidate.get("stl_file", "")
        row["report_path"] = next(candidate_dir.glob("**/interactive_report.html"), None)
        row["label"] = candidate.get("proposal_source", "").replace("_", " ").strip().title() or "Candidate"
        if row["label"] == "Seed":
            row["label"] = "Seed design"

    extrema = {
        "candidate_score": _best_worst_indices(candidate_rows, "candidate_score"),
        "coverage_match_percent": _best_worst_indices(
            candidate_rows, "coverage_match_percent"
        ),
        "coverage_smoothness_percent": _best_worst_indices(
            candidate_rows, "coverage_smoothness_percent"
        ),
        "waist_stability_percent": _best_worst_indices(
            candidate_rows, "waist_stability_percent"
        ),
        "window_uniformity_percent": _best_worst_indices(
            candidate_rows, "window_uniformity_percent"
        ),
    }
    best = next((s for s in summaries if s["average_score"] is not None), None)
    refresh = "<meta http-equiv='refresh' content='30'>" if running else ""
    rows = []
    for rank, item in enumerate(candidate_rows, 1):
        summary = item["search"]
        candidate = item["candidate"]
        diagnostics = item["diagnostics"]
        best_score_index, worst_score_index = extrema["candidate_score"]
        match_best, match_worst = extrema["coverage_match_percent"]
        smooth_best, smooth_worst = extrema["coverage_smoothness_percent"]
        waist_best, waist_worst = extrema["waist_stability_percent"]
        uniform_best, uniform_worst = extrema["window_uniformity_percent"]
        score_class = "best" if best_score_index == rank - 1 else "worst" if worst_score_index == rank - 1 else ""
        match_class = "best" if match_best == rank - 1 else "worst" if match_worst == rank - 1 else ""
        smooth_class = "best" if smooth_best == rank - 1 else "worst" if smooth_worst == rank - 1 else ""
        waist_class = "best" if waist_best == rank - 1 else "worst" if waist_worst == rank - 1 else ""
        uniform_class = "best" if uniform_best == rank - 1 else "worst" if uniform_worst == rank - 1 else ""
        candidate_name = html.escape(candidate["id"])
        candidate_links = []
        if summary["report_path"] is not None:
            candidate_links.append(
                f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>{candidate_name}</a>"
            )
        else:
            candidate_links.append(candidate_name)
        if item["stl_path"].is_file():
            candidate_links.append(
                f"<a href='{html.escape(str(item['stl_path'].relative_to(project_root)))}'>STL</a>"
            )
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(candidate.get('status', 'unknown'))}</span>"
        rows.append(
            "<tr>"
            f"<td data-sort='{rank}'>{rank}</td>"
            f"<td data-sort='{html.escape(candidate['id'])}'>{' · '.join(candidate_links)}</td>"
            f"<td data-sort='{html.escape(summary['label'])}'>{html.escape(summary['label'])}</td>"
            f"<td data-sort='{html.escape(candidate.get('status', 'unknown'))}'>{status_badge}</td>"
            f"<td class='{score_class}' data-sort='{item['candidate_score']:.6f}'>{item['candidate_score']:.1f}%</td>"
            f"<td class='{match_class}' data-sort='{diagnostics['coverage_match_percent']:.6f}'>{diagnostics['coverage_match_percent']:.1f}%</td>"
            f"<td class='{smooth_class}' data-sort='{diagnostics['coverage_smoothness_percent']:.6f}'>{diagnostics['coverage_smoothness_percent']:.1f}%</td>"
            f"<td class='{waist_class}' data-sort='{diagnostics['waist_stability_percent']:.6f}'>{diagnostics['waist_stability_percent']:.1f}%</td>"
            f"<td class='{uniform_class}' data-sort='{diagnostics['window_uniformity_percent']:.6f}'>{diagnostics['window_uniformity_percent']:.1f}%</td>"
            f"<td data-sort='{candidate.get('crossover_minimum_normalized_impedance', 0):.6f}'>{candidate.get('crossover_minimum_normalized_impedance', 0):.3f}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('length_mm', 0):.6f}'>{candidate.get('values', {}).get('length_mm', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('extension_mm', 0):.6f}'>{candidate.get('values', {}).get('extension_mm', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('osse_coverage_h_deg', 0):.6f}'>{candidate.get('values', {}).get('osse_coverage_h_deg', 0):g} / {candidate.get('values', {}).get('osse_coverage_v_deg', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('k_h', 0):.6f}'>{candidate.get('values', {}).get('k_h', 0):.2f} / {candidate.get('values', {}).get('k_v', 0):.2f}</td>"
            f"<td data-sort='{candidate.get('derived', {}).get('s_h', 0):.6f}'>{candidate.get('derived', {}).get('s_h', 0):.3f} / {candidate.get('derived', {}).get('s_v', 0):.3f}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('n_h', 0):.6f}'>{candidate.get('values', {}).get('n_h', 0):g} / {candidate.get('values', {}).get('n_v', 0):g}</td>"
            f"<td data-sort='{candidate.get('derived', {}).get('mouth_curvature_radius_h_mm', 0):.6f}'>{candidate.get('derived', {}).get('mouth_curvature_radius_h_mm', 0):.1f} / {candidate.get('derived', {}).get('mouth_curvature_radius_v_mm', 0):.1f}</td>"
            f"<td data-sort='{html.escape(item['label'])}'>{html.escape(item['label'])}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )

    all_result_rows = []
    all_result_order = sorted(
        candidate_rows,
        key=lambda item: (
            item["search"]["coverage"],
            item["search"]["mouth"],
            item["candidate"]["id"],
        ),
    )
    for rank, item in enumerate(all_result_order, 1):
        summary = item["search"]
        candidate = item["candidate"]
        diagnostics = item["diagnostics"]
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(candidate.get('status', 'unknown'))}</span>"
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        candidate_name = html.escape(candidate["id"])
        candidate_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>{candidate_name}</a>"
            if summary["report_path"] is not None else candidate_name
        )
        all_result_rows.append(
            "<tr>"
            f"<td data-sort='{rank}'>{rank}</td>"
            f"<td data-sort='{html.escape(candidate['id'])}'>{candidate_link}</td>"
            f"<td data-sort='{html.escape(summary['label'])}'>{html.escape(summary['label'])}</td>"
            f"<td data-sort='{html.escape(candidate.get('status', 'unknown'))}'>{status_badge}</td>"
            f"<td data-sort='{item['candidate_score']:.6f}'>{item['candidate_score']:.1f}%</td>"
            f"<td data-sort='{diagnostics['coverage_match_percent']:.6f}'>{diagnostics['coverage_match_percent']:.1f}%</td>"
            f"<td data-sort='{diagnostics['coverage_smoothness_percent']:.6f}'>{diagnostics['coverage_smoothness_percent']:.1f}%</td>"
            f"<td data-sort='{diagnostics['waist_stability_percent']:.6f}'>{diagnostics['waist_stability_percent']:.1f}%</td>"
            f"<td data-sort='{diagnostics['window_uniformity_percent']:.6f}'>{diagnostics['window_uniformity_percent']:.1f}%</td>"
            f"<td data-sort='{candidate.get('crossover_minimum_normalized_impedance', 0):.6f}'>{candidate.get('crossover_minimum_normalized_impedance', 0):.3f}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('length_mm', 0):.6f}'>{candidate.get('values', {}).get('length_mm', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('extension_mm', 0):.6f}'>{candidate.get('values', {}).get('extension_mm', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('osse_coverage_h_deg', 0):.6f}'>{candidate.get('values', {}).get('osse_coverage_h_deg', 0):g} / {candidate.get('values', {}).get('osse_coverage_v_deg', 0):g}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('k_h', 0):.6f}'>{candidate.get('values', {}).get('k_h', 0):.2f} / {candidate.get('values', {}).get('k_v', 0):.2f}</td>"
            f"<td data-sort='{candidate.get('derived', {}).get('s_h', 0):.6f}'>{candidate.get('derived', {}).get('s_h', 0):.3f} / {candidate.get('derived', {}).get('s_v', 0):.3f}</td>"
            f"<td data-sort='{candidate.get('values', {}).get('n_h', 0):.6f}'>{candidate.get('values', {}).get('n_h', 0):g} / {candidate.get('values', {}).get('n_v', 0):g}</td>"
            f"<td data-sort='{candidate.get('derived', {}).get('mouth_curvature_radius_h_mm', 0):.6f}'>{candidate.get('derived', {}).get('mouth_curvature_radius_h_mm', 0):.1f} / {candidate.get('derived', {}).get('mouth_curvature_radius_v_mm', 0):.1f}</td>"
            f"<td data-sort='{html.escape(item['label'])}'>{html.escape(item['label'])}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )

    summary_rows = []
    for rank, summary in enumerate(summaries, 1):
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        finalist_link = (
            f" | <a href='{html.escape(str(summary['finalist_path'].relative_to(project_root)))}'>finalist comparison</a>"
            if summary["finalist_path"] else ""
        )
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(summary['status'])}</span>"
        best_candidate = summary["best_candidate"]
        best_candidate_label = "—"
        if best_candidate is not None:
            best_candidate_label = (
                f"{html.escape(best_candidate['id'])} "
                f"({best_candidate.get('values', {}).get('length_mm', 0):g} mm, "
                f"N {best_candidate.get('values', {}).get('n_h', 0):g})"
            )
        summary_rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{html.escape(summary['label'])}</td>"
            f"<td>{status_badge}</td>"
            f"<td>{summary['completed']} / {summary['proposal_count']}</td>"
            f"<td>{_format_score(summary['average_score'])}</td>"
            f"<td>{_format_score(summary['best_score'])}</td>"
            f"<td>{best_candidate_label}</td>"
            f"<td>{report_link}{finalist_link}</td>"
            "</tr>"
        )

    project_configs = [summary["config"] for summary in summaries if summary["config"]]
    if project_configs:
        first = project_configs[0]
        coverage_targets = ", ".join(f"{summary['coverage']:g}" for summary in summaries)
        mouth_sizes = ", ".join(f"{summary['mouth']:g}" for summary in summaries)
        ratios = sorted({
            round(
                float(candidate["values"]["length_mm"]) / float(summary["mouth"]),
                3
            )
            for summary in summaries
            for _, candidate in summary["candidates"]
        })
        fixed_k = f"{first.get('bounds', {}).get('k_h', [0, 0])[0]:g}"
        fixed_n = f"{first.get('bounds', {}).get('n_h', [0, 0])[0]:g}"
        sweep_lower = f"{first.get('lower_frequency_hz', 0):g}"
        sweep_upper = f"{first.get('upper_frequency_hz', 0):g}"
        crossover = f"{first.get('crossover_hz', 0):g}"
    else:
        coverage_targets = mouth_sizes = ratios = fixed_k = fixed_n = sweep_lower = sweep_upper = crossover = "—"

    document = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}
<title>Mouth-size / coverage grid</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#69d6c8;--good:#16856b;--warn:#b7791f;--bad:#b45353}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{max-width:1600px;margin:auto;padding:20px}}
h1,h2,h3{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2)}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-bottom:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.9rem;text-transform:uppercase;letter-spacing:.02em}}.badge.complete{{background:rgba(22,133,107,.18);color:#8de8cc}}.badge.running{{background:rgba(183,121,31,.2);color:#f6d39a}}.badge.failed{{background:rgba(180,83,83,.2);color:#ffb2b2}}.badge.pending{{background:rgba(148,163,189,.16);color:#c8d0d8}}
.best{{background:#173c39;color:#9af0df;font-weight:700}}.worst{{background:#482321;color:#ffaaa3;font-weight:700}}
.wide td:nth-child(5), .wide td:nth-child(6), .wide td:nth-child(7), .wide td:nth-child(8), .wide td:nth-child(9){{white-space:nowrap}}
.sortable{{cursor:pointer;user-select:none}}
.muted{{color:var(--muted)}}
@media(max-width:1100px){{.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:700px){{.summary{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Mouth-size / coverage grid</h1>
<p class='muted'>This overview keeps the same structure as a search report, but combines the candidate entries from every sub-search into one active ranking. The combined ranking is sorted by the mean of coverage match, coverage smoothness, waist stability, and window uniformity for each completed candidate.</p>
<section class='summary'>
<div class='card'><strong>{started} / {total}</strong> started</div>
<div class='card'><strong>{running}</strong> running sub-searches</div>
<div class='card'><strong>{complete}</strong> complete sub-searches</div>
<div class='card'><strong>{completed_candidates}</strong> completed candidates</div>
</section>
<section>
<h2>Project range</h2>
<table><tr><th>Coverage targets</th><th>Mouth sizes</th><th>Fixed K / N</th><th>Sweep / crossover</th><th>Ratios</th></tr>
<tr><td>{coverage_targets} deg</td><td>{mouth_sizes} mm</td><td>K={fixed_k}, N={fixed_n}</td><td>{sweep_lower}-{sweep_upper} Hz / {crossover} Hz</td><td>{", ".join(f"{ratio:g}" for ratio in ratios) if ratios != "—" else "—"}</td></tr></table>
</section>
<section>
<h2>Active ranking</h2>
<table class='wide sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>Rank</th><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-sort='text'>Search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Average diagnostic score</th><th class='sortable' data-sort='number'>Coverage Match</th><th class='sortable' data-sort='number'>Coverage Smoothness</th><th class='sortable' data-sort='number'>Waist Stability</th><th class='sortable' data-sort='number'>Window Uniformity</th><th class='sortable' data-sort='number'>Impedance</th><th class='sortable' data-sort='number'>Length mm</th><th class='sortable' data-sort='number'>Extension mm</th><th class='sortable' data-sort='number'>OS-SE H/V</th><th class='sortable' data-sort='number'>K H/V</th><th class='sortable' data-sort='number'>S H/V</th><th class='sortable' data-sort='number'>N H/V</th><th class='sortable' data-sort='number'>Curvature radius H/V mm</th><th class='sortable' data-sort='text'>Distinguishing trait</th><th>Search report</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</section>
<section>
<h2>All results</h2>
<p class='muted'>This is the full candidate list across every sub-search. Click any column header to sort it.</p>
<table class='wide sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>Rank</th><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-sort='text'>Search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Average diagnostic score</th><th class='sortable' data-sort='number'>Coverage Match</th><th class='sortable' data-sort='number'>Coverage Smoothness</th><th class='sortable' data-sort='number'>Waist Stability</th><th class='sortable' data-sort='number'>Window Uniformity</th><th class='sortable' data-sort='number'>Impedance</th><th class='sortable' data-sort='number'>Length mm</th><th class='sortable' data-sort='number'>Extension mm</th><th class='sortable' data-sort='number'>OS-SE H/V</th><th class='sortable' data-sort='number'>K H/V</th><th class='sortable' data-sort='number'>S H/V</th><th class='sortable' data-sort='number'>N H/V</th><th class='sortable' data-sort='number'>Curvature radius H/V mm</th><th class='sortable' data-sort='text'>Distinguishing trait</th><th>Search report</th></tr></thead>
<tbody>
{''.join(all_result_rows)}
</tbody>
</table>
</section>
<section>
<h2>Sub-searches</h2>
<table class='sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>Rank</th><th class='sortable' data-sort='text'>Sub-search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Complete / Proposed</th><th class='sortable' data-sort='number'>Average score</th><th class='sortable' data-sort='number'>Best score</th><th class='sortable' data-sort='text'>Best candidate</th><th>Links</th></tr></thead>
<tbody>{''.join(summary_rows)}</tbody>
</table>
</section>
<section>
<p class='muted'>Best active sub-search: {html.escape(best['label']) if best else '—'}{f" at {best['average_score']:.1f}%" if best and best['average_score'] is not None else ''}.</p>
</section>
<script>
(() => {{
  const compare = (a, b, type, direction) => {{
    const mul = direction === 'asc' ? 1 : -1;
    if (type === 'number') {{
      const an = Number(a);
      const bn = Number(b);
      const aval = Number.isFinite(an) ? an : -Infinity;
      const bval = Number.isFinite(bn) ? bn : -Infinity;
      return aval === bval ? 0 : (aval < bval ? -1 : 1) * mul;
    }}
    return String(a).localeCompare(String(b), undefined, {{numeric: true, sensitivity: 'base'}}) * mul;
  }};
  document.querySelectorAll('table.sortable-table').forEach((table) => {{
    const headers = Array.from(table.querySelectorAll('th[data-sort]'));
    let activeIndex = -1;
    let activeDirection = 'desc';
    const sortBy = (index, direction) => {{
      const type = headers[index]?.dataset.sort || 'text';
      const tbody = table.tBodies[0];
      const rows = Array.from(tbody.rows);
      rows.sort((rowA, rowB) => {{
        const cellA = rowA.cells[index];
        const cellB = rowB.cells[index];
        const valueA = cellA?.dataset.sort ?? cellA?.textContent ?? '';
        const valueB = cellB?.dataset.sort ?? cellB?.textContent ?? '';
        return compare(valueA, valueB, type, direction);
      }});
      tbody.replaceChildren(...rows);
      headers.forEach((th, i) => th.setAttribute('aria-sort', i === index ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'));
      activeIndex = index;
      activeDirection = direction;
    }};
    headers.forEach((header, index) => {{
      header.addEventListener('click', () => {{
        const direction = activeIndex === index && activeDirection === 'desc' ? 'asc' : 'desc';
        sortBy(index, direction);
      }});
    }});
    if (headers.length) {{
      sortBy(4, 'desc');
    }}
  }});
}})();
</script>
</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.project_root / "index.html"
    print(generate_report(args.project_root, output))


if __name__ == "__main__":
    main()
