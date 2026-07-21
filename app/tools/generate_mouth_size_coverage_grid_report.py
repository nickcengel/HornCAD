#!/usr/bin/env python3
"""Generate an overview report for the mouth-size/coverage survey grid."""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from statistics import fmean
from typing import Any

import yaml

try:
    from .surface_diagnostics import surface_score
except ImportError:
    from surface_diagnostics import surface_score


LEGACY_RANKING_KEYS = (
    "coverage_match_percent",
    "coverage_smoothness_percent",
    "waist_stability_percent",
    "window_uniformity_percent",
)


def _legacy_ranking_score(candidate: dict[str, Any]) -> float | None:
    combined = candidate.get("diagnostics", {}).get("combined", {})
    if not isinstance(combined, dict):
        return None
    values = [combined.get(key) for key in LEGACY_RANKING_KEYS]
    if not all(isinstance(value, (int, float)) for value in values):
        return None
    return fmean(float(value) for value in values)


def _search_summary(path: Path) -> dict[str, Any]:
    coverage_dir = path.parent.parent.name
    mouth_dir = path.parent.name
    coverage = float(coverage_dir.removesuffix("deg"))
    mouth = float(mouth_dir.split("x", 1)[0])
    study_label = "uniform S grid" if mouth_dir.endswith("-s-grid") else "original"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))["bem_candidate_search"]
    seed_path = Path(config.get("seed_yaml", "project.yaml"))
    if not seed_path.is_absolute():
        seed_path = path.parent / seed_path
    seed_global = {}
    if seed_path.is_file():
        seed_document = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
        seed_global = seed_document.get("horncad_config", {}).get("global", {})
    state_path = path.parent / "search_state.json"
    report_path = path.parent / "search_report.html"
    summary: dict[str, Any] = {
        "coverage": coverage,
        "mouth": mouth,
        "mouth_width": float(seed_global.get("mouth_width", mouth)),
        "mouth_height": float(seed_global.get("mouth_height", mouth)),
        "label": (
            f"{coverage:g} deg\u00a0/\u200b {mouth:g} mm"
            + (" · uniform S grid" if study_label == "uniform S grid" else "")
        ),
        "study": study_label,
        "folder": path.parent,
        "search_yaml": path,
        "config": config,
        "state_path": state_path,
        "report_path": report_path if report_path.is_file() else None,
        "status": "not started",
        "phase": "",
        "counts": {},
        "completed": 0,
        "failed": 0,
        "running": 0,
        "rejected": 0,
        "proposal_count": 0,
        "completed_at_unix": None,
        "candidates": [],
    }
    if not state_path.is_file():
        return summary
    state = json.loads(state_path.read_text())
    summary["status"] = str(state.get("status", "unknown"))
    summary["phase"] = str(state.get("phase", ""))
    summary["proposal_count"] = int(state.get("proposal_count", 0))
    summary["completed_at_unix"] = state.get("completed_at_unix")
    summary["rejected"] = int(state.get("rejected_count", 0))
    counts: dict[str, int] = {}
    completed_candidates = []
    for candidate in state.get("candidates", []):
        status = str(candidate.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status != "complete":
            continue
        completed_candidates.append(candidate)
    summary["counts"] = counts
    summary["completed"] = counts.get("complete", 0)
    summary["failed"] = counts.get("failed", 0)
    summary["running"] = counts.get("running", 0)
    summary["candidates"] = completed_candidates
    return summary


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
    summaries.sort(key=lambda item: (item["coverage"], item["mouth"]))
    total = len(summaries)
    started = sum(summary["status"] != "not started" for summary in summaries)
    running = sum(summary["status"] == "running" for summary in summaries)
    complete = sum(summary["status"] == "complete" for summary in summaries)
    completed_candidates = sum(summary["completed"] for summary in summaries)
    candidate_rows = []
    for summary in summaries:
        for candidate in summary["candidates"]:
            new_score = surface_score(candidate.get("surface_diagnostics", {}), {
                "horizontal": summary["mouth_width"],
                "vertical": summary["mouth_height"],
            })
            candidate_rows.append({
                "search": summary,
                "candidate": candidate,
                "legacy_ranking_score": _legacy_ranking_score(candidate),
                "surface_ranking_score": (
                    float(new_score["overall_percent"]) if new_score else None),
            })
    legacy_order = sorted(candidate_rows, key=lambda item: (
        item["legacy_ranking_score"] is None,
        -(item["legacy_ranking_score"] or 0.0),
        item["search"]["coverage"],
        item["search"]["mouth"],
        item["candidate"]["id"],
    ))
    for previous_rank, item in enumerate(legacy_order, 1):
        item["legacy_rank"] = previous_rank
    candidate_rows.sort(
        key=lambda item: (
            item["surface_ranking_score"] is None,
            -(item["surface_ranking_score"] or 0.0),
            item["search"]["coverage"],
            item["search"]["mouth"],
            item["candidate"]["id"],
        )
    )
    for row in candidate_rows:
        candidate = row["candidate"]
        candidate_dir = row["search"]["folder"] / "candidates" / candidate["id"]
        row["project_yaml"] = candidate_dir / "project.yaml"
        row["stl_path"] = candidate_dir / candidate.get("stl_file", "")
        report_file = candidate.get("report_file")
        row["report_path"] = (
            row["search"]["folder"] / report_file if report_file else
            next(candidate_dir.glob("bem/*_Report.html"), None)
        )
        newest = candidate.get("completed_at_unix")
        if not isinstance(newest, (int, float)):
            newest = row["search"].get("completed_at_unix")
        if not isinstance(newest, (int, float)) and row["report_path"] is not None:
            newest = row["report_path"].stat().st_mtime
        row["newest_at_unix"] = (
            float(newest) if isinstance(newest, (int, float)) else None)
        row["artifact_stem"] = candidate.get("artifact_stem", candidate["id"])
        row["length_mouth_ratio"] = (
            float(row["search"]["mouth_width"]) /
            float(candidate.get("values", {}).get("length_mm", 0))
        )
        row["label"] = candidate.get("proposal_source", "").replace("_", " ").strip().title() or "Candidate"
        if row["label"] == "Seed":
            row["label"] = "Seed design"

    def surface_pair(candidate: dict[str, Any], path: tuple[str, ...],
                     suffix: str = "", scale: float = 1.0) -> tuple[str, str]:
        result = candidate.get("surface_diagnostics", {})
        values = []
        if result.get("status") == "available":
            for plane_name in ("horizontal", "vertical"):
                selected: Any = result.get(plane_name, {})
                for key in path:
                    selected = selected.get(key, {}) if isinstance(selected, dict) else {}
                if isinstance(selected, (int, float)):
                    values.append(float(selected) * scale)
        if len(values) != 2:
            return "", "—"
        return (f"{sum(values) / 2:.6f}",
                f"{values[0]:.3g}{suffix}&nbsp;/<wbr> {values[1]:.3g}{suffix}")

    refresh = "<meta http-equiv='refresh' content='30'>" if running else ""
    rows = []
    for item in candidate_rows:
        summary = item["search"]
        candidate = item["candidate"]
        containment_sort, containment_text = surface_pair(
            candidate, ("containment", "mean_fraction"), "%", 100)
        profile_sort, profile_text = surface_pair(
            candidate, ("distribution", "rms_profile_error_db"), " dB")
        rise_sort, rise_text = surface_pair(
            candidate, ("distribution", "rms_outward_rise_violation_db"), " dB")
        slice_sort, slice_text = surface_pair(
            candidate, ("slice_energy_stability", "rms_departure_db"), " dB")
        line_sort, line_text = surface_pair(
            candidate, ("minus_six_line", "rms_coverage_error_deg"), "°")
        legacy_score = item["legacy_ranking_score"]
        legacy_score_sort = "" if legacy_score is None else f"{legacy_score:.6f}"
        legacy_score_text = "—" if legacy_score is None else f"{legacy_score:.1f}%"
        surface_score_value = item["surface_ranking_score"]
        surface_score_sort = ("" if surface_score_value is None
                              else f"{surface_score_value:.6f}")
        surface_score_text = ("—" if surface_score_value is None
                              else f"{surface_score_value:.1f}%")
        newest = item["newest_at_unix"]
        newest_sort = "" if newest is None else f"{newest:.6f}"
        newest_text = ("—" if newest is None else datetime.fromtimestamp(
            newest).astimezone().strftime("%-m-%d %H:%M"))
        candidate_name = html.escape(item["artifact_stem"])
        candidate_links = []
        if item["report_path"] is not None:
            candidate_links.append(
                f"<a href='{html.escape(str(item['report_path'].relative_to(project_root)))}'>{candidate_name}</a>"
            )
        else:
            candidate_links.append(candidate_name)
        if item["stl_path"].is_file():
            candidate_links.append(
                f"<a href='{html.escape(str(item['stl_path'].relative_to(project_root)))}'>STL</a>"
            )
        if item["report_path"] is not None:
            candidate_links.append(
                f"<a href='{html.escape(str(item['report_path'].relative_to(project_root)))}'>report</a>"
            )
        rows.append(
            "<tr>"
            f"<td data-sort='{html.escape(item['artifact_stem'])}'>{' · '.join(candidate_links)}</td>"
            f"<td data-column='surface-score' data-sort='{surface_score_sort}'>{surface_score_text}</td>"
            f"<td data-sort='{newest_sort}'>{newest_text}</td>"
            f"<td data-column='legacy-rank' hidden data-sort='{item['legacy_rank']}'>{item['legacy_rank']}</td>"
            f"<td data-column='legacy-score' hidden data-sort='{legacy_score_sort}'>{legacy_score_text}</td>"
            f"<td class='axis-pair' data-column='containment-mean' hidden data-sort='{containment_sort}'>{containment_text}</td>"
            f"<td class='axis-pair' data-column='profile-rms' hidden data-sort='{profile_sort}'>{profile_text}</td>"
            f"<td class='axis-pair' data-column='outward-rise' hidden data-sort='{rise_sort}'>{rise_text}</td>"
            f"<td class='axis-pair' data-column='slice-rms' hidden data-sort='{slice_sort}'>{slice_text}</td>"
            f"<td class='axis-pair' data-column='line-rms' hidden data-sort='{line_sort}'>{line_text}</td>"
            f"<td data-column='length' hidden data-sort='{candidate.get('values', {}).get('length_mm', 0):.6f}'>{candidate.get('values', {}).get('length_mm', 0):g}</td>"
            f"<td data-column='length-mouth-ratio' hidden data-sort='{item['length_mouth_ratio']:.6f}'>{item['length_mouth_ratio']:.3f}</td>"
            f"<td data-column='extension' hidden data-sort='{candidate.get('values', {}).get('extension_mm', 0):.6f}'>{candidate.get('values', {}).get('extension_mm', 0):g}</td>"
            f"<td class='axis-pair' data-column='osse' hidden data-sort='{candidate.get('values', {}).get('osse_coverage_h_deg', 0):.6f}'>{candidate.get('values', {}).get('osse_coverage_h_deg', 0):g}&nbsp;/<wbr> {candidate.get('values', {}).get('osse_coverage_v_deg', 0):g}</td>"
            f"<td class='axis-pair' data-column='k' hidden data-sort='{candidate.get('values', {}).get('k_h', 0):.6f}'>{candidate.get('values', {}).get('k_h', 0):.2f}&nbsp;/<wbr> {candidate.get('values', {}).get('k_v', 0):.2f}</td>"
            f"<td class='axis-pair' data-column='s' hidden data-sort='{candidate.get('derived', {}).get('s_h', 0):.6f}'>{candidate.get('derived', {}).get('s_h', 0):.3f}&nbsp;/<wbr> {candidate.get('derived', {}).get('s_v', 0):.3f}</td>"
            f"<td class='axis-pair' data-column='n' hidden data-sort='{candidate.get('values', {}).get('n_h', 0):.6f}'>{candidate.get('values', {}).get('n_h', 0):g}&nbsp;/<wbr> {candidate.get('values', {}).get('n_v', 0):g}</td>"
            f"<td data-column='trait' hidden data-sort='{html.escape(item['label'])}'>{html.escape(item['label'])}</td>"
            f"<td data-column='mouth-height' hidden data-sort='{summary['mouth_height']:.6f}'>{summary['mouth_height']:g}</td>"
            f"<td data-column='mouth-width' hidden data-sort='{summary['mouth_width']:.6f}'>{summary['mouth_width']:g}</td>"
            "</tr>"
        )

    summary_rows = []
    for rank, summary in enumerate(summaries, 1):
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(summary['status'])}</span>"
        summary_rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{html.escape(summary['label'])}</td>"
            f"<td>{status_badge}</td>"
            f"<td>{summary['completed']}&nbsp;/<wbr> {summary['proposal_count']}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )

    project_configs = [summary["config"] for summary in summaries if summary["config"]]
    if project_configs:
        first = project_configs[0]
        coverage_targets = ", ".join(f"{summary['coverage']:g}" for summary in summaries)
        mouth_sizes = ", ".join(f"{summary['mouth']:g}" for summary in summaries)
        ratios = sorted({
            round(
                float(summary["mouth_width"]) / float(candidate["values"]["length_mm"]),
                3
            )
            for summary in summaries
            for candidate in summary["candidates"]
        })
        fixed_k = f"{first.get('bounds', {}).get('k_h', [0, 0])[0]:g}"
        fixed_n = f"{first.get('bounds', {}).get('n_h', [0, 0])[0]:g}"
        sweep_lower = f"{first.get('lower_frequency_hz', 0):g}"
        sweep_upper = f"{first.get('upper_frequency_hz', 0):g}"
        crossover = f"{first.get('crossover_hz', 0):g}"
    else:
        coverage_targets = mouth_sizes = ratios = fixed_k = fixed_n = sweep_lower = sweep_upper = crossover = "—"

    toggle_columns = (
        ("surface-score", "Final surface score", True),
        ("legacy-rank", "Previous rank", False),
        ("legacy-score", "Previous diagnostic score", False),
        ("containment-mean", "Mean containment H / V", False),
        ("profile-rms", "Profile RMS error H / V", False),
        ("outward-rise", "Outward-rise violation H / V", False),
        ("slice-rms", "Slice-energy RMS departure H / V", False),
        ("line-rms", "−6 dB RMS error H / V", False),
        ("length", "Length mm", False),
        ("length-mouth-ratio", "Length-mouth ratio", False),
        ("extension", "Extension mm", False),
        ("osse", "OS-SE H / V", False),
        ("k", "K H / V", False),
        ("s", "S H / V", False),
        ("n", "N H / V", False),
        ("trait", "Distinguishing trait", False),
        ("mouth-height", "Mouth height", False),
        ("mouth-width", "Mouth width", False),
    )
    column_toggles = "".join(
        f"<button type='button' class='column-toggle' data-column-toggle='{column}' "
        f"aria-pressed='{'true' if visible else 'false'}'>{html.escape(label)}</button>"
        for column, label, visible in toggle_columns)

    document = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}
