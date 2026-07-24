#!/usr/bin/env python3
"""Prepare, run, report, and analyze the capped wide-coverage closure."""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import html
import json
import os
from pathlib import Path
from typing import Any

import yaml

from .composite_diagnostics import composite_surface_impedance_score
from .generate_surface_score_rank_comparison import _evaluation_grid
from .interactive_results import load_run
from .round_control_model import _content_hash, _digest_file, _validate_npz
from .run_bem_search import materialize_candidate, run_search
from .run_stage_aware_bem_queue import run_queue, validate_queue
from .surface_diagnostics import surface_diagnostics, surface_score
from .throat_impedance_diagnostics import throat_impedance_diagnostics


ROOT = Path(__file__).resolve().parents[2]
STUDY_ROOT = ROOT / "examples/round-control-wide-coverage-closure"
WINNERS = ROOT / "examples/round-control-parameter-maps-v2-3/winners.json"
PLAN = ROOT / "docs/plans/round_control_wide_coverage_closure.md"
HARD_CANDIDATE_CAP = 12
QUEUE_WORKERS = 4
NUMCALC_PROCESSES = 20
IMPROVEMENT_THRESHOLD = 1.5

INITIAL_COORDINATES = (
    (45, 350, 142.500, 6.0, 8.0, "length-low"),
    (45, 350, 157.500, 6.0, 8.0, "length-high"),
    (45, 350, 150.000, 5.5, 8.0, "k-low"),
    (45, 350, 150.000, 6.5, 8.0, "k-high"),
    (50, 350, 118.647, 6.0, 8.0, "length-low"),
    (50, 350, 131.137, 6.0, 8.0, "length-high"),
    (50, 350, 124.892, 5.5, 8.0, "k-low"),
    (50, 350, 124.892, 6.5, 8.0, "k-high"),
    (50, 450, 191.627, 7.0, 8.0, "length-high-1p2"),
    (50, 450, 207.596, 7.0, 8.0, "length-high-1p3"),
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _winner(coverage: int, mouth: int) -> dict[str, Any]:
    cells = _read_json(WINNERS)["cells"]
    return dict(cells[f"{coverage}deg-{mouth}mm"]["v2_3_winner"])


def _source_project(winner: dict[str, Any]) -> Path:
    response = ROOT / winner["source_path"]
    project = response.parent.parent / "project.yaml"
    if not project.is_file():
        raise FileNotFoundError(project)
    return project


def _derived_s(mouth: int, coverage: int, length: float,
               k: float, n: float) -> float:
    from app.design_api import RoundControlHeuristics

    return float(RoundControlHeuristics._s_at_length(
        mouth, coverage, length, k, n))


def initial_coordinates() -> list[dict[str, Any]]:
    rows = []
    for coverage, mouth, length, k, n, role in INITIAL_COORDINATES:
        incumbent = _winner(coverage, mouth)
        rows.append({
            "id": (
                f"wide-closure-{coverage}deg-{mouth}mm-{role}"
                f"-L{str(length).replace('.', 'p')}"
                f"-K{str(k).replace('.', 'p')}-N{str(n).replace('.', 'p')}"
            ),
            "stage": "initial",
            "role": role,
            "coverage_deg": coverage,
            "mouth_mm": mouth,
            "length_mm": length,
            "k": k,
            "n": n,
            "derived_s": _derived_s(mouth, coverage, length, k, n),
            "incumbent": {
                key: incumbent[key] for key in (
                    "id", "response_sha256", "source_path", "length_mm",
                    "k", "n", "s", "score_v2_3",
                )
            },
        })
    return rows


def _directory(coordinate: dict[str, Any]) -> Path:
    return STUDY_ROOT / "searches" / coordinate["stage"] / coordinate["id"]


def _search_document(coordinate: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, float]]:
    coverage = float(coordinate["coverage_deg"])
    values = {
        "length_mm": float(coordinate["length_mm"]),
        "extension_mm": 0.0,
        "osse_coverage_h_deg": coverage,
        "osse_coverage_v_deg": coverage,
        "k_h": float(coordinate["k"]),
        "k_v": float(coordinate["k"]),
        "n_h": float(coordinate["n"]),
        "n_v": float(coordinate["n"]),
    }
    bounds = {
        key: [
            value-max(1e-6, abs(value)*1e-9),
            value+max(1e-6, abs(value)*1e-9),
        ]
        for key, value in values.items()
    }
    search = {
        "version": 1,
        "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage,
        "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": 500.0,
        "crossover_hz": 750.0,
        "upper_frequency_hz": 8000.0,
        "max_evaluations": 1,
        "initial_candidates": 1,
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.049, 4.001],
        "sampling_stability_points": 2.0,
        "confirmation_points_per_octave": 16.0,
        "adaptive_pruning": {"enabled": False},
        "bounds": bounds,
        "initial_pool": [{
            "label": f"{coordinate['id']}-schema-seed-duplicate",
            "values": values,
        }],
        "solver": {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 10,
        },
        "wide_coverage_closure": {
            "coordinate_id": coordinate["id"],
            "stage": coordinate["stage"],
            "role": coordinate["role"],
            "surface_score_version": "v2.3",
            "surface_score_is_authoritative": True,
            "throat_impedance_used_in_ranking": False,
            "composite_used_in_ranking": False,
            "k_hard_maximum": 7.0,
        },
    }
    return {"bem_candidate_search": search}, values


