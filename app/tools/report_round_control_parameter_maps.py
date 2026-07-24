#!/usr/bin/env python3
"""Generate standalone maps of measured high-scoring round-horn parameters."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    ROOT / "examples/extension-throat-angle-heuristics/manifest.json")
DEFAULT_OUTPUT = ROOT / "examples/round-control-parameter-maps/index.html"
COVERAGES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _color(value: float, minimum: float, maximum: float) -> str:
    fraction = (
        (value - minimum) / (maximum - minimum)
        if maximum > minimum else 0.5
    )
    hue = 220.0 - 178.0 * fraction
    lightness = 24.0 + 13.0 * fraction
    return f"hsl({hue:.1f} 62% {lightness:.1f}%)"


def _heatmap(
    parents: dict[str, dict[str, Any]],
    *,
    title: str,
    description: str,
    value_for: Callable[[dict[str, Any]], float],
    label_for: Callable[[dict[str, Any]], str],
    secondary_for: Callable[[dict[str, Any]], str] = lambda parent: "",
) -> str:
    values = [
        value_for(parents[f"{coverage}deg-{mouth}mm"])
        for mouth in MOUTHS for coverage in COVERAGES
    ]
    minimum, maximum = min(values), max(values)
    rows = []
    for mouth in MOUTHS:
        cells = []
        for coverage in COVERAGES:
            parent = parents[f"{coverage}deg-{mouth}mm"]
            value = value_for(parent)
            secondary = secondary_for(parent)
            score = float(parent["responses"]["surface_score"])
            cells.append(
                f"<td class='map-cell' "
                f"style='background:{_color(value, minimum, maximum)}' "
                f"title='{html.escape(parent['id'])} · "
                f"surface score {score:.2f}'>"
                f"<strong>{html.escape(label_for(parent))}</strong>"
                + (
                    f"<span>{html.escape(secondary)}</span>"
                    if secondary else ""
                )
                + "</td>"
            )
        rows.append(f"<tr><th>{mouth} mm</th>{''.join(cells)}</tr>")
    return (
        "<article class='map-card'>"
        f"<h2>{html.escape(title)}</h2>"
        f"<p>{html.escape(description)}</p>"
        "<table class='heatmap'><thead><tr>"
        "<th>Mouth ↓<br>Coverage →</th>"
        + "".join(f"<th>{coverage}°</th>" for coverage in COVERAGES)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "<div class='scale'>"
        f"<span>{minimum:.3g}</span><i></i><span>{maximum:.3g}</span>"
        "</div></article>"
    )


def _coupled_map(parents: dict[str, dict[str, Any]]) -> str:
    length_values = [
        float(parent["length_mm"]) for parent in parents.values()]
    k_values = [float(parent["k"]) for parent in parents.values()]
    s_values = [float(parent["s"]) for parent in parents.values()]
    l_min, l_max = min(length_values), max(length_values)
    k_min, k_max = min(k_values), max(k_values)
    s_min, s_max = min(s_values), max(s_values)
    rows = []
    for mouth in MOUTHS:
        cells = []
        for coverage in COVERAGES:
            parent = parents[f"{coverage}deg-{mouth}mm"]
            length = float(parent["length_mm"])
            k = float(parent["k"])
            n = float(parent["n"])
            s = float(parent["s"])
            diameter = 48.0 + 30.0 * (
                (length - l_min) / (l_max - l_min))
            border = 2.0 + 5.0 * ((k - k_min) / (k_max - k_min))
            cells.append(
                f"<td class='glyph-cell' "
                f"style='background:{_color(s, s_min, s_max)}' "
                f"title='{html.escape(parent['id'])}'>"
                f"<div class='glyph' style='width:{diameter:.1f}px;"
                f"height:{diameter:.1f}px;border-width:{border:.1f}px'>"
                f"<strong>N {n:g}</strong></div>"
                f"<span>L {length:.1f} mm · K {k:g}<br>S {s:.3f}</span>"
                "</td>"
            )
        rows.append(f"<tr><th>{mouth} mm</th>{''.join(cells)}</tr>")
    return (
        "<section><h2>Coupled recipe map</h2>"
        "<p class='muted'>Background color encodes S (blue low, gold high); "
        "circle diameter encodes physical length; border thickness encodes "
        "K; the circle label is N. Exact L, K, and S values remain below each "
        "glyph.</p><table class='coupled'><thead><tr>"
        "<th>Mouth ↓<br>Coverage →</th>"
        + "".join(f"<th>{coverage}°</th>" for coverage in COVERAGES)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><div class='glyph-legend'>"
        "<span>small circle = shorter physical length</span>"
        "<span>thicker ring = higher K</span>"
        "<span>blue → gold = lower → higher S</span>"
        "</div></section>"
    )


def render(manifest: dict[str, Any]) -> str:
    parents = manifest["parents"]["primary"]
    if len(parents) != 25:
        raise ValueError(f"expected 25 primary parents, found {len(parents)}")
    ordered = [
        parents[f"{coverage}deg-{mouth}mm"]
        for mouth in MOUTHS for coverage in COVERAGES
    ]
    s = np.asarray([float(parent["s"]) for parent in ordered])
    coverage = np.asarray(
        [float(parent["coverage_deg"]) for parent in ordered])
    coverage_s_correlation = float(np.corrcoef(coverage, s)[0, 1])
    n_eight = sum(float(parent["n"]) == 8.0 for parent in ordered)

    maps = (
        _heatmap(
            parents,
            title="Length",
            description="Physical horn length in millimetres.",
            value_for=lambda parent: float(parent["length_mm"]),
            label_for=lambda parent: f"{float(parent['length_mm']):.1f} mm",
        )
        + _heatmap(
            parents,
            title="K",
            description="OSSE core-curvature control.",
            value_for=lambda parent: float(parent["k"]),
            label_for=lambda parent: f"{float(parent['k']):g}",
        )
        + _heatmap(
            parents,
            title="N",
            description="Termination-shape exponent.",
            value_for=lambda parent: float(parent["n"]),
            label_for=lambda parent: f"{float(parent['n']):g}",
        )
        + _heatmap(
            parents,
            title="S",
            description="Solved mouth-termination amplitude.",
            value_for=lambda parent: float(parent["s"]),
            label_for=lambda parent: f"{float(parent['s']):.3f}",
        )
    )
    return f"""<!doctype html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Round-control parameter maps</title>
