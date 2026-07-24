#!/usr/bin/env python3
"""Build the standalone surface-score v1/v2 rank comparison viewer."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from .interactive_results import load_run
from .surface_diagnostics import surface_diagnostics, surface_score_v2


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "examples/control-decoupling/model_source/training_index.json"
DEFAULT_OUTPUT = ROOT / "examples/surface-score-v1-v2-rank-comparison"
SCORE_TOLERANCE = 1e-8
HEATMAP_FLOOR_DB = -30.0
HEATMAP_STEP_DB = 0.25


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _relative_link(target: Path, output: Path) -> str:
    return Path(os.path.relpath(target, output)).as_posix()


def _candidate_report(response: Path) -> Path | None:
    matches = sorted(response.parent.glob("*_Report.html"))
    return matches[0] if matches else None


def _evaluation_grid(run: dict[str, Any]) -> np.ndarray:
    crossover = float(run["crossover_hz"])
    upper = float(run["frequencies"][-1])
    count = int(math.ceil(math.log2(upper / crossover) * 48)) + 1
    return np.geomspace(crossover, upper, count)


def _grid_id(frequencies: np.ndarray, angles: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.asarray(frequencies, dtype="<f8").tobytes())
    digest.update(np.asarray(angles, dtype="<f8").tobytes())
    return digest.hexdigest()[:16]


def _encode_heatmap(surface: np.ndarray) -> str:
    clipped = np.clip(np.asarray(surface, dtype=float), HEATMAP_FLOOR_DB, 0.0)
    quantized = np.rint(
        (clipped - HEATMAP_FLOOR_DB) / HEATMAP_STEP_DB
    ).astype(np.uint8)
    return base64.b64encode(quantized.tobytes(order="C")).decode("ascii")


def _deduplicate_rows(index: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in index["rows"]:
        response_hash = row.get("response_sha256")
        source = root / row.get("source_path", "")
        if response_hash and source.is_file():
            by_hash.setdefault(response_hash, []).append(row)
    rows = []
    for response_hash, aliases in sorted(by_hash.items()):
        representative = min(aliases, key=lambda row: row["id"])
        rows.append({
            **representative,
            "response_sha256": response_hash,
            "aliases": sorted(row["id"] for row in aliases),
        })
    return rows


def _score_candidate(
    row: dict[str, Any],
    root: Path,
    output: Path,
    grids: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    response = root / row["source_path"]
    run = load_run(response.parent)
    diagnostics = surface_diagnostics(
        run, _evaluation_grid(run), fixed_band=True
    )
    if diagnostics.get("status") != "available":
        raise ValueError(f"{row['id']}: surface diagnostics unavailable")
    score_v1 = float(diagnostics["score_v1"]["overall_percent"])
    indexed_v1 = float(row["responses"]["surface_score"])
    delta = abs(score_v1 - indexed_v1)
    if delta > SCORE_TOLERANCE:
        raise ValueError(
            f"{row['id']}: recalculated v1 differs by {delta:g}"
        )
    score_v2 = float(surface_score_v2(
        diagnostics,
        run.get("mouth_dimensions_mm"),
        candidate_name="contour_forward",
        adapt_narrow_coverage=False,
    )["overall_percent"])

    frequencies = np.asarray(run["frequencies"], dtype=float)
    all_angles = np.asarray(run["angles"], dtype=float)
    positive = all_angles >= 0
    order = np.argsort(all_angles[positive])
    angles = all_angles[positive][order]
    frequency_order = np.argsort(frequencies)
    frequencies = frequencies[frequency_order]
    surface = np.asarray(run["horizontal"], dtype=float)[frequency_order][:, positive]
    surface = surface[:, order]
    grid_id = _grid_id(frequencies, angles)
    grids.setdefault(grid_id, {
        "frequencies_hz": frequencies.tolist(),
        "angles_deg": angles.tolist(),
        "rows": int(surface.shape[0]),
        "columns": int(surface.shape[1]),
    })
    report = _candidate_report(response)
    return {
        "id": row["id"],
        "aliases": row["aliases"],
        "response_sha256": row["response_sha256"],
        "source_path": row["source_path"],
        "report_link": _relative_link(report, output) if report else None,
        "provenance": row.get("provenance"),
        "role": row.get("role"),
        "mouth_mm": float(row["mouth_mm"]),
        "coverage_deg": float(row["coverage_deg"]),
        "length_mm": float(row["length_mm"]),
        "k": float(row["k"]),
        "n": float(row["n"]),
        "s": float(row["derived_s"]),
        "score_v1": score_v1,
        "score_v2": score_v2,
        "indexed_v1_delta": delta,
        "grid_id": grid_id,
        "heatmap_b64": _encode_heatmap(surface),
    }


def assemble(
    index_path: Path = DEFAULT_INDEX,
    output: Path = DEFAULT_OUTPUT,
    *,
    maximum_evidence: int | None = None,
) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows = _deduplicate_rows(index, ROOT)
    if maximum_evidence is not None:
        rows = rows[:maximum_evidence]
    grids: dict[str, dict[str, Any]] = {}
    candidates = [
        _score_candidate(row, ROOT, output, grids)
        for row in rows
    ]
    candidates.sort(key=lambda row: row["id"])
    response_hashes = [row["response_sha256"] for row in candidates]
    if len(response_hashes) != len(set(response_hashes)):
        raise ValueError("exact-response deduplication failed")
    artifact = {
        "schema_version": 1,
        "study_id": "surface-score-v1-v2-rank-comparison",
        "status": "complete",
        "source_index": str(index_path.relative_to(ROOT)),
        "source_index_sha256": _file_hash(index_path),
        "diagnostic_implementation_sha256": _file_hash(
            ROOT / "app/tools/surface_diagnostics.py"
        ),
        "deduplication": "response_sha256",
        "population_count": len(candidates),
        "top_rank_count": 25,
        "quantiles": [0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99],
        "heatmap_encoding": {
            "floor_db": HEATMAP_FLOOR_DB,
            "step_db": HEATMAP_STEP_DB,
            "dtype": "uint8",
            "order": "frequency-major row-major",
        },
        "grids": grids,
        "candidates": candidates,
    }
    artifact["content_sha256"] = _content_hash(artifact)
    return artifact


def _document(artifact: dict[str, Any]) -> str:
    payload = json.dumps(
        artifact, sort_keys=True, separators=(",", ":")
    ).replace("</", "<\\/")
    count = artifact["population_count"]
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Surface score v1 / v2 rank comparison</title>
<style>
:root{{--bg:#0b1015;--panel:#121a22;--panel2:#17222c;--ink:#e8f0f4;--muted:#9badb8;--line:#2b3a46;--v1:#79c5ff;--v2:#ffb45e;--accent:#69d6c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:18px}}h1{{font-size:1.55rem;margin:0 0 5px}}p{{margin:6px 0}}.muted{{color:var(--muted)}}.controls,.filters,.rank-strip,.quantiles{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.filters{{margin:14px 0}}label{{color:var(--muted)}}select,button{{border:1px solid var(--line);background:var(--panel2);color:var(--ink);border-radius:8px;padding:7px 10px;font:inherit}}button{{cursor:pointer}}button:hover,button:focus-visible,button.active{{border-color:var(--accent);outline:none}}button:disabled{{opacity:.35;cursor:default}}.rank-strip{{margin:10px 0}}.rank-strip button{{min-width:34px;padding:5px}}.viewer{{position:relative;border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden;user-select:none;touch-action:none}}canvas{{display:block;width:100%;height:min(67vh,720px)}}.hold-label{{position:absolute;left:14px;top:12px;background:#071018dd;border:1px solid var(--line);border-radius:999px;padding:5px 10px;pointer-events:none}}.hold-label.v1{{color:var(--v1)}}.hold-label.v2{{color:var(--v2)}}.meta-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}}.card.v1{{border-top:3px solid var(--v1)}}.card.v2{{border-top:3px solid var(--v2)}}.card h2{{font-size:1rem;margin:0 0 7px}}.score{{font-size:1.65rem;font-weight:700}}a{{color:var(--accent)}}code{{overflow-wrap:anywhere}}.legend{{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0;color:var(--muted)}}.swatch{{display:inline-block;width:16px;height:3px;vertical-align:middle;margin-right:5px}}.preference{{margin:12px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.preference h2{{font-size:1rem;margin:0 0 9px}}.preference-buttons{{display:flex;gap:8px;flex-wrap:wrap}}.preference-buttons button{{flex:1;min-width:150px}}.preference-buttons button.selected{{border-color:var(--accent);background:#173c39}}textarea{{width:100%;min-height:70px;margin-top:9px;padding:8px;border:1px solid var(--line);border-radius:8px;background:#0d151d;color:var(--ink);font:inherit;resize:vertical}}.record-tools{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:9px}}@media(max-width:720px){{.meta-grid{{grid-template-columns:1fr}}canvas{{height:55vh}}}}
</style></head><body><main>
<h1>Surface score v1 / v2 rank comparison</h1>
<p class="muted">{count} unique retained round-horn responses. Rankings are independent within the selected mouth/coverage population.</p>
<div class="filters">
<label>Mouth <select id="mouth"><option value="">All</option></select></label>
<label>Coverage <select id="coverage"><option value="">All</option></select></label>
<span id="population" class="muted"></span>
</div>
<div class="controls">
<button id="higher" type="button">↑ Higher rank</button>
<strong id="rank-label"></strong>
<button id="lower" type="button">↓ Lower rank</button>
</div>
<div id="rank-strip" class="rank-strip"></div>
<div class="quantiles"><span class="muted">Quantiles:</span><span id="quantile-buttons"></span></div>
<p><strong>Press and hold the plot for v2; release for v1.</strong> Arrow keys also change rank. Space temporarily shows v2.</p>
<div id="viewer" class="viewer" tabindex="0" aria-label="Press and hold to compare v2">
<canvas id="plot"></canvas><div id="hold-label" class="hold-label v1">v1</div>
</div>
<div class="legend"><span><i class="swatch" style="background:#69d6c8"></i>Intended coverage</span><span><i class="swatch" style="background:#7fe7ff"></i>−3 dB</span><span><i class="swatch" style="background:#fff"></i>−6 dB</span><span><i class="swatch" style="background:#ffad5c"></i>−9 dB</span></div>
<section class="preference"><h2>Which plot is better?</h2>
<div class="preference-buttons">
<button type="button" data-choice="plot_1">1 · Default plot better</button>
<button type="button" data-choice="tie">Tie / too close</button>
<button type="button" data-choice="plot_2">2 · Hold plot better</button>
</div>
<textarea id="preference-note" placeholder="Optional note for this comparison"></textarea>
<div class="record-tools"><strong id="selection-status">Not ranked</strong>
<span id="selection-summary" class="muted"></span>
<button id="export-selections" type="button">Export selections JSON</button>
<button id="import-selections" type="button">Import selections JSON</button>
<input id="selection-file" type="file" accept="application/json" hidden></div>
<p class="muted">Shortcuts: 1 = default plot, 0 = tie, 2 = hold plot. Selections autosave in this browser.</p></section>
<div class="meta-grid"><section id="v1-card" class="card v1"></section><section id="v2-card" class="card v2"></section></div>
<p class="muted">Exact-response deduplication: SHA-256. Heat maps are stored at 0.25 dB resolution from −30 to 0 dB. Content hash: <code>{html.escape(artifact["content_sha256"])}</code>.</p>
</main><script id="comparison-data" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById("comparison-data").textContent);
const byId=new Map(data.candidates.map(x=>[x.id,x]));
const grids=data.grids, encoding=data.heatmap_encoding;
let filtered=[],rank=1,held=false,spaceHeld=false;
const storageKey=`surface-score-comparison:${{data.content_sha256}}`;
let record=JSON.parse(localStorage.getItem(storageKey)||"null")||{{schema_version:1,experiment_id:data.study_id,artifact_content_sha256:data.content_sha256,selections:{{}}}};
const canvas=document.getElementById("plot"),ctx=canvas.getContext("2d");
const viewer=document.getElementById("viewer"),holdLabel=document.getElementById("hold-label");
const mouth=document.getElementById("mouth"),coverage=document.getElementById("coverage");
const unique=key=>[...new Set(data.candidates.map(x=>x[key]))].sort((a,b)=>a-b);
for(const value of unique("mouth_mm")) mouth.add(new Option(`${{value}} mm`,value));
for(const value of unique("coverage_deg")) coverage.add(new Option(`${{value}}°`,value));
function rankings(){{
 const sortBy=key=>[...filtered].sort((a,b)=>b[key]-a[key]||a.id.localeCompare(b.id));
 return {{v1:sortBy("score_v1"),v2:sortBy("score_v2")}};
}}
function applyFilter(){{
 filtered=data.candidates.filter(x=>(!mouth.value||x.mouth_mm===+mouth.value)&&(!coverage.value||x.coverage_deg===+coverage.value));
 rank=1; rebuildButtons(); render();
}}
function topLimit(){{return Math.min(data.top_rank_count,filtered.length)}}
function currentPair(){{
 if(!filtered.length)return null;
 const lists=rankings(),a=lists.v1[rank-1],b=lists.v2[rank-1];
 const mouthFilter=mouth.value||"all",coverageFilter=coverage.value||"all";
 const key=[mouthFilter,coverageFilter,rank,a.response_sha256,b.response_sha256].join("|");
 return {{key,a,b,mouth_filter:mouthFilter,coverage_filter:coverageFilter}};
}}
function saveRecord(){{
 record.updated_at=new Date().toISOString();
 localStorage.setItem(storageKey,JSON.stringify(record));
 renderPreference();
}}
function renderPreference(){{
 const pair=currentPair(),selection=pair?record.selections[pair.key]:null;
 document.querySelectorAll("[data-choice]").forEach(button=>button.classList.toggle("selected",selection?.choice===button.dataset.choice));
 document.getElementById("preference-note").value=selection?.note||"";
 document.getElementById("selection-status").textContent=selection?.choice?`Recorded: ${{selection.choice.replace("plot_1","plot 1").replace("plot_2","plot 2")}}`:"Not ranked";
 const decided=Object.values(record.selections).filter(value=>["plot_1","plot_2","tie"].includes(value.choice)).length;
 document.getElementById("selection-summary").textContent=`${{decided}} recorded comparison${{decided===1?"":"s"}}`;
}}
function choose(choice){{
 const pair=currentPair();if(!pair)return;
 const prior=record.selections[pair.key]||{{}};
 record.selections[pair.key]={{...prior,choice,note:document.getElementById("preference-note").value,filter:{{mouth_mm:pair.mouth_filter,coverage_deg:pair.coverage_filter}},rank,plot_1:{{score_version:"v1",id:pair.a.id,response_sha256:pair.a.response_sha256,score:pair.a.score_v1}},plot_2:{{score_version:"v2",id:pair.b.id,response_sha256:pair.b.response_sha256,score:pair.b.score_v2}},recorded_at:new Date().toISOString()}};
 saveRecord();
}}
function rebuildButtons(){{
 const strip=document.getElementById("rank-strip");strip.textContent="";
 for(let n=1;n<=topLimit();n++){{const b=document.createElement("button");b.textContent=n;b.onclick=()=>{{rank=n;render()}};strip.append(b)}}
 const qroot=document.getElementById("quantile-buttons");qroot.textContent="";
 for(const q of data.quantiles){{const b=document.createElement("button");b.textContent=`${{Math.round(q*100)}}%`;b.onclick=()=>{{rank=Math.max(1,Math.round(q*(filtered.length-1))+1);render()}};qroot.append(b)}}
}}
function decode(candidate){{
 const binary=atob(candidate.heatmap_b64),values=new Uint8Array(binary.length);
 for(let i=0;i<binary.length;i++)values[i]=binary.charCodeAt(i);
 return values;
}}
const stops=[[0,[9,19,36]],[.22,[41,72,111]],[.45,[30,145,151]],[.68,[118,190,116]],[.84,[239,199,78]],[1,[250,245,225]]];
function color(t){{t=Math.max(0,Math.min(1,t));let a=stops[0],b=stops.at(-1);for(let i=1;i<stops.length;i++)if(t<=stops[i][0]){{a=stops[i-1];b=stops[i];break}}const u=(t-a[0])/(b[0]-a[0]||1);return `rgb(${{a[1].map((v,i)=>Math.round(v+u*(b[1][i]-v))).join(",")}})`}}
function contour(values,grid,level,x0,y0,w,h){{
 const target=Math.round((level-encoding.floor_db)/encoding.step_db),points=[];
 for(let r=0;r<grid.rows;r++){{let crossing=null;for(let c=1;c<grid.columns;c++){{const a=values[r*grid.columns+c-1],b=values[r*grid.columns+c];if(a>=target&&b<target){{const u=(target-a)/(b-a);crossing=(c-1+u)/(grid.columns-1);break}}}}if(crossing!==null)points.push([x0+r/(grid.rows-1)*w,y0+(1-crossing)*h]);}}
 if(points.length<2)return;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();
}}
function draw(candidate,version){{
 const dpr=devicePixelRatio||1,rect=canvas.getBoundingClientRect();canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
 const W=rect.width,H=rect.height,pad={{l:67,r:24,t:42,b:54}},x0=pad.l,y0=pad.t,w=W-pad.l-pad.r,h=H-pad.t-pad.b;
 ctx.fillStyle="#0d151d";ctx.fillRect(0,0,W,H);const grid=grids[candidate.grid_id],values=decode(candidate);
 const image=document.createElement("canvas");image.width=grid.rows;image.height=grid.columns;const ix=image.getContext("2d"),pixels=ix.createImageData(grid.rows,grid.columns);
 for(let r=0;r<grid.rows;r++)for(let c=0;c<grid.columns;c++){{const code=values[r*grid.columns+c],rgb=color(code/120),m=rgb.match(/\\d+/g),p=((grid.columns-1-c)*grid.rows+r)*4;pixels.data[p]=+m[0];pixels.data[p+1]=+m[1];pixels.data[p+2]=+m[2];pixels.data[p+3]=255}}ix.putImageData(pixels,0,0);ctx.imageSmoothingEnabled=true;ctx.drawImage(image,x0,y0,w,h);
 const maxAngle=grid.angles_deg.at(-1),targetY=y0+(1-candidate.coverage_deg/maxAngle)*h;
 ctx.save();ctx.strokeStyle="#69d6c8";ctx.lineWidth=2;ctx.setLineDash([8,6]);ctx.beginPath();ctx.moveTo(x0,targetY);ctx.lineTo(x0+w,targetY);ctx.stroke();ctx.restore();
 ctx.fillStyle="#b7fff3";ctx.font="600 12px system-ui";ctx.textAlign="right";ctx.fillText(`Intended ${{candidate.coverage_deg}}°`,x0+w-6,targetY-6);
 ctx.lineWidth=2.2;for(const [level,stroke] of [[-3,"#7fe7ff"],[-6,"#ffffff"],[-9,"#ffad5c"]]){{ctx.strokeStyle=stroke;contour(values,grid,level,x0,y0,w,h)}}
 ctx.strokeStyle="#67808f";ctx.lineWidth=1;ctx.strokeRect(x0,y0,w,h);ctx.fillStyle="#aab8c1";ctx.font="13px system-ui";ctx.textAlign="center";
 const freqs=grid.frequencies_hz;for(const f of [500,1000,2000,4000,8000])if(f>=freqs[0]&&f<=freqs.at(-1)){{const x=x0+(Math.log(f)-Math.log(freqs[0]))/(Math.log(freqs.at(-1))-Math.log(freqs[0]))*w;ctx.fillText(f>=1000?`${{f/1000}}k`:f,x,y0+h+22)}}
 ctx.fillText("Frequency (Hz)",x0+w/2,H-9);ctx.save();ctx.translate(17,y0+h/2);ctx.rotate(-Math.PI/2);ctx.fillText("Half-angle (degrees)",0,0);ctx.restore();ctx.textAlign="right";
 for(const a of [0,15,30,45,60,75,90])if(a<=maxAngle)ctx.fillText(a+"°",x0-8,y0+(1-a/maxAngle)*h+4);
 ctx.textAlign="left";ctx.fillStyle=version==="v1"?"#79c5ff":"#ffb45e";ctx.font="600 16px system-ui";ctx.fillText(`${{version.toUpperCase()}} rank ${{rank}} · ${{candidate.id}}`,x0,y0-15);
}}
function card(candidate,version){{
 const score=candidate[`score_${{version}}`],other=candidate[`score_${{version==="v1"?"v2":"v1"}}`];
 return `<h2>${{version.toUpperCase()}} rank ${{rank}}</h2><div class="score">${{score.toFixed(1)}}%</div><p><strong>${{candidate.id}}</strong></p><p>${{candidate.mouth_mm}} mm · ${{candidate.coverage_deg}}° · L ${{candidate.length_mm.toFixed(3)}} · K ${{candidate.k}} · N ${{candidate.n}} · S ${{candidate.s.toFixed(4)}}</p><p class="muted">${{candidate.provenance}} · ${{candidate.role}} · other score ${{other.toFixed(1)}}%</p>${{candidate.report_link?`<a href="${{candidate.report_link}}">Open candidate report</a>`:""}}`;
}}
function render(){{
 if(!filtered.length){{ctx.clearRect(0,0,canvas.width,canvas.height);document.getElementById("population").textContent="No evidence";return}}
 rank=Math.max(1,Math.min(rank,filtered.length));const lists=rankings(),a=lists.v1[rank-1],b=lists.v2[rank-1],showV2=held||spaceHeld;
 draw(showV2?b:a,showV2?"v2":"v1");holdLabel.textContent=showV2?"v2 · release for v1":"v1 · hold for v2";holdLabel.className=`hold-label ${{showV2?"v2":"v1"}}`;
 document.getElementById("v1-card").innerHTML=card(a,"v1");document.getElementById("v2-card").innerHTML=card(b,"v2");
 document.getElementById("rank-label").textContent=`Rank ${{rank}} of ${{filtered.length}}`;document.getElementById("population").textContent=`${{filtered.length}} unique responses`;
 document.getElementById("higher").disabled=rank===1;document.getElementById("lower").disabled=rank===filtered.length;
 [...document.querySelectorAll("#rank-strip button")].forEach((b,i)=>b.classList.toggle("active",i+1===rank));
 renderPreference();
}}
function hold(value){{held=value;render()}}
viewer.addEventListener("pointerdown",e=>{{viewer.setPointerCapture(e.pointerId);hold(true)}});
viewer.addEventListener("pointerup",()=>hold(false));viewer.addEventListener("pointercancel",()=>hold(false));viewer.addEventListener("lostpointercapture",()=>{{if(held)hold(false)}});
document.getElementById("higher").onclick=()=>{{rank--;render()}};document.getElementById("lower").onclick=()=>{{rank++;render()}};
for(const select of [mouth,coverage])select.onchange=applyFilter;
document.querySelectorAll("[data-choice]").forEach(button=>button.onclick=()=>choose(button.dataset.choice));
document.getElementById("preference-note").addEventListener("change",event=>{{const pair=currentPair();if(!pair)return;const prior=record.selections[pair.key];if(prior){{prior.note=event.target.value;saveRecord()}}}});
document.getElementById("export-selections").onclick=()=>{{const blob=new Blob([JSON.stringify(record,null,2)+"\\n"],{{type:"application/json"}}),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="surface_score_v1_v2_selections.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}};
document.getElementById("import-selections").onclick=()=>document.getElementById("selection-file").click();
document.getElementById("selection-file").onchange=async event=>{{const file=event.target.files[0];if(!file)return;const imported=JSON.parse(await file.text());if(imported.artifact_content_sha256!==data.content_sha256){{alert("Selection file belongs to a different comparison artifact.");return}}record=imported;saveRecord();event.target.value=""}};
addEventListener("keydown",e=>{{if((e.target.tagName==="TEXTAREA"||e.target.tagName==="INPUT")&&e.key!=="Escape")return;if(e.key==="1"){{choose("plot_1");e.preventDefault()}}else if(e.key==="0"){{choose("tie");e.preventDefault()}}else if(e.key==="2"){{choose("plot_2");e.preventDefault()}}else if(e.key==="ArrowUp"||e.key==="ArrowLeft"){{rank--;render();e.preventDefault()}}else if(e.key==="ArrowDown"||e.key==="ArrowRight"){{rank++;render();e.preventDefault()}}else if(e.code==="Space"&&!spaceHeld){{spaceHeld=true;render();e.preventDefault()}}else if(e.key==="Escape"){{held=spaceHeld=false;render()}}}});
addEventListener("keyup",e=>{{if(e.code==="Space"){{spaceHeld=false;render();e.preventDefault()}}}});addEventListener("blur",()=>{{held=spaceHeld=false;render()}});addEventListener("resize",render);
applyFilter();
</script></body></html>"""


def write(output: Path, artifact: dict[str, Any]) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "comparison.json"
    html_path = output / "index.html"
    json_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(_document(artifact), encoding="utf-8")
    return json_path, html_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--maximum-evidence", type=int)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="rebuild HTML from the existing comparison JSON without rescoring NPZ",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.render_only:
        artifact = json.loads(
            (args.output / "comparison.json").read_text(encoding="utf-8")
        )
    else:
        artifact = assemble(
            args.index, args.output, maximum_evidence=args.maximum_evidence
        )
    _, report = write(args.output, artifact)
    print(report)


if __name__ == "__main__":
    main()