def prepare_initial() -> dict[str, Any]:
    coordinates = initial_coordinates()
    if len(coordinates) != 10:
        raise ValueError("initial design must contain exactly ten candidates")
    inputs = {}
    for coordinate in coordinates:
        directory = _directory(coordinate)
        source_path = _source_project(coordinate["incumbent"])
        source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        document, values = _search_document(coordinate)
        project, derived = materialize_candidate(
            copy.deepcopy(source), values, document["bem_candidate_search"])
        if abs(float(derived["s_h"])-coordinate["derived_s"]) > 1e-9:
            raise ValueError(f"S mismatch for {coordinate['id']}")
        _write_yaml(directory / "project.yaml", project)
        _write_yaml(directory / "search.yaml", document)
        inputs[coordinate["id"]] = {
            "source_project": str(source_path.relative_to(ROOT)),
            "source_project_sha256": _digest_file(source_path),
            "project": str((directory / "project.yaml").relative_to(ROOT)),
            "project_sha256": _digest_file(directory / "project.yaml"),
            "search": str((directory / "search.yaml").relative_to(ROOT)),
            "search_sha256": _digest_file(directory / "search.yaml"),
        }
    manifest = {
        "schema_version": 1,
        "study_id": "round-control-wide-coverage-closure-v1",
        "stage": "initial",
        "status": "frozen-not-run",
        "candidate_count": len(coordinates),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "coordinates": coordinates,
        "inputs": inputs,
        "plan": str(PLAN.relative_to(ROOT)),
        "plan_sha256": _digest_file(PLAN),
        "winners": str(WINNERS.relative_to(ROOT)),
        "winners_sha256": _digest_file(WINNERS),
        "ranking": {
            "authoritative_diagnostic": "surface_score_v2.3",
            "composite_is_authoritative": False,
            "throat_impedance_is_authoritative": False,
        },
        "conditional_rule": {
            "improvement_threshold_points": IMPROVEMENT_THRESHOLD,
            "maximum_candidates": 2,
            "improvement_branch": (
                "confirm or bracket the strongest measured direction"
            ),
            "no_improvement_branch": (
                "matched infinite-planar-baffle mechanism comparison for "
                "35deg/450mm and 50deg/450mm, only after equivalent preflight"
            ),
        },
        "scheduler": {
            "type": "stage-aware-bem-queue",
            "queue_workers": QUEUE_WORKERS,
            "numcalc_process_capacity": NUMCALC_PROCESSES,
            "configured_workers_per_search": 10,
            "search_sharding": "one-candidate-per-search",
        },
    }
    manifest["freeze_sha256"] = _content_hash(manifest)
    _write_json(STUDY_ROOT / "initial_manifest.json", manifest)
    refresh_index()
    return manifest


