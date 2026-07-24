#!/usr/bin/env python3
"""Build a blinded per-cell ranking game for surface score v1 versus v2.2."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from .report_round_control_parameter_maps import COVERAGES, MOUTHS
from .report_round_control_parameter_maps_v2_1 import (
    DEFAULT_RIDGE_RESULTS,
    DEFAULT_SOURCE,
    _ridge_candidates,
)
from .surface_diagnostics import surface_score_v2_fraction


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "examples/surface-score-v2-2-cell-ranking-game"
SEED = 20260724
PLOTS_PER_SCORE = 5


def _content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _v2_2_score(candidate: dict[str, Any]) -> float:
    fraction = surface_score_v2_fraction(
        float(candidate["coverage_deg"]), "v2.2"
    )
    base_v2 = float(
        candidate["score_v2"]
        if "score_v2" in candidate else candidate["score_v2_1"]
    )
    return float(
        (1.0 - fraction) * float(candidate["score_v1"])
        + fraction * base_v2
    )


def _population(
    source_path: Path,
    ridge_results_path: Path,
    output: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    grids = dict(source["grids"])
    by_hash = {
        row["response_sha256"]: {
            **row,
            "score_v2_2": _v2_2_score(row),
        }
        for row in source["candidates"]
    }
    for row in _ridge_candidates(ridge_results_path, output, grids):
        by_hash[row["response_sha256"]] = {
            **row,
            "score_v2_2": _v2_2_score(row),
        }
    return (
        sorted(by_hash.values(), key=lambda row: row["id"]),
        grids,
        source["heatmap_encoding"],
    )


def select_cell_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Alternate score sources, skipping duplicates, for five picks each."""
    rankings = {
        "v2.2": sorted(
            candidates,
            key=lambda row: (-float(row["score_v2_2"]), row["id"]),
        ),
        "v1": sorted(
            candidates,
            key=lambda row: (-float(row["score_v1"]), row["id"]),
        ),
    }
    rank_lookup = {
        name: {
            row["response_sha256"]: index
            for index, row in enumerate(ranking, 1)
        }
        for name, ranking in rankings.items()
    }
    indices = {"v2.2": 0, "v1": 0}
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for source_name in ("v2.2", "v1") * PLOTS_PER_SCORE:
        ranking = rankings[source_name]
        while (
            indices[source_name] < len(ranking)
            and ranking[indices[source_name]]["response_sha256"] in used
        ):
            indices[source_name] += 1
        if indices[source_name] >= len(ranking):
            raise ValueError(f"not enough unique candidates for {source_name}")
        candidate = ranking[indices[source_name]]
        indices[source_name] += 1
        used.add(candidate["response_sha256"])
        selected.append({
            **candidate,
            "selected_by": source_name,
            "rank_v1": rank_lookup["v1"][candidate["response_sha256"]],
            "rank_v2_2": rank_lookup["v2.2"][
                candidate["response_sha256"]
            ],
        })
    if len(selected) != 10 or len(used) != 10:
        raise ValueError("cell selection did not produce ten unique candidates")
    return selected


