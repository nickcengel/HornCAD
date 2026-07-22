#!/usr/bin/env python3
"""Refresh the full control-decoupling study index from frozen/runtime state."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any

import yaml


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _same_values(record: dict[str, Any], row: dict[str, Any]) -> bool:
    expected = {
        "length_mm": row["length_mm"],
        "osse_coverage_h_deg": row["coverage_deg"],
        "osse_coverage_v_deg": row["coverage_deg"],
        "k_h": row["k"], "k_v": row["k"],
        "n_h": row["n"], "n_v": row["n"],
    }
    try:
        return all(math.isclose(float(record[key]), float(value),
                                rel_tol=0.0, abs_tol=2e-5)
                   for key, value in expected.items())
    except (KeyError, TypeError, ValueError):
        return False


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


def _candidate(row: dict[str, Any], record: dict[str, Any] | None,
               report: str | None, fallback_score: float | None = None
               ) -> dict[str, Any]:
    result = (record or {}).get("surface_diagnostics", {})
    score = (result.get("score") or {}).get("overall_percent", fallback_score)
    derived = (record or {}).get("derived", {})
    s = row.get("s")
    if isinstance(derived.get("s_h"), (int, float)):
        s = (float(derived["s_h"]) + float(derived.get("s_v", derived["s_h"]))) / 2
    return {
        "id": row["id"], "coverage_deg": row["coverage_deg"],
        "mouth_mm": row["mouth_mm"], "length_mm": row["length_mm"],
        "length_mouth_ratio": row["length_mm"] / row["mouth_mm"],
        "k": row["k"], "n": row["n"], "s": s,
        "score": float(score) if isinstance(score, (int, float)) else None,
        "date_unix": float((record or {}).get("completed_at_unix", 0.0)),
        "report": report,
        "containment": _mean_axis(result, ("containment", "mean_fraction")),
        "profile_rms": _mean_axis(
            result, ("distribution", "rms_profile_error_db")),
        "slice_rms": _mean_axis(
            result, ("slice_energy_stability", "rms_departure_db")),
        "outward_rise": _mean_axis(
            result, ("distribution", "rms_outward_rise_violation_db")),
        "minus_six_rms": _mean_axis(
            result, ("minus_six_line", "rms_coverage_error_deg")),
    }


def build_progress(root: Path, manifest: dict[str, Any],
                   plan: dict[str, Any]) -> dict[str, Any]:
    runtime = _read_json(root / "runtime_state.json")
    skipped = {item["search"] for item in runtime.get("skipped_searches", [])}
    rows_by_id = {row["id"]: row for row in manifest["coordinates"]}
    coordinate_status: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    searches_out: list[dict[str, Any]] = []
    waves = []
    for wave in plan.get("wave_counts", {}):
        searches = [item for item in plan["searches"] if item["wave"] == wave]
        wave_counts = {"complete": 0, "running": 0, "not-started": 0,
                       "failed": 0, "pruned": 0}
        for item in searches:
            search_dir = root / item["path"]
            state = _read_json(search_dir / "search_state.json")
            if item["path"] in skipped:
                status = "pruned"
            else:
                status = str(state.get("status", "not-started"))
                if status not in wave_counts:
                    status = "failed" if status in {
                        "error", "blocked", "geometry-rejected"} else "not-started"
            wave_counts[status] += 1
            records = state.get("candidates", [])
            complete_count = 0
            best_score = None
            newest = 0.0
            for identifier in item["coordinate_ids"]:
                row = rows_by_id[identifier]
                matches = [record for record in records
                           if _same_values(record.get("values", {}), row)]
                record = matches[0] if len(matches) == 1 else None
                row_status = (str(record.get("status")) if record else
                              status.replace("not-started", "planned"))
                coordinate_status[identifier] = row_status
                if record and record.get("status") == "complete":
                    complete_count += 1
                    newest = max(newest, float(record.get("completed_at_unix", 0.0)))
                    score = ((record.get("surface_diagnostics", {}).get("score") or {})
                             .get("overall_percent"))
                    if isinstance(score, (int, float)):
                        best_score = max(best_score, float(score)) if best_score else float(score)
                    report_file = record.get("report_file")
                    candidates.append(_candidate(
                        row, record,
                        f"{item['path']}/{report_file}" if report_file else None))
            searches_out.append({
                **item, "status": status, "complete_count": complete_count,
                "best_score": best_score, "date_unix": newest,
            })
        waves.append({
            "wave": wave,
            "searches": plan["wave_counts"][wave]["searches"],
            "candidates": plan["wave_counts"][wave]["candidates"],
            "complete": wave_counts["complete"], "running": wave_counts["running"],
            "not_started": wave_counts["not-started"],
            "failed": wave_counts["failed"], "pruned": wave_counts["pruned"],
        })
    source_root = (root / manifest["source_evidence_root"]).resolve()
    for row in manifest["coordinates"]:
        if row["kind"] != "reference-anchor":
            continue
        reused = row["reused_from"]
        state = _read_json(source_root / reused["search"] / "search_state.json")
        matches = [record for record in state.get("candidates", [])
                   if str(record.get("id")) == reused["candidate_id"]]
        record = matches[0] if len(matches) == 1 else None
        report = (f"../mouth-size-coverage-grid/{reused['search']}/"
                  f"{record.get('report_file')}" if record and record.get("report_file")
                  else None)
        candidates.append(_candidate(
            row, record, report, float(reused["score"])))
        coordinate_status[row["id"]] = "reused"
    return {
        "manifest_sha256": _digest(manifest), "runtime": runtime,
        "coordinate_status": coordinate_status, "waves": waves,
        "searches": searches_out,
        "candidates": sorted(candidates, key=lambda item: (
            item["score"] is not None, item["score"] or -math.inf), reverse=True),
    }


def _number(value: Any, digits: int = 1, suffix: str = "") -> str:
    return (f"{float(value):.{digits}f}{suffix}"
            if isinstance(value, (int, float)) and math.isfinite(value) else "—")


def _date(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%-m-%-d %H:%M") if value else "—"


def _sort(value: Any) -> str:
    return str(value) if isinstance(value, (int, float)) and math.isfinite(value) else ""


def render_index(manifest: dict[str, Any], progress: dict[str, Any]) -> str:
    counts = manifest["status_counts"]
    runtime = progress.get("runtime", {})
    candidates = progress["candidates"]
    scored = sum(item["score"] is not None for item in candidates)
    completed_new = sum(item["complete_count"] for item in progress["searches"])
    running = sum(item["status"] == "running" for item in progress["searches"])
    wave_rows = "".join(
        f"<tr><td>{html.escape(row['wave'])}</td><td data-sort='{row['searches']}'>{row['searches']}</td>"
        f"<td data-sort='{row['candidates']}'>{row['candidates']}</td>"
        f"<td>{row['complete']}</td><td>{row['running']}</td>"
        f"<td>{row['not_started']}</td><td>{row['failed']}</td><td>{row['pruned']}</td></tr>"
        for row in progress["waves"])
    candidate_rows = []
    for item in candidates:
        label = (f"<a href='{html.escape(item['report'])}'>{html.escape(item['id'])}</a>"
                 if item["report"] else html.escape(item["id"]))
        candidate_rows.append(
            f"<tr data-coverage-angle='{item['coverage_deg']}'>"
            f"<td>{label}</td><td data-sort='{_sort(item['score'])}'>{_number(item['score'])}</td>"
            f"<td data-sort='{item['date_unix']}'>{_date(item['date_unix'])}</td>"
            f"<td>{item['coverage_deg']}°</td><td>{item['mouth_mm']} mm</td>"
            f"<td data-column='length' data-sort='{item['length_mm']}'>{item['length_mm']:.1f}</td>"
            f"<td data-column='ratio' data-sort='{item['length_mouth_ratio']:.8f}'>{item['length_mouth_ratio']:.3f}</td>"
            f"<td data-column='s' data-sort='{_sort(item['s'])}'>{_number(item['s'],2)}</td>"
            f"<td data-column='k' data-sort='{item['k']}'>{item['k']:g}</td>"
            f"<td data-column='n' data-sort='{item['n']}'>{item['n']:g}</td>"
            f"<td data-column='containment' hidden data-sort='{_sort(item['containment'])}'>{_number(item['containment']*100 if item['containment'] is not None else None,1,'%')}</td>"
            f"<td data-column='profile' hidden data-sort='{_sort(item['profile_rms'])}'>{_number(item['profile_rms'],3)}</td>"
            f"<td data-column='slice' hidden data-sort='{_sort(item['slice_rms'])}'>{_number(item['slice_rms'],3)}</td>"
            f"<td data-column='outward' hidden data-sort='{_sort(item['outward_rise'])}'>{_number(item['outward_rise'],3)}</td>"
            f"<td data-column='minus-six' hidden data-sort='{_sort(item['minus_six_rms'])}'>{_number(item['minus_six_rms'],2)}</td></tr>")
    search_rows = []
    for item in progress["searches"]:
        status_class = ("complete" if item["status"] == "complete" else
                        "running" if item["status"] == "running" else
                        "failed" if item["status"] == "failed" else "pending")
        search_rows.append(
            f"<tr data-subsearch-coverage-angle='{item['coverage_deg']}'>"
            f"<td>{html.escape(item['wave'])}</td><td>{item['coverage_deg']}°</td>"
            f"<td>{item['mouth_mm']} mm</td><td><span class='badge {status_class}'>{html.escape(item['status'])}</span></td>"
            f"<td data-sort='{item['date_unix']}'>{_date(item['date_unix'])}</td>"
            f"<td data-sort='{item['complete_count']}'>{item['complete_count']} / {item['candidate_count']}</td>"
            f"<td data-sort='{_sort(item['best_score'])}'>{_number(item['best_score'])}</td>"
            f"<td><a href='{html.escape(item['path'])}/search_report.html'>report</a></td></tr>")
    grid = []
    for mouth in manifest["domain"]["mouth_mm"]:
        cells = []
        for angle in manifest["domain"]["coverage_deg"]:
            cell = [row for row in manifest["coordinates"]
                    if row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
            ref = next(row for row in cell if row["kind"] == "reference-anchor")
            valid = [row for row in cell if isinstance(row.get("s"), (int, float))]
            measured = [item for item in candidates if item["coverage_deg"] == angle and
                        item["mouth_mm"] == mouth and item["score"] is not None]
            best = max(measured, key=lambda item: item["score"]) if measured else None
            best_text = _number(best["score"]) if best else "—"
            cells.append(
                f"<td class='design-cell'><strong class='design-score'>{best_text}</strong>"
                f"<span>{sum(row['status']=='planned' for row in cell)} required · "
                f"{sum(row['status']=='conditional' for row in cell)} conditional · "
                f"{sum(row['status']=='geometry-rejected' for row in cell)} rejected</span>"
                f"<span>Reference L {ref['length_mm']:.1f} · S {ref['s']:.2f}</span>"
                f"<span>Registered S {_number(min(row['s'] for row in valid),2)}–{_number(max(row['s'] for row in valid),2)}</span></td>")
        grid.append(f"<tr><th>{mouth} mm</th>{''.join(cells)}</tr>")
    plot_points = [{key: row.get(key) for key in (
        "id", "coverage_deg", "mouth_mm", "length_factor", "k", "n", "s", "status")}
        for row in manifest["coordinates"] if isinstance(row.get("s"), (int, float))]
    angles = manifest["domain"]["coverage_deg"]
    angle_buttons = "".join(
        f"<button class='angle-filter' data-angle-filter='{angle}' aria-pressed='false'>{angle}°</button>"
        for angle in angles)
    subsearch_buttons = "".join(
        f"<button class='angle-filter' data-subsearch-angle-filter='{angle}' aria-pressed='false'>{angle}°</button>"
        for angle in angles)
    matrix_buttons = []
    for mouth in manifest["domain"]["mouth_mm"]:
        buttons = "".join(
            f"<td><button class='sampling-cell' data-sampling-key='{mouth}:{angle}'><strong>{mouth} / {angle}°</strong><span>registered coordinates</span></button></td>"
            for angle in angles)
        matrix_buttons.append(f"<tr><th>{mouth} mm</th>{buttons}</tr>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Round-horn control decoupling</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#69d6c8;--good:#16856b;--warn:#b7791f;--bad:#b45353}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}h1,h2,h3{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-bottom:4px}}.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.9rem;text-transform:uppercase}}.badge.complete{{background:rgba(22,133,107,.18);color:#8de8cc}}.badge.running{{background:rgba(183,121,31,.2);color:#f6d39a}}.badge.failed{{background:rgba(180,83,83,.2);color:#ffb2b2}}.badge.pending{{background:rgba(148,163,189,.16);color:#c8d0d8}}.muted{{color:var(--muted)}}.sortable{{cursor:pointer;user-select:none}}[hidden]{{display:none!important}}.column-controls,.angle-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 12px}}.column-toggle,.angle-filter{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true'],.angle-filter[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}.show-more{{display:block;margin:14px auto 2px;border:1px solid var(--accent);border-radius:999px;padding:8px 16px;background:#173c39;color:var(--ink);cursor:pointer}}.design-map{{table-layout:fixed;min-width:1000px}}.design-cell{{min-width:150px;background:#17212a;border:1px solid var(--line)}}.design-cell>span{{display:block;margin-top:4px;font-size:.8rem;color:#c1cbd2;white-space:nowrap}}.design-score{{font-size:1.45rem}}.sampling-matrix{{table-layout:fixed;min-width:1000px}}.sampling-matrix td{{padding:3px}}.sampling-cell{{width:100%;border:1px solid transparent;border-radius:6px;padding:7px;background:#17212a;color:var(--ink);text-align:left;cursor:pointer}}.sampling-cell.active{{border-color:var(--accent);background:#173c39}}.sampling-cell strong,.sampling-cell span{{display:block}}.sampling-cell span{{color:var(--muted);font-size:.78rem}}.sampling-canvas{{display:block;width:100%;height:520px;touch-action:none;cursor:grab}}.sampling-canvas.wheel-active{{outline:1px solid var(--accent);outline-offset:-1px}}code{{overflow-wrap:anywhere}}@media(max-width:900px){{.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main><h1>Round-horn control decoupling</h1>
<p>Canonical symmetric round-horn study: physical length, K, and N are controlled; S is derived.</p>
<p class='muted'>No stale Phase 1–4 queue is included. Historical K4/N10 results appear only as explicit reusable references.</p>
<section class='summary'><div class='card'><strong>{completed_new} / {counts.get('planned',0)}</strong>new BEM complete</div><div class='card'><strong>{running}</strong>running searches</div><div class='card'><strong>{scored}</strong>scored candidates</div><div class='card'><strong>{runtime.get('status','not launched')}</strong>study status</div></section>
<section><h2>Project range</h2><table><tr><th>Coverage half-angles</th><th>Mouths</th><th>Length factors</th><th>K</th><th>N</th><th>Registered / required / conditional</th></tr><tr><td>{', '.join(map(str,angles))}°</td><td>{', '.join(map(str,manifest['domain']['mouth_mm']))} mm</td><td>{' / '.join(f'{x:.2f}' for x in manifest['fixed_design']['length_factors'])}<br>{' / '.join(f'{x:.2f}' for x in manifest['fixed_design']['boundary_length_factors'])} sentinels</td><td>{' / '.join(f'{x:g}' for x in manifest['fixed_design']['k_levels'])}</td><td>{' / '.join(f'{x:g}' for x in manifest['fixed_design']['n_levels'])}<br>K4/N10 reference; N2 closure only</td><td>{len(manifest['coordinates'])} / {counts.get('planned',0)} / {counts.get('conditional',0)}</td></tr></table><p class='muted'>Manifest SHA-256: <code>{progress['manifest_sha256']}</code></p></section>
<section><h2>Design map</h2><p class='muted'>Best measured score and the registered physical extent of each mouth/coverage cell.</p><table class='design-map'><thead><tr><th>Mouth / coverage</th>{''.join(f'<th>{a}°</th>' for a in angles)}</tr></thead><tbody>{''.join(grid)}</tbody></table></section>
<section><h2>Sampling extent</h2><p>Select a cell to inspect the actual registered L-factor/K/N cloud. Rejected geometries are excluded from the plot.</p><table class='sampling-matrix'><thead><tr><th>Cell</th>{''.join(f'<th>{a}°</th>' for a in angles)}</tr></thead><tbody>{''.join(matrix_buttons)}</tbody></table><h3 id='sampling-selection'></h3><canvas id='sampling-3d' class='sampling-canvas'></canvas><p class='muted'>Drag to rotate. Click the plot to enable wheel zoom; click elsewhere to release it. Axes are length factor, K, and N—S is not treated as an independent coordinate.</p></section>
<section><h2>Candidates</h2><div class='column-controls'>{''.join(f"<button class='column-toggle' data-column-toggle='{key}' aria-pressed='{str(visible).lower()}'>{label}</button>" for key,label,visible in [('length','Length',True),('ratio','L / mouth',True),('s','S',True),('k','K',True),('n','N',True),('containment','Containment',False),('profile','Profile RMS',False),('slice','Slice energy',False),('outward','Outward rise',False),('minus-six','−6 dB RMS',False)])}</div><div class='angle-controls'><button class='angle-filter' data-angle-filter='all' aria-pressed='true'>All angles</button>{angle_buttons}<span id='candidate-count' class='muted'></span></div><table id='candidate-table' class='sortable-table'><thead><tr><th data-sort='text'>Candidate</th><th data-sort='number'>Surface score</th><th data-sort='number'>Date</th><th data-sort='number'>Coverage</th><th data-sort='number'>Mouth</th><th data-column='length' data-sort='number'>Length mm</th><th data-column='ratio' data-sort='number'>L / mouth</th><th data-column='s' data-sort='number'>S</th><th data-column='k' data-sort='number'>K</th><th data-column='n' data-sort='number'>N</th><th data-column='containment' hidden data-sort='number'>Containment</th><th data-column='profile' hidden data-sort='number'>Profile RMS</th><th data-column='slice' hidden data-sort='number'>Slice energy</th><th data-column='outward' hidden data-sort='number'>Outward rise</th><th data-column='minus-six' hidden data-sort='number'>−6 dB RMS</th></tr></thead><tbody>{''.join(candidate_rows)}</tbody></table><button id='candidate-show-more' class='show-more'>Show 25 more</button></section>
<section><h2>Execution waves</h2><table class='sortable-table'><thead><tr><th data-sort='text'>Wave</th><th data-sort='number'>Searches</th><th data-sort='number'>Candidates</th><th data-sort='number'>Complete</th><th data-sort='number'>Running</th><th data-sort='number'>Not started</th><th data-sort='number'>Failed</th><th data-sort='number'>Pruned</th></tr></thead><tbody>{wave_rows}</tbody></table></section>
<section><h2>Sub-searches</h2><div class='angle-controls'><button class='angle-filter' data-subsearch-angle-filter='all' aria-pressed='true'>All angles</button>{subsearch_buttons}<span id='subsearch-count' class='muted'></span></div><table id='subsearch-table' class='sortable-table'><thead><tr><th data-sort='text'>Wave</th><th data-sort='number'>Coverage</th><th data-sort='number'>Mouth</th><th data-sort='text'>Status</th><th data-sort='number'>Date complete</th><th data-sort='number'>Complete / proposed</th><th data-sort='number'>Best score</th><th>Report</th></tr></thead><tbody>{''.join(search_rows)}</tbody></table></section>
<script>(()=>{{const points={json.dumps(plot_points,separators=(',',':'))};let key='350:40',yaw=-.65,pitch=.65,zoom=.82,drag=null,wheel=false;const canvas=document.getElementById('sampling-3d'),label=document.getElementById('sampling-selection');const cell=()=>{{const [m,a]=key.split(':').map(Number);return points.filter(p=>p.mouth_mm===m&&p.coverage_deg===a&&Number.isFinite(p.length_factor));}};function draw(){{const ps=cell();if(!ps.length)return;const ratio=devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=Math.round(r.width*ratio);canvas.height=Math.round(r.height*ratio);const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,r.width,r.height);const ranges=['length_factor','k','n'].map(name=>{{const v=ps.map(p=>p[name]),lo=Math.min(...v),hi=Math.max(...v),pad=Math.max((hi-lo)*.1,.08);return[lo-pad,hi+pad];}});const norm=p=>({{x:(p.length_factor-ranges[0][0])/(ranges[0][1]-ranges[0][0])*2-1,y:(p.k-ranges[1][0])/(ranges[1][1]-ranges[1][0])*2-1,z:(p.n-ranges[2][0])/(ranges[2][1]-ranges[2][0])*2-1,p}});const scale=Math.min(r.width,r.height)*.3*zoom;const project=v=>{{const x=v.x*Math.cos(yaw)-v.y*Math.sin(yaw),y=v.x*Math.sin(yaw)+v.y*Math.cos(yaw);return{{x:r.width/2+x*scale,y:r.height/2+(y*Math.cos(pitch)-v.z*Math.sin(pitch))*scale,d:y*Math.sin(pitch)+v.z*Math.cos(pitch),p:v.p}};}};const origin=project({{x:-1,y:-1,z:-1}});function axis(end,text){{end=project(end);c.strokeStyle='#536774';c.beginPath();c.moveTo(origin.x,origin.y);c.lineTo(end.x,end.y);c.stroke();c.fillStyle='#d7e2e8';c.font='12px system-ui';c.fillText(text,end.x+5,end.y-5);}}axis({{x:1,y:-1,z:-1}},'Length factor');axis({{x:-1,y:1,z:-1}},'K');axis({{x:-1,y:-1,z:1}},'N');ps.map(norm).map(project).sort((a,b)=>a.d-b.d).forEach(v=>{{c.beginPath();c.arc(v.x,v.y,4,0,Math.PI*2);c.fillStyle=v.p.status==='reused'?'#f6d39a':'#69d6c8';c.fill();c.strokeStyle='#071015';c.stroke();}});}}function render(){{const [m,a]=key.split(':');label.textContent=`${{m}} mm / ${{a}}° — ${{cell().length}} feasible registered coordinates`;document.querySelectorAll('[data-sampling-key]').forEach(b=>b.classList.toggle('active',b.dataset.samplingKey===key));draw();}}document.querySelectorAll('[data-sampling-key]').forEach(b=>b.onclick=()=>{{key=b.dataset.samplingKey;render();}});canvas.onpointerdown=e=>{{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);}};canvas.onpointermove=e=>{{if(!drag)return;yaw+=(e.clientX-drag[0])*.008;pitch=Math.max(.15,Math.min(1.3,pitch+(e.clientY-drag[1])*.006));drag=[e.clientX,e.clientY];draw();}};canvas.onpointerup=()=>drag=null;canvas.onclick=()=>{{wheel=true;canvas.classList.add('wheel-active');}};document.addEventListener('pointerdown',e=>{{if(!canvas.contains(e.target)){{wheel=false;canvas.classList.remove('wheel-active');}}}});canvas.addEventListener('wheel',e=>{{if(!wheel)return;e.preventDefault();zoom=Math.max(.55,Math.min(1.4,zoom-e.deltaY*.001));draw();}},{{passive:false}});addEventListener('resize',draw);
document.querySelectorAll('[data-column-toggle]').forEach(b=>b.onclick=()=>{{const on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',String(on));document.querySelectorAll(`[data-column="${{b.dataset.columnToggle}}"]`).forEach(x=>x.hidden=!on);}});const ct=document.getElementById('candidate-table'),more=document.getElementById('candidate-show-more'),cc=document.getElementById('candidate-count');let angle='all',limit=25;function candidates(){{let match=0,shown=0;Array.from(ct.tBodies[0].rows).forEach(r=>{{const ok=angle==='all'||r.dataset.coverageAngle===angle;if(ok)match++;r.hidden=!(ok&&shown++<limit);}});shown=Math.min(match,limit);cc.textContent=`Showing ${{shown}} of ${{match}}`;more.hidden=shown>=match;}}document.querySelectorAll('[data-angle-filter]').forEach(b=>b.onclick=()=>{{angle=b.dataset.angleFilter;limit=25;document.querySelectorAll('[data-angle-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));candidates();}});more.onclick=()=>{{limit+=25;candidates();}};const st=document.getElementById('subsearch-table'),sc=document.getElementById('subsearch-count');function subsearches(a='all'){{let n=0;Array.from(st.tBodies[0].rows).forEach(r=>{{r.hidden=!(a==='all'||r.dataset.subsearchCoverageAngle===a);if(!r.hidden)n++;}});sc.textContent=`${{n}} sub-searches`;}}document.querySelectorAll('[data-subsearch-angle-filter]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-subsearch-angle-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));subsearches(b.dataset.subsearchAngleFilter);}});document.querySelectorAll('table.sortable-table').forEach(table=>{{const hs=Array.from(table.querySelectorAll('th[data-sort]'));let active=-1,dir='desc';hs.forEach((h,i)=>h.onclick=()=>{{dir=active===i&&dir==='desc'?'asc':'desc';active=i;const mul=dir==='asc'?1:-1,rows=Array.from(table.tBodies[0].rows);rows.sort((a,b)=>{{let x=a.cells[i]?.dataset.sort??a.cells[i]?.textContent??'',y=b.cells[i]?.dataset.sort??b.cells[i]?.textContent??'';if(h.dataset.sort==='number'){{x=Number(x);y=Number(y);x=Number.isFinite(x)?x:-Infinity;y=Number.isFinite(y)?y:-Infinity;}}return(x<y?-1:x>y?1:0)*mul;}});table.tBodies[0].replaceChildren(...rows);candidates();}});}});render();candidates();subsearches();}})();</script></main></body></html>"""


def refresh_index(root: Path) -> None:
    manifest = _read_json(root / "manifest.json")
    plan = _read_json(root / "execution_plan.json")
    if not manifest:
        raise RuntimeError(f"missing manifest: {root}")
    if not plan:
        from .plan_control_decoupling_study import render_index as render_static
        output = render_static(manifest)
    else:
        output = render_index(manifest, build_progress(root, manifest, plan))
    (root / "index.html").write_text(output, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?",
                        default=Path("examples/control-decoupling"))
    args = parser.parse_args()
    refresh_index(args.root)


if __name__ == "__main__":
    main()