def _verify_manifest() -> dict[str, Any]:
    manifest = _read_json(STUDY_ROOT / "initial_manifest.json")
    expected = manifest["freeze_sha256"]
    actual = _content_hash({
        key: value for key, value in manifest.items()
        if key != "freeze_sha256"
    })
    if actual != expected:
        raise ValueError("initial manifest freeze hash changed")
    if _digest_file(PLAN) != manifest["plan_sha256"]:
        raise ValueError("study plan changed after freeze")
    if (_digest_file(WINNERS) != manifest["winners_sha256"]
            and not (STUDY_ROOT / "initial_results.json").is_file()):
        raise ValueError("winner map changed after freeze")
    for coordinate in manifest["coordinates"]:
        item = manifest["inputs"][coordinate["id"]]
        for kind in ("source_project", "project", "search"):
            path = ROOT / item[kind]
            if _digest_file(path) != item[f"{kind}_sha256"]:
                raise ValueError(f"changed frozen input: {path}")
    return manifest


def _search_paths(manifest: dict[str, Any]) -> list[Path]:
    return [
        ROOT / manifest["inputs"][row["id"]]["search"]
        for row in manifest["coordinates"]
    ]


def preflight() -> dict[str, Any]:
    manifest = _verify_manifest()
    paths = _search_paths(manifest)
    scheduler = validate_queue(paths, QUEUE_WORKERS, NUMCALC_PROCESSES)
    rows = []
    for path in paths:
        state = run_search(path, path.parent, binary=None, dry_run=True)
        candidates = state.get("candidates", [])
        if (state.get("status") != "preflight" or len(candidates) != 1
                or candidates[0].get("status") != "preflight"):
            raise ValueError(f"wrong one-candidate preflight: {path}")
        rows.append({"search": str(path.relative_to(ROOT)),
                     "candidate_count": 1})
    result = {"stage": "initial", "scheduler": scheduler, "searches": rows}
    _write_json(STUDY_ROOT / "initial_preflight.json", result)
    refresh_index()
    return result


def run_initial() -> dict[str, Any]:
    manifest = _verify_manifest()
    if not (STUDY_ROOT / "initial_preflight.json").is_file():
        raise ValueError("initial preflight has not run")
    refresh_index()
    try:
        return run_queue(
            _search_paths(manifest),
            STUDY_ROOT / "initial_runtime.json",
            queue_workers=QUEUE_WORKERS,
            numcalc_processes=NUMCALC_PROCESSES,
            on_event=lambda _event: refresh_index(),
        )
    finally:
        refresh_index()


def _diagnostics(response: Path) -> dict[str, Any]:
    _validate_npz(response)
    run = load_run(response.parent)
    radiation = surface_diagnostics(
        run, _evaluation_grid(run), fixed_band=True)
    active = surface_score(radiation, run.get("mouth_dimensions_mm"))
    if active is None or active.get("version") != "v2.3":
        raise ValueError(f"active v2.3 score unavailable: {response}")
    impedance = throat_impedance_diagnostics(
        run["frequencies"],
        run["normalized_impedance"],
        float(run["crossover_hz"]),
        float(run["parameters"].get(
            "upper_frequency_hz", run["frequencies"][-1])),
    )
    composite = composite_surface_impedance_score(active, impedance)
    return {
        "surface_score_v2_3": float(active["overall_percent"]),
        "surface": radiation,
        "throat_impedance": impedance,
        "composite": composite,
    }


def measured_initial() -> list[dict[str, Any]]:
    manifest = _verify_manifest()
    rows = []
    for coordinate in manifest["coordinates"]:
        response = (
            _directory(coordinate)
            / "candidates/candidate-000/bem/responses.npz"
        )
        values = _diagnostics(response)
        rows.append({
            **coordinate,
            "response_path": str(response.relative_to(ROOT)),
            "response_sha256": _digest_file(response),
            "surface_score_v2_3": values["surface_score_v2_3"],
            "surface_delta_points": (
                values["surface_score_v2_3"]
                - float(coordinate["incumbent"]["score_v2_3"])
            ),
            "throat_impedance_score": (
                values["throat_impedance"].get("overall_percent")
            ),
            "composite_score": (
                values["composite"].get("overall_percent")
                if values["composite"] else None
            ),
        })
    return rows