<title>Mouth-size / coverage grid</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#69d6c8;--good:#16856b;--warn:#b7791f;--bad:#b45353}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}
h1,h2,h3{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-bottom:4px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.9rem;text-transform:uppercase;letter-spacing:.02em}}.badge.complete{{background:rgba(22,133,107,.18);color:#8de8cc}}.badge.running{{background:rgba(183,121,31,.2);color:#f6d39a}}.badge.failed{{background:rgba(180,83,83,.2);color:#ffb2b2}}.badge.pending{{background:rgba(148,163,189,.16);color:#c8d0d8}}
.best{{background:#173c39;color:#9af0df;font-weight:700}}.worst{{background:#482321;color:#ffaaa3;font-weight:700}}
.wide td:nth-child(5), .wide td:nth-child(6), .wide td:nth-child(7), .wide td:nth-child(8), .wide td:nth-child(9){{white-space:nowrap}}
.sortable{{cursor:pointer;user-select:none}}.axis-pair{{white-space:normal}}[hidden]{{display:none!important}}
.column-controls{{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 12px}}.column-toggle{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}
.muted{{color:var(--muted)}}
@media(max-width:1100px){{.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:700px){{.summary{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Mouth-size / coverage grid</h1>
<p class='muted'>Candidates are ranked by the final surface score. Previous rank and previous diagnostic score are shown beside it for direct comparison. The final score weights profile RMS error 30%, slice-energy departure 25%, mean containment 20%, outward-rise violation 15%, and the secondary −6 dB line 10%.</p>
<section class='summary'>
<div class='card'><strong>{started}&nbsp;/<wbr> {total}</strong> started</div>
<div class='card'><strong>{running}</strong> running sub-searches</div>
<div class='card'><strong>{complete}</strong> complete sub-searches</div>
<div class='card'><strong>{completed_candidates}</strong> completed candidates</div>
</section>
<section>
<h2>Project range</h2>
<table><tr><th>Coverage targets</th><th>Mouth sizes</th><th>Fixed K&nbsp;/ N</th><th>Sweep&nbsp;/ crossover</th><th>Length-mouth ratios</th></tr>
<tr><td>{coverage_targets} deg</td><td>{mouth_sizes} mm</td><td>K={fixed_k}, N={fixed_n}</td><td>{sweep_lower}-{sweep_upper} Hz&nbsp;/<wbr> {crossover} Hz</td><td>{", ".join(f"{ratio:g}" for ratio in ratios) if ratios != "—" else "—"}</td></tr></table>
</section>
<section>
<h2>Candidates</h2>
<div class='column-controls' aria-label='Candidate table columns'>{column_toggles}</div>
<table class='wide sortable-table'>
<thead><tr><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-column='surface-score' data-sort='number'>Final surface score</th><th class='sortable' data-sort='number'>Newest</th><th class='sortable' data-column='legacy-rank' hidden data-sort='number'>Previous rank</th><th class='sortable' data-column='legacy-score' hidden data-sort='number'>Previous diagnostic score</th><th class='sortable' data-column='containment-mean' hidden data-sort='number'>Mean containment H&nbsp;/ V</th><th class='sortable' data-column='profile-rms' hidden data-sort='number'>Profile RMS error H&nbsp;/ V</th><th class='sortable' data-column='outward-rise' hidden data-sort='number'>Outward-rise violation H&nbsp;/ V</th><th class='sortable' data-column='slice-rms' hidden data-sort='number'>Slice-energy RMS departure H&nbsp;/ V</th><th class='sortable' data-column='line-rms' hidden data-sort='number'>−6 dB RMS error H&nbsp;/ V</th><th class='sortable' data-column='length' hidden data-sort='number'>Length mm</th><th class='sortable' data-column='length-mouth-ratio' hidden data-sort='number'>Length-mouth ratio</th><th class='sortable' data-column='extension' hidden data-sort='number'>Extension mm</th><th class='sortable' data-column='osse' hidden data-sort='number'>OS-SE H&nbsp;/ V</th><th class='sortable' data-column='k' hidden data-sort='number'>K H&nbsp;/ V</th><th class='sortable' data-column='s' hidden data-sort='number'>S H&nbsp;/ V</th><th class='sortable' data-column='n' hidden data-sort='number'>N H&nbsp;/ V</th><th class='sortable' data-column='trait' hidden data-sort='text'>Distinguishing trait</th><th class='sortable' data-column='mouth-height' hidden data-sort='number'>Mouth height</th><th class='sortable' data-column='mouth-width' hidden data-sort='number'>Mouth width</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</section>
<section>
<h2>Sub-searches</h2>
<table class='sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>#</th><th class='sortable' data-sort='text'>Sub-search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Complete&nbsp;/ Proposed</th><th>Links</th></tr></thead>
<tbody>{''.join(summary_rows)}</tbody>
</table>
</section>
<script>
(() => {{
  document.querySelectorAll('[data-column-toggle]').forEach((button) => {{
    button.addEventListener('click', () => {{
      const visible = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', String(visible));
      document.querySelectorAll(`[data-column="${{button.dataset.columnToggle}}"]`).forEach((cell) => {{
        cell.hidden = !visible;
      }});
    }});
  }});
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
