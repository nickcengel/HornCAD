#!/usr/bin/env python3
"""Build the measured 6° round-control composite/extension parameter map."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples/surface-score-v1-v2-rank-comparison/comparison.json"
RIDGE = ROOT / "examples/round-control-ridge-closure/results.json"
WIDE = ROOT / "examples/round-control-wide-coverage-closure/initial_results.json"
EXTENSION = ROOT / "examples/extension-throat-angle-heuristics/manifest.json"
OUTPUT = ROOT / "examples/round-control-composite-extension-map"
COVERAGES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)
EXTENSIONS = (0, 20, 40, 60)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _state_record(response: Path) -> tuple[dict[str, Any], Path]:
    state_path = response.parents[3] / "search_state.json"
    state = _read(state_path)
    candidate_id = response.parents[1].name
    record = next((
        row for row in state.get("candidates", [])
        if row.get("id") == candidate_id
    ), None)
    if record is None:
        raise ValueError(f"missing {candidate_id} in {state_path}")
    return record, state_path.parent


def _scores(record: dict[str, Any], response: Path) -> dict[str, float]:
    surface = (
        (record.get("surface_diagnostics") or {}).get("score") or {})
    impedance = record.get("throat_impedance_diagnostics") or {}
    composite = record.get("composite_diagnostics") or {}
    if surface.get("version") != "v2.3":
        raise ValueError(f"{response}: surface score is not v2.3")
    if impedance.get("diagnostic_version") != "2.3.0":
        raise ValueError(f"{response}: impedance score is not v2.3.0")
    if composite.get("version") != "1.0":
        raise ValueError(f"{response}: composite score is not v1.0")
    expected = (
        0.75*float(surface["overall_percent"])
        + 0.25*float(impedance["overall_percent"])
    )
    if not math.isclose(
            expected, float(composite["overall_percent"]), abs_tol=1e-9):
        raise ValueError(f"{response}: composite components disagree")
    return {
        "surface_score_v2_3": float(surface["overall_percent"]),
        "throat_impedance_score_v2_3_0":
            float(impedance["overall_percent"]),
        "composite_score_v1_0": float(composite["overall_percent"]),
    }


def _report_path(
    record: dict[str, Any], search: Path, response: Path
) -> Path:
    report = record.get("report_file")
    if report:
        candidate = search / str(report)
        if candidate.is_file():
            return candidate
    reports = sorted(response.parent.glob("*_Report.html"))
    return reports[0] if reports else search / "search_report.html"


def _base_rows() -> list[dict[str, Any]]:
    source = _read(SOURCE)
    raw = list(source["candidates"])
    for path in (RIDGE, WIDE):
        for row in _read(path)["evidence"]:
            raw.append({
                "id": row["id"],
                "coverage_deg": row["coverage_deg"],
                "mouth_mm": row["mouth_mm"],
                "length_mm": row["length_mm"],
                "k": row["k"],
                "n": row["n"],
                "s": row.get("derived_s", row.get("s")),
                "source_path": row.get(
                    "response_path", row.get("source_path")),
                "response_sha256": row["response_sha256"],
            })
    unique = {
        row["response_sha256"]: row for row in raw
    }
    rows = []
    for row in unique.values():
        response = ROOT / row["source_path"]
        record, search = _state_record(response)
        rows.append({
            "id": row["id"],
            "coverage_deg": int(row["coverage_deg"]),
            "mouth_mm": int(row["mouth_mm"]),
            "length_mm": float(row["length_mm"]),
            "profile_plus_extension_length_mm": float(row["length_mm"]),
            "k": float(row["k"]),
            "n": float(row["n"]),
            "s": float(row["s"]),
            "throat_angle_deg": 6,
            "extension_mm": 0,
            "evidence_role": "zero-extension-round",
            "parent_id": row["id"],
            "source_path": row["source_path"],
            "response_sha256": row["response_sha256"],
            "report_path": str(
                _report_path(record, search, response).relative_to(ROOT)),
            **_scores(record, response),
        })
    return rows


def _extension_rows() -> list[dict[str, Any]]:
    manifest = _read(EXTENSION)
    rows = []
    for coordinate in manifest["coordinates"]:
        if int(coordinate["throat_angle_deg"]) != 6:
            continue
        search_yaml = ROOT / manifest["inputs"][coordinate["id"]]["search"]
        search = search_yaml.parent
        state = _read(search / "search_state.json")
        record = state["candidates"][0]
        response = (
            search / "candidates" / str(record["id"])
            / "bem" / "responses.npz"
        )
        cell_id = (
            f"{coordinate['coverage_deg']}deg-"
            f"{coordinate['round_mouth_diameter_mm']}mm")
        parent = manifest["parents"][coordinate["parent_role"]][cell_id]
        rows.append({
            "id": coordinate["id"],
            "coverage_deg": int(coordinate["coverage_deg"]),
            "mouth_mm": int(coordinate["round_mouth_diameter_mm"]),
            "length_mm": float(coordinate["osse_length_mm"]),
            "profile_plus_extension_length_mm": float(
                coordinate["profile_plus_extension_length_mm"]),
            "k": float(parent["k"]),
            "n": float(parent["n"]),
            "s": float(coordinate["derived_s"]),
            "throat_angle_deg": 6,
            "extension_mm": int(coordinate["extension_mm"]),
            "evidence_role": coordinate["stage"],
            "parent_id": coordinate["parent_id"],
            "source_path": str(response.relative_to(ROOT)),
            "response_sha256": _hash_file(response),
            "report_path": str(
                _report_path(record, search, response).relative_to(ROOT)),
            **_scores(record, response),
        })
    return rows


def assemble() -> dict[str, Any]:
    by_hash = {
        row["response_sha256"]: row
        for row in [*_base_rows(), *_extension_rows()]
    }
    evidence = sorted(by_hash.values(), key=lambda row: row["id"])
    cells = {}
    for coverage in COVERAGES:
        for mouth in MOUTHS:
            selected = [
                row for row in evidence
                if row["coverage_deg"] == coverage
                and row["mouth_mm"] == mouth
            ]
            zero = [
                row for row in selected if row["extension_mm"] == 0
            ]
            extended = [
                row for row in selected if row["extension_mm"] > 0
            ]
            if not zero or not extended:
                raise ValueError(f"incomplete evidence at {coverage}/{mouth}")

            def winner(values: list[dict[str, Any]]) -> dict[str, Any]:
                return min(values, key=lambda row: (
                    -row["composite_score_v1_0"], row["id"]))

            zero_winner = winner(zero)
            extension_winner = winner(extended)
            overall = winner(selected)
            by_extension = {}
            for extension in EXTENSIONS:
                values = [
                    row for row in selected
                    if row["extension_mm"] == extension
                ]
                by_extension[str(extension)] = (
                    winner(values) if values else None)
            cells[f"{coverage}deg-{mouth}mm"] = {
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "evidence_count": len(selected),
                "zero_extension_winner": zero_winner,
                "best_measured_extension": extension_winner,
                "overall_winner": overall,
                "best_extension_minus_zero_composite": (
                    extension_winner["composite_score_v1_0"]
                    - zero_winner["composite_score_v1_0"]
                ),
                "winners_by_extension_mm": by_extension,
            }
    result = {
        "schema_version": 1,
        "study_id": "round-control-composite-extension-map-v1",
        "status": "existing-evidence",
        "selection_scope": (
            "axisymmetric round horns at 6 degree throat angle"),
        "ranking": {
            "diagnostic": "composite_score_v1.0",
            "surface_weight": 0.75,
            "throat_impedance_weight": 0.25,
            "surface_version": "v2.3",
            "throat_impedance_version": "2.3.0",
            "authoritative_scope": "this extension-selection map only",
        },
        "evidence_count": len(evidence),
        "zero_extension_evidence_count": sum(
            row["extension_mm"] == 0 for row in evidence),
        "extension_evidence_count": sum(
            row["extension_mm"] > 0 for row in evidence),
        "sources": {
            str(path.relative_to(ROOT)): _hash_file(path)
            for path in (SOURCE, RIDGE, WIDE, EXTENSION)
        },
        "cells": cells,
        "evidence": evidence,
    }
    result["content_sha256"] = _content_hash(result)
    return result


def _number(value: Any, digits: int = 1) -> str:
    return (
        f"{float(value):.{digits}f}"
        if isinstance(value, (float, int)) and math.isfinite(value) else "—"
    )


def _relative(output: Path, path: str) -> str:
    return os.path.relpath(ROOT / path, output).replace(os.sep, "/")


def render(result: dict[str, Any], output: Path) -> str:
    cells = result["cells"]

    def grid(value: str, digits: int = 1) -> str:
        body = []
        for mouth in MOUTHS:
            values = []
            for coverage in COVERAGES:
                winner = cells[f"{coverage}deg-{mouth}mm"]["overall_winner"]
                values.append(
                    f"<td>{_number(winner[value], digits)}</td>")
            body.append(f"<tr><th>{mouth} mm</th>{''.join(values)}</tr>")
        return (
            "<table><thead><tr><th>Mouth / coverage</th>"
            + "".join(f"<th>{value}°</th>" for value in COVERAGES)
            + f"</tr></thead><tbody>{''.join(body)}</tbody></table>"
        )

    summary_rows = []
    for cell_id, cell in sorted(cells.items()):
        zero = cell["zero_extension_winner"]
        extended = cell["best_measured_extension"]
        overall = cell["overall_winner"]
        summary_rows.append(
            "<tr>"
            f"<td>{html.escape(cell_id)}</td>"
            f"<td>{_number(overall['composite_score_v1_0'],2)}</td>"
            f"<td>{_number(overall['surface_score_v2_3'],2)}</td>"
            f"<td>{_number(overall['throat_impedance_score_v2_3_0'],2)}</td>"
            f"<td>{overall['extension_mm']}</td>"
            f"<td>{_number(overall['length_mm'],3)}</td>"
            f"<td>{_number(overall['k'],2)}</td>"
            f"<td>{_number(overall['n'],2)}</td>"
            f"<td>{_number(overall['s'],4)}</td>"
            f"<td>{_number(zero['composite_score_v1_0'],2)}</td>"
            f"<td>{_number(extended['composite_score_v1_0'],2)}</td>"
            f"<td>{_number(cell['best_extension_minus_zero_composite'],2)}</td>"
            f"<td><a href='{html.escape(_relative(output, overall['report_path']))}'>candidate</a></td>"
            "</tr>"
        )
    evidence_rows = []
    for row in sorted(result["evidence"], key=lambda item: (
            item["coverage_deg"], item["mouth_mm"],
            -item["composite_score_v1_0"], item["id"])):
        evidence_rows.append(
            "<tr>"
            f"<td>{html.escape(row['id'])}</td>"
            f"<td>{row['coverage_deg']}</td><td>{row['mouth_mm']}</td>"
            f"<td>{row['extension_mm']}</td>"
            f"<td>{_number(row['composite_score_v1_0'],2)}</td>"
            f"<td>{_number(row['surface_score_v2_3'],2)}</td>"
            f"<td>{_number(row['throat_impedance_score_v2_3_0'],2)}</td>"
            f"<td>{_number(row['length_mm'],3)}</td>"
            f"<td>{_number(row['profile_plus_extension_length_mm'],3)}</td>"
            f"<td>{_number(row['k'],2)}</td><td>{_number(row['n'],2)}</td>"
            f"<td>{_number(row['s'],4)}</td>"
            f"<td>{html.escape(row['evidence_role'])}</td>"
            f"<td><a href='{html.escape(_relative(output, row['report_path']))}'>candidate</a></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8"><title>Round-control 6° composite extension map</title>
<style>
body{{font:15px system-ui,sans-serif;margin:20px;background:#10161d;color:#e8edf2}}
section{{background:#17212a;border:1px solid #34414c;border-radius:9px;padding:14px;margin:14px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:7px 9px;border-bottom:1px solid #34414c;text-align:right}}
th{{background:#202c36;cursor:pointer}}th:first-child,td:first-child{{text-align:left}}a{{color:#7bd7cb}}.muted{{color:#aab5bf}}
</style>
<h1>Round-control 6° composite extension map</h1>
<p>Composite v1.0 = 75% surface v2.3 + 25% throat impedance v2.3.0.
This composite is authoritative only for this extension-selection map.</p>
<p class="muted">{result['zero_extension_evidence_count']} zero-extension and
{result['extension_evidence_count']} extension responses; exact-response
deduplicated. Existing-evidence status.</p>
<section><h2>Cell winners</h2><table class="sortable"><thead><tr>
<th>Cell</th><th>Composite</th><th>Surface</th><th>Impedance</th>
<th>Extension mm</th><th>OSSE length</th><th>K</th><th>N</th><th>S</th>
<th>Best E0</th><th>Best E&gt;0</th><th>Extension Δ</th><th>Report</th>
</tr></thead><tbody>{''.join(summary_rows)}</tbody></table></section>
<section><h2>Composite score</h2>{grid('composite_score_v1_0',2)}</section>
<section><h2>Extension (mm)</h2>{grid('extension_mm',0)}</section>
<section><h2>OSSE length (mm)</h2>{grid('length_mm',1)}</section>
<section><h2>K</h2>{grid('k',2)}</section>
<section><h2>N</h2>{grid('n',2)}</section>
<section><h2>S</h2>{grid('s',3)}</section>
<section><h2>All measured evidence</h2><table class="sortable"><thead><tr>
<th>Candidate</th><th>Coverage</th><th>Mouth</th><th>Extension</th>
<th>Composite</th><th>Surface</th><th>Impedance</th><th>OSSE length</th>
<th>Total length</th><th>K</th><th>N</th><th>S</th><th>Role</th><th>Report</th>
</tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></section>
<script>
for(const table of document.querySelectorAll('table.sortable')){{
 const body=table.tBodies[0];
 for(const [index,th] of [...table.tHead.rows[0].cells].entries()){{
  th.addEventListener('click',()=>{{
   const asc=th.dataset.order!=='asc'; th.dataset.order=asc?'asc':'desc';
   const rows=[...body.rows].sort((a,b)=>{{
    const av=a.cells[index].textContent.trim(),bv=b.cells[index].textContent.trim();
    const an=Number(av),bn=Number(bv);
    const value=Number.isFinite(an)&&Number.isFinite(bn)?an-bn:av.localeCompare(bv);
    return asc?value:-value;
   }});
   body.append(...rows);
  }});
 }}
}}
</script>"""


def write(output: Path = OUTPUT) -> dict[str, Any]:
    result = assemble()
    output.mkdir(parents=True, exist_ok=True)
    (output / "map.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    (output / "index.html").write_text(
        render(result, output), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = write(args.output)
    print(json.dumps({
        "output": str(args.output.relative_to(ROOT)),
        "evidence_count": result["evidence_count"],
        "content_sha256": result["content_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