def analyze_initial() -> dict[str, Any]:
    rows = measured_initial()
    ordered = sorted(
        rows, key=lambda row: (-row["surface_delta_points"], row["id"]))
    best = ordered[0]
    decision = {
        "schema_version": 1,
        "study_id": "round-control-wide-coverage-closure-v1",
        "stage": "initial",
        "status": "complete",
        "candidate_count": len(rows),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "evidence": sorted(rows, key=lambda row: row["id"]),
        "best_initial_candidate": {
            key: best[key] for key in (
                "id", "coverage_deg", "mouth_mm", "length_mm", "k", "n",
                "derived_s", "surface_score_v2_3", "surface_delta_points",
            )
        },
        "conditional_authorized": (
            best["surface_delta_points"] >= IMPROVEMENT_THRESHOLD
        ),
        "conditional_branch": (
            "confirm-or-bracket-improvement"
            if best["surface_delta_points"] >= IMPROVEMENT_THRESHOLD
            else "infinite-baffle-mechanism-comparison"
        ),
        "remaining_candidate_budget": HARD_CANDIDATE_CAP-len(rows),
        "ranking_authority": "surface_score_v2.3",
        "throat_impedance_used_in_decision": False,
        "composite_used_in_decision": False,
    }
    decision["content_sha256"] = _content_hash(decision)
    _write_json(STUDY_ROOT / "initial_results.json", decision)
    refresh_index()
    return decision


def finalize_without_conditional() -> dict[str, Any]:
    initial_path = STUDY_ROOT / "initial_results.json"
    if not initial_path.is_file():
        raise ValueError("initial results must be analyzed before finalization")
    initial = _read_json(initial_path)
    result = {
        "schema_version": 1,
        "study_id": "round-control-wide-coverage-closure-v1",
        "status": "complete-initial-user-stopped",
        "completed_candidate_count": int(initial["candidate_count"]),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "conditional_candidate_count": 0,
        "conditional_status": "declined-by-user-not-run",
        "decision_date": "2026-07-24",
        "decision": (
            "Do not pursue additional simulations on this issue at this time."
        ),
        "leading_provisional_mechanism": (
            "mouth-edge diffraction: wider coverage sends more acoustic energy "
            "to the lip, and the measured disturbance follows aperture-scaled "
            "frequency rather than a simple axial-length scale"
        ),
        "initial_results": str(initial_path.relative_to(ROOT)),
        "initial_results_sha256": _digest_file(initial_path),
        "best_initial_candidate": initial["best_initial_candidate"],
        "initial_improvement_threshold_reached": bool(
            initial["conditional_authorized"]),
        "ranking_authority": "surface_score_v2.3",
        "throat_impedance_used_in_decision": False,
        "composite_used_in_decision": False,
        "forward_action": (
            "carry the measured cell map forward and proceed to intended "
            "non-round H/V, corner, sag, and baffle geometry"
        ),
    }
    result["content_sha256"] = _content_hash(result)
    _write_json(STUDY_ROOT / "results.json", result)
    refresh_index()
    return result


def status() -> dict[str, Any]:
    if not (STUDY_ROOT / "initial_manifest.json").is_file():
        return {"status": "not-prepared", "complete_candidates": 0,
                "scheduled_candidates": 0}
    manifest = _verify_manifest()
    rows = []
    for coordinate, search in zip(
            manifest["coordinates"], _search_paths(manifest)):
        state_path = search.parent / "search_state.json"
        state = _read_json(state_path) if state_path.is_file() else {}
        candidates = state.get("candidates", [])
        complete = sum(row.get("status") == "complete" for row in candidates)
        rows.append({
            "id": coordinate["id"],
            "status": state.get("status", "not-started"),
            "complete_candidates": complete,
        })
    return {
        "status": "complete" if all(
            row["complete_candidates"] == 1 for row in rows) else "in-progress",
        "summary": dict(Counter(row["status"] for row in rows)),
        "complete_candidates": sum(
            row["complete_candidates"] for row in rows),
        "scheduled_candidates": len(rows),
        "hard_candidate_cap": HARD_CANDIDATE_CAP,
        "rows": rows,
    }