def assemble(
    source_path: Path = DEFAULT_SOURCE,
    ridge_results_path: Path = DEFAULT_RIDGE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    population, grids, encoding = _population(
        source_path, ridge_results_path, output
    )
    rng = random.Random(SEED)
    rounds = []
    private_plots = {}
    round_number = 0
    for mouth in MOUTHS:
        for coverage in COVERAGES:
            round_number += 1
            cell = [
                row for row in population
                if float(row["mouth_mm"]) == mouth
                and float(row["coverage_deg"]) == coverage
            ]
            selected = select_cell_candidates(cell)
            rng.shuffle(selected)
            plots = []
            for plot_number, candidate in enumerate(selected, 1):
                plot_id = f"R{round_number:02d}-P{plot_number:02d}"
                plots.append({
                    "plot_id": plot_id,
                    "grid_id": candidate["grid_id"],
                    "heatmap_b64": candidate["heatmap_b64"],
                })
                private_plots[plot_id] = {
                    key: candidate[key] for key in (
                        "id",
                        "response_sha256",
                        "source_path",
                        "report_link",
                        "mouth_mm",
                        "coverage_deg",
                        "length_mm",
                        "k",
                        "n",
                        "s",
                        "score_v1",
                        "score_v2_2",
                        "selected_by",
                        "rank_v1",
                        "rank_v2_2",
                    )
                }
            rounds.append({
                "round": round_number,
                "cell_id": f"{coverage}deg-{mouth}mm",
                "mouth_mm": mouth,
                "coverage_deg": coverage,
                "plots": plots,
            })
    public = {
        "schema_version": 1,
        "experiment_id": "surface-score-v2-2-cell-ranking-game",
        "status": "ready",
        "blinded": True,
        "seed": SEED,
        "selection_rule": (
            "alternate five v2.2-ranked and five v1-ranked picks per cell; "
            "advance within a ranking whenever a response is already selected"
        ),
        "round_count": len(rounds),
        "plots_per_round": 10,
        "grids": grids,
        "heatmap_encoding": encoding,
        "rounds": rounds,
    }
    public["content_sha256"] = _content_hash(public)
    private = {
        "schema_version": 1,
        "experiment_id": public["experiment_id"],
        "public_content_sha256": public["content_sha256"],
        "population_count": len(population),
        "plots": private_plots,
    }
    private["content_sha256"] = _content_hash(private)
    return public, private


def render(public: dict[str, Any]) -> str:
    payload = json.dumps(
        public, separators=(",", ":")
    ).replace("</", "<\\/")
    options = "".join(
        f"<option value='{item['round']}'>"
        f"{item['mouth_mm']} mm · {item['coverage_deg']}°</option>"
        for item in public["rounds"]
    )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Blinded per-cell surface ranking</title>
<style>
:root{{--bg:#0b1015;--panel:#121a22;--panel2:#17212b;--ink:#edf3f6;--muted:#9eacb6;--line:#2b3945;--accent:#72d9ca}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif}}main{{max-width:1250px;margin:auto;padding:22px}}h1{{margin:0 0 8px}}p{{line-height:1.4}}button,select,textarea{{font:inherit}}button,select{{background:#1b2833;color:var(--ink);border:1px solid #456070;border-radius:7px;padding:8px 11px}}.muted{{color:var(--muted)}}.toolbar{{position:sticky;top:0;z-index:5;background:#0b1015ee;border-bottom:1px solid var(--line);padding:12px 0;display:flex;gap:9px;align-items:center;flex-wrap:wrap}}.toolbar .spacer{{flex:1}}.progress{{color:var(--accent);font-weight:700}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:15px}}.card{{display:grid;grid-template-columns:44px 1fr;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;cursor:grab}}.card.dragging{{opacity:.35}}.rank{{font-size:1.5rem;font-weight:800;color:var(--accent);text-align:center;padding-top:9px}}canvas{{display:block;width:100%;height:auto;background:#0d151d;border-radius:7px}}.plot-id{{color:var(--muted);font-size:.75rem;margin-top:5px}}textarea{{width:100%;min-height:42px;margin-top:6px;resize:vertical;background:#0d151d;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:7px}}.move{{display:flex;gap:5px;margin-top:5px}}.move button{{padding:3px 8px}}.notice{{background:#17212b;border:1px solid var(--line);border-radius:9px;padding:10px;margin:12px 0}}@media(max-width:850px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Blinded per-cell surface ranking</h1>
<p class='muted'>Drag the ten plots into best-to-worst order. Candidate
identity, score, and selection source remain hidden. Notes are optional and
travel with each plot. Every change is saved locally in this browser.</p>
<div class='notice'>One cell per round · normal logarithmic frequency scale ·
intended coverage and −3/−6/−9 dB contours shown.</div>
<div class='toolbar'>
<button id='previous' type='button'>← Previous</button>
<label>Cell <select id='round-select'>{options}</select></label>
<button id='next' type='button'>Next →</button>
<span class='progress' id='progress'></span><span class='spacer'></span>
<button id='complete-button' type='button'>Mark cell complete</button>
<button id='import-button' type='button'>Import</button>
<button id='export-button' type='button'>Export rankings</button>
<input id='import-file' type='file' accept='application/json' hidden>
</div>
<div id='cards' class='cards'></div>
<script id='experiment-data' type='application/json'>{payload}</script>
<script>
const EXP=JSON.parse(document.getElementById("experiment-data").textContent),KEY=`${{EXP.experiment_id}}:${{EXP.content_sha256}}`,select=document.getElementById("round-select"),cards=document.getElementById("cards");let current=1,dragged=null;
function initial(){{return{{schema_version:1,experiment_id:EXP.experiment_id,experiment_content_sha256:EXP.content_sha256,orders:Object.fromEntries(EXP.rounds.map(r=>[String(r.round),r.plots.map(p=>p.plot_id)])),notes:{{}},completed_rounds:[],updated_at:null}}}}
function valid(x){{if(!x||x.experiment_id!==EXP.experiment_id||x.experiment_content_sha256!==EXP.content_sha256||!Array.isArray(x.completed_rounds)||x.completed_rounds.some(n=>!Number.isInteger(n)||n<1||n>25))return false;for(const r of EXP.rounds){{const a=x.orders?.[String(r.round)],b=r.plots.map(p=>p.plot_id);if(!Array.isArray(a)||a.length!==10||a.some(id=>!b.includes(id))||new Set(a).size!==10)return false}}return true}}
let state;try{{state=JSON.parse(localStorage.getItem(KEY))}}catch{{}}if(!valid(state))state=initial();
function save(){{state.updated_at=new Date().toISOString();localStorage.setItem(KEY,JSON.stringify(state));progress()}}
function progress(){{const done=new Set(state.completed_rounds);document.getElementById("progress").textContent=`Cell ${{current}} / 25 · ${{done.size}} complete`;document.getElementById("complete-button").textContent=done.has(current)?"Reopen cell":"Mark cell complete"}}
function decode(plot){{const bytes=Uint8Array.from(atob(plot.heatmap_b64),c=>c.charCodeAt(0)),e=EXP.heatmap_encoding;return Array.from(bytes,x=>e.floor_db+x*e.step_db)}}
function color(t){{t=Math.max(0,Math.min(1,t));const stops=[[8,16,25],[16,50,73],[22,97,104],[210,173,60],[248,241,189]],x=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(x)),f=x-i,a=stops[i],b=stops[i+1];return a.map((v,j)=>Math.round(v+(b[j]-v)*f))}}
function crossing(a,b,l){{if((a-l)*(b-l)>0||a===b)return null;return(l-a)/(b-a)}}
function contour(ctx,v,g,l,x0,y0,w,h){{const R=g.rows,C=g.columns;for(let r=0;r<R-1;r++)for(let c=0;c<C-1;c++){{const z=[v[r*C+c],v[(r+1)*C+c],v[(r+1)*C+c+1],v[r*C+c+1]],p=[],ed=[[0,1],[1,2],[2,3],[3,0]],xy=[[r,c],[r+1,c],[r+1,c+1],[r,c+1]];for(const [a,b] of ed){{const q=crossing(z[a],z[b],l);if(q!==null)p.push([xy[a][0]+q*(xy[b][0]-xy[a][0]),xy[a][1]+q*(xy[b][1]-xy[a][1])])}}if(p.length>=2){{ctx.beginPath();for(let i=0;i+1<p.length;i+=2){{const A=p[i],B=p[i+1];ctx.moveTo(x0+A[0]/(R-1)*w,y0+(1-A[1]/(C-1))*h);ctx.lineTo(x0+B[0]/(R-1)*w,y0+(1-B[1]/(C-1))*h)}}ctx.stroke()}}}}}}
function draw(canvas,plot,coverage){{const ctx=canvas.getContext("2d"),g=EXP.grids[plot.grid_id],v=decode(plot),W=canvas.width,H=canvas.height,x0=52,y0=18,w=W-67,h=H-54;ctx.fillStyle="#0d151d";ctx.fillRect(0,0,W,H);const im=document.createElement("canvas");im.width=g.rows;im.height=g.columns;const ix=im.getContext("2d"),px=ix.createImageData(g.rows,g.columns);for(let r=0;r<g.rows;r++)for(let c=0;c<g.columns;c++){{const rgb=color(v[r*g.columns+c]/30+1),p=((g.columns-1-c)*g.rows+r)*4;px.data[p]=rgb[0];px.data[p+1]=rgb[1];px.data[p+2]=rgb[2];px.data[p+3]=255}}ix.putImageData(px,0,0);ctx.imageSmoothingEnabled=true;ctx.drawImage(im,x0,y0,w,h);const ma=g.angles_deg.at(-1),ty=y0+(1-coverage/ma)*h;ctx.save();ctx.strokeStyle="#69d6c8";ctx.lineWidth=1.7;ctx.setLineDash([7,5]);ctx.beginPath();ctx.moveTo(x0,ty);ctx.lineTo(x0+w,ty);ctx.stroke();ctx.restore();ctx.lineWidth=1.6;for(const [l,s] of [[-3,"#7fe7ff"],[-6,"#fff"],[-9,"#ffad5c"]]){{ctx.strokeStyle=s;contour(ctx,v,g,l,x0,y0,w,h)}}ctx.strokeStyle="#67808f";ctx.strokeRect(x0,y0,w,h);ctx.fillStyle="#aab8c1";ctx.font="11px system-ui";ctx.textAlign="center";const f=g.frequencies_hz;for(const q of [500,1000,2000,4000,8000])if(q>=f[0]&&q<=f.at(-1)){{const x=x0+(Math.log(q)-Math.log(f[0]))/(Math.log(f.at(-1))-Math.log(f[0]))*w;ctx.fillText(q>=1000?`${{q/1000}}k`:q,x,y0+h+16)}}ctx.textAlign="right";for(const a of [0,30,60,90])if(a<=ma)ctx.fillText(a+"°",x0-5,y0+(1-a/ma)*h+3)}}
function move(id,delta){{const o=state.orders[String(current)],i=o.indexOf(id),j=Math.max(0,Math.min(9,i+delta));if(i===j)return;o.splice(i,1);o.splice(j,0,id);save();render()}}
function render(){{const round=EXP.rounds[current-1],map=Object.fromEntries(round.plots.map(p=>[p.plot_id,p])),order=state.orders[String(current)];select.value=String(current);progress();cards.innerHTML=order.map((id,i)=>`<article class="card" draggable="true" data-id="${{id}}"><div><div class="rank">${{i+1}}</div><div class="move"><button type="button" data-up="${{id}}">↑</button><button type="button" data-down="${{id}}">↓</button></div></div><div><canvas width="520" height="250" data-plot="${{id}}"></canvas><div class="plot-id">${{id}}</div><textarea data-note="${{id}}" placeholder="Optional note for this plot">${{(state.notes[id]||"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;")}}</textarea></div></article>`).join("");document.querySelectorAll("canvas[data-plot]").forEach(c=>draw(c,map[c.dataset.plot],round.coverage_deg));document.querySelectorAll("textarea").forEach(t=>t.oninput=()=>{{state.notes[t.dataset.note]=t.value;save()}});document.querySelectorAll("[data-up]").forEach(b=>b.onclick=()=>move(b.dataset.up,-1));document.querySelectorAll("[data-down]").forEach(b=>b.onclick=()=>move(b.dataset.down,1));document.querySelectorAll(".card").forEach(c=>{{c.ondragstart=()=>{{dragged=c.dataset.id;c.classList.add("dragging")}};c.ondragend=()=>{{dragged=null;c.classList.remove("dragging")}};c.ondragover=e=>e.preventDefault();c.ondrop=e=>{{e.preventDefault();if(!dragged||dragged===c.dataset.id)return;const o=state.orders[String(current)],from=o.indexOf(dragged),to=o.indexOf(c.dataset.id);o.splice(from,1);o.splice(to,0,dragged);save();render()}}}})}}
function go(n){{current=Math.max(1,Math.min(25,n));render();scrollTo({{top:0,behavior:"smooth"}})}}select.onchange=()=>go(+select.value);document.getElementById("previous").onclick=()=>go(current-1);document.getElementById("next").onclick=()=>go(current+1);document.getElementById("complete-button").onclick=()=>{{const done=new Set(state.completed_rounds);if(done.has(current))done.delete(current);else done.add(current);state.completed_rounds=[...done].sort((a,b)=>a-b);save();if(done.has(current)&&current<25)go(current+1);else render()}};document.getElementById("export-button").onclick=()=>{{save();if(state.completed_rounds.length<25&&!confirm(`Only ${{state.completed_rounds.length}} of 25 cells are marked complete. Export anyway?`))return;const blob=new Blob([JSON.stringify(state,null,2)+"\\n"],{{type:"application/json"}}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="surface_score_v2_2_cell_rankings.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}};document.getElementById("import-button").onclick=()=>document.getElementById("import-file").click();document.getElementById("import-file").onchange=async e=>{{const x=JSON.parse(await e.target.files[0].text());if(!valid(x)){{alert("This ranking file does not match the experiment.");return}}state=x;save();render()}};render();
</script></main></body></html>"""


def write(
    source: Path = DEFAULT_SOURCE,
    ridge_results: Path = DEFAULT_RIDGE_RESULTS,
    output: Path = DEFAULT_OUTPUT,
) -> Path:
    public, private = assemble(source, ridge_results, output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment.json").write_text(
        json.dumps(public, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "private_manifest.json").write_text(
        json.dumps(private, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "index.html").write_text(render(public), encoding="utf-8")
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
