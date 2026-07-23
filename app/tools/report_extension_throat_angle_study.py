#!/usr/bin/env python3
"""Refresh the extension/throat-angle study index from frozen runtime state."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import numpy as np

from .throat_impedance_diagnostics import (
    DIAGNOSTIC_VERSION,
    throat_impedance_diagnostics,
)


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _number(value: Any, digits: int = 1, suffix: str = "") -> str:
    return (f"{float(value):.{digits}f}{suffix}"
            if isinstance(value, (int, float)) and math.isfinite(value) else "—")


def _sort(value: Any) -> str:
    return str(value) if isinstance(value, (int, float)) and math.isfinite(value) else ""


def _percent_change(value: Any, parent: Any) -> float | None:
    if (not isinstance(value, (int, float))
            or not isinstance(parent, (int, float))
            or not math.isfinite(value)
            or not math.isfinite(parent)
            or parent == 0):
        return None
    return (float(value) - float(parent)) / float(parent) * 100.0


def _signed_percent(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "—"


def _date(value: Any) -> str:
    return (datetime.fromtimestamp(float(value)).strftime("%-m-%-d %H:%M")
            if isinstance(value, (int, float)) and value else "—")


def _relative(root: Path, path: Path) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _mean_axis(result: dict[str, Any], path: tuple[str, ...]) -> float | None:
    values = []
    for axis in ("horizontal", "vertical"):
        selected: Any = result.get(axis, {})
        for key in path:
            selected = selected.get(key) if isinstance(selected, dict) else None
        if not isinstance(selected, (int, float)) or not math.isfinite(selected):
            return None
        values.append(float(selected))
    return sum(values) / 2


def _record(root: Path, manifest: dict[str, Any],
            row: dict[str, Any]) -> dict[str, Any]:
    search_yaml = ROOT / manifest["inputs"][row["id"]]["search"]
    search = search_yaml.parent
    state = _read_json(search / "search_state.json")
    records = state.get("candidates", [])
    record = records[0] if isinstance(records, list) and records else {}
    surface = record.get("surface_diagnostics", {})
    report_file = record.get("report_file")
    status = str(record.get("status", state.get("status", "not-started")))
    if status == "not-started" and (search / "project.yaml").is_file():
        status = "planned"
    return {
        "status": status,
        "surface_score": (surface.get("score") or {}).get("overall_percent"),
        "throat_impedance_score": (
            record.get("throat_impedance_diagnostics") or {}).get(
                "overall_percent"),
        "containment": _mean_axis(surface, ("containment", "mean_fraction")),
        "profile_rms": _mean_axis(
            surface, ("distribution", "rms_profile_error_db")),
        "slice_rms": _mean_axis(
            surface, ("slice_energy_stability", "rms_departure_db")),
        "outward_rise": _mean_axis(
            surface, ("distribution", "rms_outward_rise_violation_db")),
        "minus_six_rms": _mean_axis(
            surface, ("minus_six_line", "rms_coverage_error_deg")),
        "completed_at": record.get("completed_at_unix", 0),
        "search_report": _relative(root, search / "search_report.html"),
        "candidate_report": (
            _relative(root, search / str(report_file)) if report_file else None),
    }


def build_progress(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for row in manifest["coordinates"]:
        candidates.append({**row, **_record(root, manifest, row)})
    stages = []
    for stage in (
        "primary-development", "secondary-transfer",
        "locked-validation", "conditional-validation",
    ):
        rows = [row for row in candidates if row["stage"] == stage]
        if not rows:
            continue
        stages.append({
            "stage": stage,
            "candidates": len(rows),
            "complete": sum(row["status"] == "complete" for row in rows),
            "running": sum(row["status"] == "running" for row in rows),
            "preflight": sum(row["status"] == "preflight" for row in rows),
            "failed": sum(row["status"] in {
                "failed", "error", "blocked", "geometry-rejected"} for row in rows),
        })
    runtime_labels = (
        ("conditional validation",
         root / "runtime-conditional-validation.json"),
        ("locked validation", root / "runtime-locked-validation.json"),
        ("development", root /
         "runtime-primary-development-secondary-transfer.json"),
    )
    study_status = str(manifest.get("status", "not launched"))
    runtime_active = False
    for label, path in runtime_labels:
        runtime = _read_json(path)
        if not runtime:
            continue
        state = str(runtime.get("status", "unknown"))
        study_status = f"{label} {state}"
        runtime_active = state == "running"
        break
    if (root / "results.json").is_file():
        study_status = "study complete"
        runtime_active = False
    return {
        "candidates": candidates,
        "stages": stages,
        "study_status": study_status,
        "runtime_active": runtime_active,
    }


def render_index(root: Path, manifest: dict[str, Any],
                 progress: dict[str, Any]) -> str:
    candidates = progress["candidates"]
    complete = sum(row["status"] == "complete" for row in candidates)
    running = sum(row["status"] == "running" for row in candidates)
    scored = sum(row["surface_score"] is not None for row in candidates)
    active = (progress.get("runtime_active", False) or running)
    refresh = "<meta http-equiv='refresh' content='30'>" if active else ""

    parent_impedance_scores = {}
    for role in ("primary", "secondary"):
        for parent in manifest["parents"][role].values():
            response = ROOT / parent["response_path"]
            source_state = _read_json(
                response.parents[3] / "search_state.json")
            with np.load(response, allow_pickle=False) as archive:
                frequencies = np.asarray(
                    archive["frequencies_hz"], dtype=float)
                impedance = np.asarray(archive["impedance"])
            diagnostic = throat_impedance_diagnostics(
                frequencies,
                impedance,
                float(source_state["crossover_hz"]),
                float(source_state.get(
                    "upper_frequency_hz", frequencies[-1])),
            )
            parent_impedance_scores[(role, parent["id"])] = float(
                diagnostic["overall_percent"])

    candidate_rows = []
    for row in sorted(candidates, key=lambda item: (
            item["surface_score"] is not None,
            item["surface_score"] or -math.inf), reverse=True):
        surface_change = _percent_change(
            row["surface_score"], row["parent_surface_score"])
        impedance_change = _percent_change(
            row["throat_impedance_score"],
            parent_impedance_scores[(row["parent_role"], row["parent_id"])])
        label = html.escape(row["id"])
        if row["candidate_report"]:
            label = f"<a href='{html.escape(row['candidate_report'])}'>{label}</a>"
        status_class = (
            "complete" if row["status"] == "complete" else
            "running" if row["status"] == "running" else
            "failed" if row["status"] in {
                "failed", "error", "blocked", "geometry-rejected"} else "pending")
        candidate_rows.append(
            f"<tr data-coverage-angle='{row['coverage_deg']}' "
            f"data-stage='{html.escape(row['stage'])}'>"
            f"<td>{label}</td>"
            f"<td data-sort='{_sort(row['surface_score'])}'>{_number(row['surface_score'])}</td>"
            f"<td data-sort='{_sort(row['throat_impedance_score'])}'>{_number(row['throat_impedance_score'])}</td>"
            f"<td class='{'delta-positive' if surface_change is not None and surface_change > 0 else 'delta-negative' if surface_change is not None and surface_change < 0 else ''}' "
            f"data-sort='{_sort(surface_change)}' "
            f"title='Parent surface score: {_number(row['parent_surface_score'],2)}'>"
            f"{_signed_percent(surface_change)}</td>"
            f"<td class='{'delta-positive' if impedance_change is not None and impedance_change > 0 else 'delta-negative' if impedance_change is not None and impedance_change < 0 else ''}' "
            f"data-sort='{_sort(impedance_change)}' "
            f"title='Parent throat-impedance score v{DIAGNOSTIC_VERSION}: "
            f"{_number(parent_impedance_scores[(row['parent_role'], row['parent_id'])],2)}'>"
            f"{_signed_percent(impedance_change)}</td>"
            f"<td data-sort='{row['completed_at']}'>{_date(row['completed_at'])}</td>"
            f"<td>{html.escape(row['stage'])}</td>"
            f"<td data-sort='{row['coverage_deg']}'>{row['coverage_deg']}°</td>"
            f"<td data-sort='{row['round_mouth_diameter_mm']}'>{row['round_mouth_diameter_mm']} mm</td>"
            f"<td>{html.escape(row['parent_role'])}</td>"
            f"<td data-column='parent'>{html.escape(row['parent_id'])}</td>"
            f"<td data-sort='{row['throat_angle_deg']}'>{row['throat_angle_deg']}°</td>"
            f"<td data-sort='{row['extension_mm']}'>{row['extension_mm']} mm</td>"
            f"<td data-column='s' data-sort='{_sort(row.get('derived_s'))}'>{_number(row.get('derived_s'),3)}</td>"
            f"<td><span class='badge {status_class}'>{html.escape(row['status'])}</span></td>"
            f"<td data-column='containment' hidden data-sort='{_sort(row['containment'])}'>{_number(row['containment']*100 if row['containment'] is not None else None,1,'%')}</td>"
            f"<td data-column='profile' hidden data-sort='{_sort(row['profile_rms'])}'>{_number(row['profile_rms'],3)}</td>"
            f"<td data-column='slice' hidden data-sort='{_sort(row['slice_rms'])}'>{_number(row['slice_rms'],3)}</td>"
            f"<td data-column='outward' hidden data-sort='{_sort(row['outward_rise'])}'>{_number(row['outward_rise'],3)}</td>"
            f"<td data-column='minus-six' hidden data-sort='{_sort(row['minus_six_rms'])}'>{_number(row['minus_six_rms'],2)}</td>"
            f"<td><a href='{html.escape(row['search_report'])}'>report</a></td></tr>")

    parent_rows = []
    parent_items = []
    for role in ("primary", "secondary"):
        for cell, parent in sorted(manifest["parents"][role].items()):
            response = ROOT / parent["response_path"]
            source_candidate = response.parents[1]
            source_search = response.parents[3]
            source_state = _read_json(source_search / "search_state.json")
            source_record = next((
                record for record in source_state.get("candidates", [])
                if record.get("id") == source_candidate.name
            ), {})
            report_file = source_record.get("report_file")
            source_report = (
                source_search / str(report_file)
                if report_file else source_search / "search_report.html"
            )
            report_href = _relative(root, source_report)
            parent_items.append({
                "role": role,
                "cell": cell,
                "id": parent["id"],
                "surface_score": float(
                    parent["responses"]["surface_score"]),
                "throat_impedance_score": parent_impedance_scores[
                    (role, parent["id"])],
                "report": report_href,
                "response_path": parent["response_path"],
            })
            parent_rows.append(
                f"<tr><td>{html.escape(role)}</td><td>{html.escape(cell)}</td>"
                f"<td>{html.escape(parent['id'])}</td>"
                f"<td>{_number(parent['responses']['surface_score'])}</td>"
                f"<td>{_number(parent_impedance_scores[(role, parent['id'])])}</td>"
                f"<td>{_number(parent['length_mm'],1)}</td>"
                f"<td>{_number(parent['s'],3)}</td><td>{_number(parent['k'],1)}</td>"
                f"<td>{_number(parent['n'],1)}</td>"
                f"<td><a href='{html.escape(report_href)}'>candidate</a></td></tr>")

    ranked_parents = sorted(
        parent_items, key=lambda item: item["throat_impedance_score"])
    parent_extremes = [
        *((item, "lowest impedance") for item in ranked_parents[:5]),
        *((item, "highest impedance") for item in ranked_parents[-5:]),
    ]
    curve_data = []
    # One continuous rank scale across all ten selected curves. Do not assign
    # independent palettes to the low-five and high-five groups.
    colors_worst_to_best = tuple(
        f"hsl({rank * 120 / 9:.1f} 72% 44%)" for rank in range(10))
    for color_rank, ((item, group), color) in enumerate(zip(
            parent_extremes, colors_worst_to_best)):
        with np.load(ROOT / item["response_path"], allow_pickle=False) as archive:
            frequencies = np.asarray(archive["frequencies_hz"], dtype=float)
            magnitude = np.abs(np.asarray(archive["impedance"]))
        peak = float(np.max(magnitude))
        if peak <= 0 or not np.isfinite(peak):
            raise ValueError(f"{item['id']}: invalid throat-impedance peak")
        curve_data.append({
            **item,
            "group": group,
            "color": color,
            "color_rank": color_rank,
            "frequencies": frequencies,
            "normalized": magnitude / peak,
        })
    frequency_min = min(float(np.min(item["frequencies"]))
                        for item in curve_data)
    frequency_max = max(float(np.max(item["frequencies"]))
                        for item in curve_data)
    plot_left, plot_top = 74.0, 20.0
    plot_width, plot_height = 986.0, 400.0

    def plot_x(frequency: float) -> float:
        return plot_left + (
            math.log2(frequency / frequency_min)
            / math.log2(frequency_max / frequency_min) * plot_width)

    def plot_y(value: float) -> float:
        return plot_top + (1.0 - value) * plot_height

    x_ticks = [
        frequency for frequency in (500, 1000, 2000, 4000, 8000, 16000)
        if frequency_min <= frequency <= frequency_max
    ]
    grid_lines = []
    for value in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = plot_y(value)
        grid_lines.append(
            f"<line x1='{plot_left}' y1='{y:.2f}' "
            f"x2='{plot_left+plot_width}' y2='{y:.2f}'/>"
            f"<text x='{plot_left-10}' y='{y+4:.2f}' "
            f"text-anchor='end'>{value:g}</text>")
    for frequency in x_ticks:
        x = plot_x(frequency)
        label = (f"{frequency/1000:g}k"
                 if frequency >= 1000 else str(frequency))
        grid_lines.append(
            f"<line x1='{x:.2f}' y1='{plot_top}' "
            f"x2='{x:.2f}' y2='{plot_top+plot_height}'/>"
            f"<text x='{x:.2f}' y='{plot_top+plot_height+23}' "
            f"text-anchor='middle'>{label}</text>")

    impedance_curves = []
    impedance_legend = []
    for item in curve_data:
        points = " ".join(
            f"{plot_x(float(frequency)):.2f},{plot_y(float(value)):.2f}"
            for frequency, value in zip(
                item["frequencies"], item["normalized"]))
        tooltip = (
            f"{item['id']}\n{item['cell']} · {item['role']}\n"
            f"{item['group']}\n"
            f"Throat-impedance diagnostic: "
            f"{item['throat_impedance_score']:.2f}\n"
            f"Surface score: {item['surface_score']:.2f}\n"
            "Each impedance magnitude curve is normalized to peak = 1\n"
            f"Open report: {item['report']}"
        )
        impedance_curves.append(
            f"<a class='impedance-curve-link' "
            f"href='{html.escape(item['report'])}' "
            "data-peak-normalized='1' "
            f"data-impedance-score='{item['throat_impedance_score']:.8f}' "
            f"data-color-rank='{item['color_rank']}' "
            f"data-title='{html.escape(tooltip)}' "
            f"title='{html.escape(tooltip)}' "
            f"aria-label='{html.escape(tooltip)}'>"
            f"<polyline class='impedance-hit' points='{points}'/>"
            f"<polyline class='impedance-curve' "
            f"style='stroke:{item['color']}' points='{points}'/></a>")
        impedance_legend.append(
            f"<a class='impedance-legend-item impedance-curve-link' "
            f"href='{html.escape(item['report'])}' "
            f"data-title='{html.escape(tooltip)}' "
            f"title='{html.escape(tooltip)}'>"
            f"<i style='background:{item['color']}'></i>"
            f"<span>{html.escape(item['cell'])} · "
            f"impedance {item['throat_impedance_score']:.1f} · "
            f"surface {item['surface_score']:.1f}</span></a>")

    coverages = (30, 35, 40, 45, 50)
    mouths = (250, 300, 350, 400, 450)
    grid_rows = []
    for mouth in mouths:
        cells = []
        for coverage in coverages:
            cell = [row for row in candidates
                    if row["coverage_deg"] == coverage
                    and row["round_mouth_diameter_mm"] == mouth]
            measured = [row for row in cell if row["surface_score"] is not None]
            best = max(measured, key=lambda row: row["surface_score"]) if measured else None
            cells.append(
                "<td class='design-cell'>"
                f"<strong class='design-score'>{_number(best['surface_score']) if best else '—'}</strong>"
                f"<span>surface · impedance {_number(best['throat_impedance_score']) if best else '—'}</span>"
                f"<span>{sum(row['status']=='complete' for row in cell)} / {len(cell)} complete</span>"
                f"<span>A {', '.join(map(str, sorted(set(row['throat_angle_deg'] for row in cell))))}° · "
                f"E {', '.join(map(str, sorted(set(row['extension_mm'] for row in cell))))} mm</span></td>")
        grid_rows.append(f"<tr><th>{mouth} mm</th>{''.join(cells)}</tr>")

    stage_rows = "".join(
        f"<tr><td>{html.escape(row['stage'])}</td><td>{row['candidates']}</td>"
        f"<td>{row['complete']}</td><td>{row['running']}</td>"
        f"<td>{row['preflight']}</td><td>{row['failed']}</td></tr>"
        for row in progress["stages"])

    subsearch_rows = "".join(
        f"<tr data-subsearch-coverage-angle='{row['coverage_deg']}'>"
        f"<td>{html.escape(row['stage'])}</td><td>{row['coverage_deg']}°</td>"
        f"<td>{row['round_mouth_diameter_mm']} mm</td>"
        f"<td>{row['throat_angle_deg']}°</td><td>{row['extension_mm']} mm</td>"
        f"<td><span class='badge {'complete' if row['status']=='complete' else 'running' if row['status']=='running' else 'pending'}'>{html.escape(row['status'])}</span></td>"
        f"<td>{_number(row['surface_score'])}</td>"
        f"<td>{_number(row['throat_impedance_score'])}</td>"
        f"<td><a href='{html.escape(row['search_report'])}'>report</a></td></tr>"
        for row in candidates)

    angle_buttons = "".join(
        f"<button class='angle-filter' data-angle-filter='{angle}' aria-pressed='false'>{angle}°</button>"
        for angle in coverages)
    stage_buttons = "".join(
        f"<button class='stage-filter' data-stage-filter='{stage}' aria-pressed='false'>{html.escape(stage)}</button>"
        for stage in ("primary-development", "secondary-transfer",
                      "locked-validation", "conditional-validation"))

    return f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Extension and throat-angle heuristic study</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#69d6c8;--good:#16856b;--warn:#b7791f;--bad:#b45353}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}h1,h2{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}th.sortable{{cursor:pointer;user-select:none}}th.sortable::after{{content:' ↕';color:var(--muted)}}th.sortable[aria-sort='ascending']::after{{content:' ↑';color:var(--accent)}}th.sortable[aria-sort='descending']::after{{content:' ↓';color:var(--accent)}}.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-bottom:4px}}.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.9rem;text-transform:uppercase}}.badge.complete{{background:rgba(22,133,107,.18);color:#8de8cc}}.badge.running{{background:rgba(183,121,31,.2);color:#f6d39a}}.badge.failed{{background:rgba(180,83,83,.2);color:#ffb2b2}}.badge.pending{{background:rgba(148,163,189,.16);color:#c8d0d8}}.delta-positive{{color:#8de8cc}}.delta-negative{{color:#ffb2b2}}.muted{{color:var(--muted)}}[hidden]{{display:none!important}}.column-controls,.angle-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 12px}}.column-toggle,.angle-filter,.stage-filter{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true'],.angle-filter[aria-pressed='true'],.stage-filter[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}.show-more{{display:block;margin:14px auto 2px;border:1px solid var(--accent);border-radius:999px;padding:8px 16px;background:#173c39;color:var(--ink);cursor:pointer}}.design-map{{table-layout:fixed;min-width:1000px}}.design-cell{{min-width:150px;background:#17212a;border:1px solid var(--line)}}.design-cell>span{{display:block;margin-top:4px;font-size:.8rem;color:#c1cbd2;white-space:nowrap}}.design-score{{font-size:1.45rem}}.impedance-scale{{display:grid;grid-template-columns:auto minmax(220px,520px) auto;align-items:center;gap:9px;margin:12px 0;color:var(--muted);font-size:.9rem}}.impedance-scale i{{height:10px;border-radius:999px;background:linear-gradient(90deg,hsl(0 72% 44%),hsl(60 72% 44%),hsl(120 72% 44%))}}.impedance-legend{{display:grid;grid-template-columns:1fr;gap:3px;margin:10px 0;max-width:760px}}.impedance-legend-item{{display:flex;align-items:center;gap:7px;padding:4px 7px;border:1px solid transparent;border-radius:5px;text-decoration:none;color:var(--muted)}}.impedance-legend-item i{{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none}}.impedance-legend-item:hover,.impedance-legend-item.active{{border-color:var(--accent);color:var(--ink);background:#173c39}}.impedance-frequency-plot{{min-width:760px;max-width:1200px;margin:auto}}.impedance-frequency-plot svg{{display:block;width:100%;height:auto;background:#0f151b;border:1px solid var(--line);border-radius:7px}}.impedance-grid line{{stroke:var(--line-soft);stroke-width:1}}.impedance-grid text,.axis-label{{fill:var(--muted);font:13px system-ui,sans-serif}}.impedance-curve{{fill:none;stroke-width:2.3;stroke-linejoin:round;stroke-linecap:round;opacity:.82}}.impedance-hit{{fill:none;stroke:transparent;stroke-width:12;pointer-events:stroke}}.impedance-curve-link:hover .impedance-curve,.impedance-curve-link.active .impedance-curve{{stroke-width:4.5;opacity:1}}.impedance-hover{{min-height:3.2em;white-space:pre-line;margin-bottom:0}}code{{overflow-wrap:anywhere}}@media(max-width:900px){{.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main><h1>Extension and throat-angle heuristic study</h1>
<p>Full 5×5 round-horn grid for deterministic extension and throat-angle design heuristics.</p>
<p class='muted'>Throat impedance is reported as an experimental diagnostic in every report. It is not included in the surface score, ranking, heuristic fit, or validation gate.</p>
<section class='summary'><div class='card'><strong>{complete} / {len(candidates)}</strong>BEM complete</div><div class='card'><strong>{running}</strong>running searches</div><div class='card'><strong>{scored}</strong>scored candidates</div><div class='card'><strong>{html.escape(str(progress.get('study_status', manifest['status'])))}</strong>study status</div></section>
<section><h2>Project range</h2><table><tr><th>Coverage half-angles</th><th>Round mouths</th><th>Throat angles</th><th>Extensions</th><th>Initial / hard cap</th><th>Scheduler</th></tr><tr><td>30, 35, 40, 45, 50°</td><td>250, 300, 350, 400, 450 mm</td><td>0, 6, 12°</td><td>0, 20, 40, 60 mm</td><td>{manifest['initial_candidate_count']} / {manifest['hard_candidate_cap']}</td><td>{manifest['scheduler']['queue_workers']} workers · {manifest['scheduler']['numcalc_process_capacity']} total NumCalc processes</td></tr></table><p class='muted'>Coordinate SHA-256: <code>{manifest['coordinate_sha256']}</code> · Manifest SHA-256: <code>{_digest(manifest)}</code></p></section>
<section><h2>Design map</h2><p class='muted'>Best measured surface score in each cell; its throat-impedance score is shown directly below it.</p><table class='design-map'><thead><tr><th>Mouth / coverage</th>{''.join(f'<th>{a}°</th>' for a in coverages)}</tr></thead><tbody>{''.join(grid_rows)}</tbody></table></section>
<section><h2>Measured round parents</h2><p class='muted'>Frozen measured parents. Throat impedance was recorded but not used to select either parent set.</p><table class='sortable-table'><thead><tr><th data-sort='text'>Role</th><th data-sort='text'>Cell</th><th data-sort='text'>Parent</th><th data-sort='number'>Surface score</th><th data-sort='number'>Throat-impedance score v{DIAGNOSTIC_VERSION}</th><th data-sort='number'>Length mm</th><th data-sort='number'>S</th><th data-sort='number'>K</th><th data-sort='number'>N</th><th>Report</th></tr></thead><tbody>{''.join(parent_rows)}</tbody></table></section>
<section><h2>Throat impedance v{DIAGNOSTIC_VERSION}: highest- and lowest-scoring parents</h2><p class='muted'>Complex throat-impedance magnitude versus frequency for the five lowest and five highest measured parents ranked by the experimental <em>throat-impedance diagnostic score</em>. Every curve is independently normalized so its peak magnitude equals 1. One continuous color scale covers all ten ranked curves, from worst overall in red through yellow to best overall in green. Hover a curve or legend entry to expose its candidate-report link; click to open it. Surface score is shown only as context.</p><div class='impedance-scale'><span>Worst impedance score</span><i></i><span>Best impedance score</span></div><div class='impedance-legend'>{''.join(impedance_legend)}</div><div class='impedance-frequency-plot'><svg viewBox='0 0 1100 470' role='img' aria-label='Normalized throat impedance magnitude versus frequency'><g class='impedance-grid'>{''.join(grid_lines)}</g><g>{''.join(impedance_curves)}</g><text class='axis-label' x='567' y='466' text-anchor='middle'>Frequency (Hz)</text><text class='axis-label' x='17' y='220' text-anchor='middle' transform='rotate(-90 17 220)'>Normalized |Z|</text></svg></div><p id='impedance-hover' class='impedance-hover muted'>Hover a curve or legend entry. Click any curve to open its candidate report.</p></section>
<section><h2>Candidates</h2><div class='column-controls'>{''.join(f"<button class='column-toggle' data-column-toggle='{key}' aria-pressed='{str(visible).lower()}'>{label}</button>" for key,label,visible in [('parent','Parent ID',True),('s','S',True),('containment','Containment',False),('profile','Profile RMS',False),('slice','Slice energy',False),('outward','Outward rise',False),('minus-six','−6 dB RMS',False)])}</div><div class='angle-controls'><button class='angle-filter' data-angle-filter='all' aria-pressed='true'>All coverages</button>{angle_buttons}<button class='stage-filter' data-stage-filter='all' aria-pressed='true'>All stages</button>{stage_buttons}<span id='candidate-count' class='muted'></span></div><table id='candidate-table' class='sortable-table'><thead><tr><th data-sort='text'>Candidate</th><th data-sort='number'>Surface score</th><th data-sort='number'>Throat-impedance score v{DIAGNOSTIC_VERSION}</th><th data-sort='number'>Surface Δ vs parent</th><th data-sort='number'>Impedance Δ vs parent</th><th data-sort='number'>Date</th><th data-sort='text'>Stage</th><th data-sort='number'>Coverage</th><th data-sort='number'>Mouth</th><th data-sort='text'>Parent role</th><th data-column='parent' data-sort='text'>Parent ID</th><th data-sort='number'>Throat angle</th><th data-sort='number'>Extension</th><th data-column='s' data-sort='number'>S</th><th data-sort='text'>Status</th><th data-column='containment' hidden data-sort='number'>Containment</th><th data-column='profile' hidden data-sort='number'>Profile RMS</th><th data-column='slice' hidden data-sort='number'>Slice energy</th><th data-column='outward' hidden data-sort='number'>Outward rise</th><th data-column='minus-six' hidden data-sort='number'>−6 dB RMS</th><th>Report</th></tr></thead><tbody>{''.join(candidate_rows)}</tbody></table><button id='candidate-show-more' class='show-more'>Show 25 more</button></section>
<section><h2>Execution stages</h2><table class='sortable-table'><thead><tr><th data-sort='text'>Stage</th><th data-sort='number'>Candidates</th><th data-sort='number'>Complete</th><th data-sort='number'>Running</th><th data-sort='number'>Preflight</th><th data-sort='number'>Failed</th></tr></thead><tbody>{stage_rows}</tbody></table></section>
<section><h2>Sub-searches</h2><p class='muted'>Each fixed candidate is an independently recoverable one-candidate search.</p><table class='sortable-table'><thead><tr><th data-sort='text'>Stage</th><th data-sort='number'>Coverage</th><th data-sort='number'>Mouth</th><th data-sort='number'>Throat angle</th><th data-sort='number'>Extension</th><th data-sort='text'>Status</th><th data-sort='number'>Surface score</th><th data-sort='number'>Throat-impedance score v{DIAGNOSTIC_VERSION}</th><th>Report</th></tr></thead><tbody>{subsearch_rows}</tbody></table></section>
<script>(()=>{{document.querySelectorAll('[data-column-toggle]').forEach(b=>b.onclick=()=>{{const on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',String(on));document.querySelectorAll(`[data-column="${{b.dataset.columnToggle}}"]`).forEach(x=>x.hidden=!on);}});const table=document.getElementById('candidate-table'),more=document.getElementById('candidate-show-more'),count=document.getElementById('candidate-count');let angle='all',stage='all',limit=25;function filter(){{let match=0,shown=0;Array.from(table.tBodies[0].rows).forEach(r=>{{const ok=(angle==='all'||r.dataset.coverageAngle===angle)&&(stage==='all'||r.dataset.stage===stage);if(ok)match++;r.hidden=!(ok&&shown++<limit);}});shown=Math.min(match,limit);count.textContent=`Showing ${{shown}} of ${{match}}`;more.hidden=shown>=match;}}document.querySelectorAll('[data-angle-filter]').forEach(b=>b.onclick=()=>{{angle=b.dataset.angleFilter;limit=25;document.querySelectorAll('[data-angle-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));filter();}});document.querySelectorAll('[data-stage-filter]').forEach(b=>b.onclick=()=>{{stage=b.dataset.stageFilter;limit=25;document.querySelectorAll('[data-stage-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));filter();}});more.onclick=()=>{{limit+=25;filter();}};document.querySelectorAll('table.sortable-table').forEach(t=>{{const hs=Array.from(t.querySelectorAll('th[data-sort]'));let active=-1,dir='desc';hs.forEach(h=>{{h.classList.add('sortable');const sort=()=>{{const col=h.cellIndex;dir=active===col&&dir==='desc'?'asc':'desc';active=col;hs.forEach(x=>x.removeAttribute('aria-sort'));h.setAttribute('aria-sort',dir==='asc'?'ascending':'descending');const mul=dir==='asc'?1:-1,rows=Array.from(t.tBodies[0].rows);rows.sort((a,b)=>{{let x=a.cells[col]?.dataset.sort??a.cells[col]?.textContent??'',y=b.cells[col]?.dataset.sort??b.cells[col]?.textContent??'';if(h.dataset.sort==='number'){{x=Number(x);y=Number(y);x=Number.isFinite(x)?x:-Infinity;y=Number.isFinite(y)?y:-Infinity;}}return(x<y?-1:x>y?1:0)*mul;}});t.tBodies[0].replaceChildren(...rows);if(t===table)filter();}};h.onclick=sort;}});}});const hover=document.getElementById('impedance-hover');document.querySelectorAll('.impedance-curve-link').forEach(link=>{{const show=()=>{{hover.replaceChildren();const text=document.createElement('span');text.textContent=link.dataset.title+' — ';const open=document.createElement('a');open.href=link.getAttribute('href');open.textContent='open candidate report';hover.append(text,open);document.querySelectorAll('.impedance-curve-link').forEach(x=>x.classList.toggle('active',x.getAttribute('href')===link.getAttribute('href')));}};link.addEventListener('mouseenter',show);link.addEventListener('focus',show);}});filter();}})();</script></main></body></html>"""


def refresh_index(root: Path) -> Path:
    manifest = _read_json(root / "manifest.json")
    if not manifest:
        raise RuntimeError(f"missing manifest: {root / 'manifest.json'}")
    output = render_index(root, manifest, build_progress(root, manifest))
    path = root / "index.html"
    temporary = path.with_suffix(".html.tmp")
    temporary.write_text(output, encoding="utf-8")
    temporary.replace(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?",
                        default=Path("examples/extension-throat-angle-heuristics"))
    parser.add_argument(
        "--watch-seconds", type=float, default=0.0,
        help="refresh repeatedly while any study runtime ledger is running",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if args.watch_seconds < 0:
        parser.error("--watch-seconds must be nonnegative")
    while True:
        refresh_index(root)
        active = any(
            _read_json(path).get("status") == "running"
            for path in root.glob("runtime-*.json")
        )
        if not active or args.watch_seconds == 0:
            break
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    main()