def _report_link(directory: Path) -> str | None:
    reports = sorted(
        (directory / "candidates/candidate-000/bem").glob("*_Report.html"))
    return (
        os.path.relpath(reports[0], STUDY_ROOT)
        if reports else None
    )


def refresh_index() -> Path:
    STUDY_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = STUDY_ROOT / "initial_manifest.json"
    if not manifest_path.is_file():
        coordinates = initial_coordinates()
        freeze = "not frozen"
    else:
        manifest = _read_json(manifest_path)
        coordinates = manifest["coordinates"]
        freeze = manifest["freeze_sha256"]
    runtime_path = STUDY_ROOT / "initial_runtime.json"
    runtime = _read_json(runtime_path) if runtime_path.is_file() else {}
    rows = []
    complete = 0
    for coordinate in coordinates:
        directory = _directory(coordinate)
        state_path = directory / "search_state.json"
        state = _read_json(state_path) if state_path.is_file() else {}
        candidates = state.get("candidates", [])
        record = candidates[0] if candidates else {}
        is_complete = record.get("status") == "complete"
        complete += int(is_complete)
        score = None
        impedance = None
        composite = None
        if is_complete:
            active = surface_score(record.get("surface_diagnostics", {}), {
                "horizontal": coordinate["mouth_mm"],
                "vertical": coordinate["mouth_mm"],
            })
            score = active.get("overall_percent") if active else None
            imp = record.get("throat_impedance_diagnostics", {})
            impedance = imp.get("overall_percent")
            comp = composite_surface_impedance_score(active, imp)
            composite = comp.get("overall_percent") if comp else None
        link = _report_link(directory)
        label = html.escape(coordinate["id"])
        if link:
            label = f"<a href='{html.escape(link)}'>{label}</a>"
        delta = (
            score-float(coordinate["incumbent"]["score_v2_3"])
            if score is not None else None
        )
        number = lambda value, digits=2: (
            "—" if value is None else f"{float(value):.{digits}f}"
        )
        candidate_status = record.get(
            "status", state.get("status", "not started"))
        numeric = lambda value: (
            "" if value is None else f"{float(value):.12g}"
        )
        rows.append(
            "<tr>"
            f"<td data-sort='{html.escape(coordinate['id'])}'>{label}</td>"
            f"<td data-sort='{html.escape(candidate_status)}'>"
            f"{html.escape(candidate_status)}</td>"
            f"<td data-sort='{coordinate['coverage_deg']*1000+coordinate['mouth_mm']}'>"
            f"{coordinate['coverage_deg']}° / {coordinate['mouth_mm']} mm</td>"
            f"<td data-sort='{coordinate['length_mm']}'>{coordinate['length_mm']:.3f}</td>"
            f"<td data-sort='{coordinate['k']}'>{coordinate['k']:g}</td>"
            f"<td data-sort='{coordinate['n']}'>{coordinate['n']:g}</td>"
            f"<td data-sort='{coordinate['derived_s']}'>{coordinate['derived_s']:.4f}</td>"
            f"<td data-sort='{numeric(score)}'>{number(score)}</td>"
            f"<td data-sort='{numeric(delta)}'>{number(delta)}</td>"
            f"<td data-sort='{numeric(impedance)}'>{number(impedance)}</td>"
            f"<td data-sort='{numeric(composite)}'>{number(composite)}</td>"
            "</tr>"
        )
    final_path = STUDY_ROOT / "results.json"
    final = _read_json(final_path) if final_path.is_file() else {}
    runtime_status = final.get("status") or runtime.get(
        "status", "prepared" if manifest_path.is_file() else "not prepared")
    conclusion = ""
    if final:
        conclusion = (
            "<section><h2>Conclusion</h2>"
            "<p>The ten initial candidates completed. The two conditional "
            "simulations were declined and were not run. The leading "
            "provisional mechanism is mouth-edge diffraction: wider coverage "
            "sends more energy to the lip, while the observed disturbance "
            "tracks aperture-scaled frequency.</p>"
            "<p>The best new result improved its incumbent by only "
            f"{float(final['best_initial_candidate']['surface_delta_points']):.2f} "
            "v2.3 points. Further round-horn sampling is stopped; the measured "
            "map is carried into the intended non-round geometry work.</p>"
            "</section>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Round-control wide-coverage closure</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1500px;margin:0 auto;padding:24px;background:#0d151d;color:#e8eef2}}
a{{color:#7fe7ff}} table{{border-collapse:collapse;width:100%}} th,td{{padding:8px;border-bottom:1px solid #33434f;text-align:right}} th:first-child,td:first-child{{text-align:left}} code{{overflow-wrap:anywhere}} .muted{{color:#aab8c1}} th[data-type]{{cursor:pointer;user-select:none}} th[data-type]::after{{content:" ↕";color:#718491}} th[aria-sort="ascending"]::after{{content:" ↑";color:#7fe7ff}} th[aria-sort="descending"]::after{{content:" ↓";color:#7fe7ff}}
</style></head><body>
<h1>Round-control wide-coverage closure</h1>
<p>Status: <strong>{html.escape(str(runtime_status))}</strong> · completed
<strong>{complete} / {len(coordinates)}</strong> initial candidates.</p>
<p>Surface score <strong>v2.3</strong> is authoritative. Throat impedance and
the 75/25 composite are reported only and do not affect ranking.</p>
<p class="muted">Frozen manifest: <code>{html.escape(freeze)}</code> ·
hard study cap: {HARD_CANDIDATE_CAP}</p>
<table id="candidate-table"><thead><tr>
<th data-type="text">Candidate report</th><th data-type="text">Status</th>
<th data-type="number">Cell</th><th data-type="number">L mm</th>
<th data-type="number">K</th><th data-type="number">N</th>
<th data-type="number">Derived S</th><th data-type="number">Surface v2.3</th>
<th data-type="number">Δ vs incumbent</th>
<th data-type="number">Impedance</th><th data-type="number">Composite</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
{conclusion}
<p><a href="../../docs/plans/round_control_wide_coverage_closure.md">Study plan</a></p>
<script>
document.querySelectorAll('#candidate-table th[data-type]').forEach((header, index) => {{
  header.tabIndex = 0;
  const sort = () => {{
    const table = header.closest('table');
    const ascending = header.getAttribute('aria-sort') !== 'ascending';
    table.querySelectorAll('th').forEach(item => item.removeAttribute('aria-sort'));
    header.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    const rows = Array.from(table.tBodies[0].rows);
    const type = header.dataset.type;
    rows.sort((left, right) => {{
      let a = left.cells[index].dataset.sort ?? left.cells[index].textContent;
      let b = right.cells[index].dataset.sort ?? right.cells[index].textContent;
      if (type === 'number') {{
        a = a === '' ? Number.NEGATIVE_INFINITY : Number(a);
        b = b === '' ? Number.NEGATIVE_INFINITY : Number(b);
      }}
      const order = a < b ? -1 : a > b ? 1 : 0;
      return ascending ? order : -order;
    }});
    table.tBodies[0].replaceChildren(...rows);
  }};
  header.addEventListener('click', sort);
  header.addEventListener('keydown', event => {{
    if (event.key === 'Enter' || event.key === ' ') {{
      event.preventDefault();
      sort();
    }}
  }});
}});
</script>
</body></html>"""
    path = STUDY_ROOT / "index.html"
    path.write_text(document, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "prepare-initial", "preflight", "run-initial", "analyze-initial",
        "finalize-without-conditional", "status", "report",
    ))
    args = parser.parse_args()
    if args.command == "prepare-initial":
        result: Any = prepare_initial()
    elif args.command == "preflight":
        result = preflight()
    elif args.command == "run-initial":
        result = run_initial()
    elif args.command == "analyze-initial":
        result = analyze_initial()
    elif args.command == "finalize-without-conditional":
        result = finalize_without_conditional()
    elif args.command == "status":
        result = status()
    else:
        result = {"index": str(refresh_index().relative_to(ROOT))}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