<style>
:root{{--bg:#0b1015;--panel:#121a22;--panel2:#17212b;--ink:#edf3f6;--muted:#9eacb6;--line:#2b3945;--accent:#72d9ca}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:24px}}h1,h2{{margin:0 0 8px}}p{{line-height:1.45}}.muted,.map-card p{{color:var(--muted)}}section,.map-card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0;overflow-x:auto}}.insights{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.insight{{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:14px}}.insight strong{{display:block;font-size:1.5rem;color:var(--accent)}}.map-grid{{display:grid;grid-template-columns:repeat(2,minmax(500px,1fr));gap:16px}}.map-card{{margin:0}}table{{border-collapse:collapse;width:100%;table-layout:fixed}}th,td{{border:1px solid rgba(255,255,255,.12);text-align:center;padding:10px 6px}}th{{background:var(--panel2)}}th:first-child{{width:105px}}.map-cell{{height:74px}}.map-cell strong{{display:block;font-size:1.2rem;text-shadow:0 1px 3px #000}}.map-cell span{{display:block;font-size:.78rem;margin-top:3px;text-shadow:0 1px 3px #000}}.scale{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;margin-top:9px;color:var(--muted);font-size:.82rem}}.scale i{{height:9px;border-radius:99px;background:linear-gradient(90deg,hsl(220 62% 24%),hsl(131 62% 30.5%),hsl(42 62% 37%))}}.glyph-cell{{height:136px;vertical-align:middle}}.glyph{{display:flex;align-items:center;justify-content:center;margin:0 auto 6px;border-style:solid;border-color:rgba(255,255,255,.88);border-radius:50%;background:rgba(8,12,16,.28);text-shadow:0 1px 3px #000}}.glyph-cell>span{{font-size:.77rem;text-shadow:0 1px 3px #000}}.glyph-legend{{display:flex;flex-wrap:wrap;gap:18px;margin-top:10px;color:var(--muted)}}code{{overflow-wrap:anywhere}}@media(max-width:1100px){{.map-grid{{grid-template-columns:1fr}}.insights{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Measured high-scoring round-control parameter maps</h1>
<p class='muted'>The 25 cells are the final measured high-scoring round parents,
not surrogate predictions. Coverage increases left to right; mouth diameter
increases top to bottom. Hover any cell for its evidence identifier and surface
score.</p>
<section><h2>Strongest visible structure</h2><div class='insights'>
<div class='insight'><strong>r = {coverage_s_correlation:.3f}</strong>
S rises strongly with coverage across the grid.</div>
<div class='insight'><strong>{n_eight} / 25</strong>
Selected parents use N = 8; N is mostly stable, with a few localized
exceptions.</div>
<div class='insight'><strong>Length in mm</strong>
Physical length generally rises with mouth size and falls as coverage widens.
</div>
</div></section>
<section><h2>One map per parameter</h2>
<p class='muted'>Each panel has its own blue-to-gold scale. Exact values are
printed, so color shows pattern without hiding discontinuities.</p>
<div class='map-grid'>{maps}</div></section>
{_coupled_map(parents)}
<section><h2>Why this is not a 3D surface</h2>
<p class='muted'>A continuous surface would imply dependable interpolation
between cells. The round-control work did not establish that. These discrete
maps preserve abrupt changes that may mark a switch between local high-scoring
zones.</p>
<p class='muted'>Manifest freeze:
<code>{html.escape(str(manifest.get('freeze_sha256', 'unavailable')))}</code>
</p></section>
</main></body></html>"""


def write_report(manifest_path: Path, output_path: Path) -> Path:
    output = render(_read_json(manifest_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".html.tmp")
    temporary.write_text(output, encoding="utf-8")
    temporary.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(write_report(
        args.manifest.resolve(),
        args.output.resolve(),
    ))


if __name__ == "__main__":
    main()
