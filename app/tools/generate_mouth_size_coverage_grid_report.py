#!/usr/bin/env python3
"""Generate an overview report for the mouth-size/coverage survey grid."""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import os
from pathlib import Path
from statistics import fmean
import threading
from typing import Any

import yaml

try:
    from .analyze_bem_design_space import (
        analyze as analyze_design_space, render_markdown)
    from .surface_diagnostics import surface_score
except ImportError:
    from analyze_bem_design_space import analyze as analyze_design_space, render_markdown
    from surface_diagnostics import surface_score


SUPPORTED_COVERAGE_MIN_DEG = 25.0
SUPPORTED_COVERAGE_MAX_DEG = 50.0
SUPPORTED_MOUTH_MIN_MM = 250.0
SUPPORTED_MOUTH_MAX_MM = 500.0


LEGACY_RANKING_KEYS = (
    "coverage_match_percent",
    "coverage_smoothness_percent",
    "waist_stability_percent",
    "window_uniformity_percent",
)
NEAR_DUPLICATE_LENGTH_MM = 1.0
STUDY_PHASES = {
    "original": (1, "Phase 1 · baseline / S closure"),
    "uniform S grid": (1, "Phase 1 · baseline / S closure"),
    "S boundary closure": (1, "Phase 1 · baseline / S closure"),
    "adaptive K/N grid": (2, "Phase 2 · K/N grid / S extension"),
    "canonical S extension": (2, "Phase 2 · K/N grid / S extension"),
    "coupled K/N closure": (3, "Phase 3 · coupled refinement"),
    "coupled local S": (3, "Phase 3 · coupled refinement"),
}


def _candidate_geometry_key(item: dict[str, Any]) -> tuple[float, ...]:
    """Return the physical inputs that must match before lengths are compared."""
    summary = item["search"]
    values = item["candidate"].get("values", {})
    return tuple(round(float(value), 6) for value in (
        summary["mouth_width"], summary["mouth_height"],
        values.get("extension_mm", 0),
        values.get("osse_coverage_h_deg", 0),
        values.get("osse_coverage_v_deg", 0),
        values.get("k_h", 0), values.get("k_v", 0),
        values.get("n_h", 0), values.get("n_v", 0),
    ))


def _deduplicate_candidate_rows(
        rows: list[dict[str, Any]],
        tolerance_mm: float = NEAR_DUPLICATE_LENGTH_MM) -> list[dict[str, Any]]:
    """Keep the best-scoring representative of near-identical candidates."""
    groups: dict[tuple[float, ...], list[dict[str, Any]]] = {}
    for item in rows:
        groups.setdefault(_candidate_geometry_key(item), []).append(item)
    retained = []
    for group in groups.values():
        selected: list[dict[str, Any]] = []
        ordered = sorted(group, key=lambda item: (
            item["surface_ranking_score"] is None,
            -(item["surface_ranking_score"] or 0),
            float(item["candidate"].get("values", {}).get("length_mm", 0)),
        ))
        for item in ordered:
            length = float(item["candidate"].get("values", {}).get("length_mm", 0))
            if any(abs(length - float(other["candidate"].get(
                    "values", {}).get("length_mm", 0))) <= tolerance_mm
                   for other in selected):
                continue
            selected.append(item)
        retained.extend(selected)
    return retained


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
    if mouth_dir.endswith("-canonical-s"):
        study_label = "canonical S extension"
    elif "-s-boundary-r" in mouth_dir:
        study_label = "S boundary closure"
    elif "-coupled-" in mouth_dir and mouth_dir.endswith("-kn"):
        study_label = "coupled K/N closure"
    elif "-coupled-" in mouth_dir and mouth_dir.endswith("-s"):
        study_label = "coupled local S"
    elif mouth_dir.endswith("-s-grid"):
        study_label = "uniform S grid"
    elif mouth_dir.endswith("-kn-grid"):
        study_label = "adaptive K/N grid"
    else:
        study_label = "original"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))["bem_candidate_search"]
    seed_path = Path(config.get("seed_yaml", "project.yaml"))
    if not seed_path.is_absolute():
        seed_path = path.parent / seed_path
    seed_global = {}
    seed_horizontal = {}
    if seed_path.is_file():
        seed_document = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
        seed_global = seed_document.get("horncad_config", {}).get("global", {})
        seed_horizontal = seed_document.get("horncad_config", {}).get(
            "horizontal_basis", {})
    if study_label == "S boundary closure":
        round_label = mouth_dir.rsplit("-s-boundary-", 1)[-1]
        target_s = seed_horizontal.get("solved_s")
        s_detail = (f" · S={float(target_s):g}"
                    if isinstance(target_s, (int, float)) else "")
        study_detail = f" · S boundary closure {round_label}{s_detail}"
    else:
        study_detail = {
            "uniform S grid": " · uniform S grid",
            "adaptive K/N grid": " · adaptive K/N grid",
            "canonical S extension": " · canonical S extension",
            "coupled K/N closure": " · coupled K/N closure",
            "coupled local S": " · coupled local S",
        }.get(study_label, "")
    state_path = path.parent / "search_state.json"
    report_path = path.parent / "search_report.html"
    summary: dict[str, Any] = {
        "coverage": coverage,
        "mouth": mouth,
        "mouth_width": float(seed_global.get("mouth_width", mouth)),
        "mouth_height": float(seed_global.get("mouth_height", mouth)),
        "label": (
            f"{coverage:g} deg\u00a0/\u200b {mouth:g} mm"
            + study_detail
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
    search_paths = [
        path for path in sorted(project_root.glob("*deg/*x*/search.yaml"))
        if SUPPORTED_COVERAGE_MIN_DEG <=
        float(path.parent.parent.name.removesuffix("deg")) <=
        SUPPORTED_COVERAGE_MAX_DEG and
        SUPPORTED_MOUTH_MIN_MM <= float(path.parent.name.split("x", 1)[0]) <=
        SUPPORTED_MOUTH_MAX_MM
    ]
    summaries = [_search_summary(path) for path in search_paths]
    learning = analyze_design_space(project_root)
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
    candidate_rows = _deduplicate_candidate_rows(candidate_rows)
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

    best_by_design: dict[tuple[float, float], dict[str, Any]] = {}
    for row in candidate_rows:
        if row["surface_ranking_score"] is None:
            continue
        key = (row["search"]["mouth"], row["search"]["coverage"])
        best_by_design.setdefault(key, row)

    summaries_by_design: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for summary in summaries:
        summaries_by_design.setdefault(
            (summary["mouth"], summary["coverage"]), []).append(summary)
    closure_by_design: dict[tuple[float, float], str] = {}
    closure_path = project_root / "s_boundary_closure.json"
    if closure_path.is_file():
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        for result in closure.get("results", []):
            parts = Path(str(result.get("baseline", ""))).parts
            if len(parts) < 2:
                continue
            try:
                coverage = float(parts[0].removesuffix("deg"))
                mouth = float(parts[1].split("x", 1)[0])
            except ValueError:
                continue
            closure_by_design[(mouth, coverage)] = str(result.get("status", ""))

    design_coverages = sorted({summary["coverage"] for summary in summaries})
    design_mouths = sorted({summary["mouth"] for summary in summaries})
    design_map_rows = []
    for mouth in design_mouths:
        cells = [f"<th scope='row'>{mouth:g} mm</th>"]
        for coverage in design_coverages:
            key = (mouth, coverage)
            winner = best_by_design.get(key)
            cell_summaries = summaries_by_design.get(key, [])
            if winner is None:
                cells.append("<td class='design-cell unmeasured'><span class='design-state'>unmeasured</span></td>")
                continue
            score = float(winner["surface_ranking_score"])
            candidate = winner["candidate"]
            values = candidate.get("values", {})
            derived = candidate.get("derived", {})
            length = float(values.get("length_mm", 0))
            s_value = fmean((float(derived.get("s_h", 0)),
                             float(derived.get("s_v", 0))))
            k_value = fmean((float(values.get("k_h", 0)),
                             float(values.get("k_v", 0))))
            n_value = fmean((float(values.get("n_h", 0)),
                             float(values.get("n_v", 0))))
            closure_status = closure_by_design.get(key)
            has_running = any(item["status"] == "running" for item in cell_summaries)
            has_refinement = any(
                item["status"] == "complete" and item["study"] in {
                    "adaptive K/N grid", "coupled K/N closure", "coupled local S"}
                for item in cell_summaries)
            baseline_complete = any(
                item["status"] == "complete" and item["study"] == "uniform S grid"
                for item in cell_summaries)
            if closure_status == "boundary-limited":
                state, state_class = "boundary limited", "limited"
            elif has_running or not baseline_complete:
                state, state_class = "provisional", "provisional"
            elif has_refinement:
                state, state_class = "refined", "refined"
            elif closure_status == "closed":
                state, state_class = "S bounded", "bounded"
            else:
                state, state_class = "S complete", "baseline"
            score_class = ("excellent" if score >= 90 else "good" if score >= 85
                           else "fair" if score >= 80 else "low")
            report_path = winner.get("report_path")
            score_text = f"{score:.1f}"
            if report_path is not None:
                score_text = (f"<a href='{html.escape(str(report_path.relative_to(project_root)))}'>"
                              f"{score_text}</a>")
            cells.append(
                f"<td class='design-cell {score_class}'>"
                f"<strong class='design-score'>{score_text}</strong>"
                f"<span class='design-state {state_class}'>{state}</span>"
                f"<span>L {length:.1f} mm · W/L {mouth / length:.2f}</span>"
                f"<span>S {s_value:.2f} · K {k_value:g} · N {n_value:g}</span>"
                "</td>")
        design_map_rows.append("<tr>" + "".join(cells) + "</tr>")
    design_map_header = "".join(
        f"<th scope='col'>{coverage:g}°</th>" for coverage in design_coverages)
    design_map_html = (
        "<table class='design-map'><thead><tr><th>Mouth / coverage</th>" +
        design_map_header + "</tr></thead><tbody>" +
        "".join(design_map_rows) + "</tbody></table>")

    sampling_points = []
    for row in candidate_rows:
        candidate = row["candidate"]
        derived = candidate.get("derived", {})
        values = candidate.get("values", {})
        axes = (derived.get("s_h"), derived.get("s_v"), values.get("k_h"),
                values.get("k_v"), values.get("n_h"), values.get("n_v"))
        if row["surface_ranking_score"] is None or not all(
                isinstance(value, (int, float)) for value in axes):
            continue
        report_path = row.get("report_path")
        sampling_points.append({
            "mouth": row["search"]["mouth"],
            "coverage": row["search"]["coverage"],
            "s": fmean((float(axes[0]), float(axes[1]))),
            "k": fmean((float(axes[2]), float(axes[3]))),
            "n": fmean((float(axes[4]), float(axes[5]))),
            "score": float(row["surface_ranking_score"]),
            "candidate": row["artifact_stem"],
            "report": (str(report_path.relative_to(project_root))
                       if report_path is not None else ""),
        })
    sampling_groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for point in sampling_points:
        sampling_groups.setdefault((point["mouth"], point["coverage"]), []).append(point)
    default_sampling_key = max(
        sampling_groups, key=lambda key: (len(sampling_groups[key]),
                                          -abs(key[0] - 400), -abs(key[1] - 45)))
    sampling_rows = []
    for mouth in design_mouths:
        cells = [f"<th scope='row'>{mouth:g} mm</th>"]
        for coverage in design_coverages:
            points = sampling_groups.get((mouth, coverage), [])
            if not points:
                cells.append("<td class='sampling-empty'>—</td>")
                continue
            def extent(name: str) -> str:
                extent_values = [float(point[name]) for point in points]
                return f"{min(extent_values):g}–{max(extent_values):g}"
            active = " active" if (mouth, coverage) == default_sampling_key else ""
            cells.append(
                f"<td><button type='button' class='sampling-cell{active}' "
                f"data-sampling-key='{mouth:g}:{coverage:g}'>"
                f"<strong>{len(points)}</strong><span>S {extent('s')}</span>"
                f"<span>K {extent('k')} · N {extent('n')}</span></button></td>")
        sampling_rows.append("<tr>" + "".join(cells) + "</tr>")
    sampling_matrix_html = (
        "<table class='sampling-matrix'><thead><tr><th>Mouth / coverage</th>" +
        design_map_header + "</tr></thead><tbody>" +
        "".join(sampling_rows) + "</tbody></table>")
    sampling_data_json = json.dumps(sampling_points, separators=(",", ":"))
    default_sampling_json = json.dumps(
        f"{default_sampling_key[0]:g}:{default_sampling_key[1]:g}")

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
            f"<tr data-coverage-angle='{summary['coverage']:g}'>"
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

    status_order = {"running": 0, "active": 0, "planned": 1, "queued": 1,
                    "not started": 1,
                    "conditional": 2, "complete": 3, "failed": 4}
    summary_entries = []
    for summary in summaries:
        phase_order, phase_label = STUDY_PHASES.get(
            summary["study"], (9, "Outside unified queue"))
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(summary['status'])}</span>"
        completed_at = summary.get("completed_at_unix")
        completed_sort = (f"{float(completed_at):.6f}"
                          if isinstance(completed_at, (int, float)) else "")
        completed_text = (datetime.fromtimestamp(float(completed_at)).astimezone().strftime(
            "%-m-%d %H:%M") if isinstance(completed_at, (int, float)) else "—")
        summary_entries.append((
            status_order.get(summary["status"], 2), phase_order, summary["label"],
            f"{summary['coverage']:g}",
            "<tr data-subsearch-coverage-angle='{}'>"
            f"<td data-sort='{phase_order}'>{html.escape(phase_label)}</td>"
            f"<td>{html.escape(summary['label'])}</td>"
            f"<td>{status_badge}</td>"
            f"<td data-sort='{completed_sort}'>{completed_text}</td>"
            f"<td>{summary['completed']}&nbsp;/<wbr> {summary['failed']}"
            f"&nbsp;/<wbr> {summary['proposal_count']}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        ))
    program_state_path = project_root / "study_program_state.json"
    program_state = {}
    if program_state_path.is_file():
        try:
            program_state = json.loads(program_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            program_state = {}
    program_status = str(program_state.get("status", "not started"))
    current_phase = str(program_state.get("phase", "baseline-and-s-closure"))
    current_phase_order = {
        "baseline-and-s-closure": 1,
        "kn-grids-and-canonical-extensions": 2,
        "coupled": 3,
    }.get(current_phase, 0)

    plan_path = project_root / "study_plan.yaml"
    planned = (yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}).get(
        "planned_subsearches", []) if plan_path.is_file() else []
    for item in planned:
        prerequisite = item.get("prerequisite")
        planned_status = str(item.get("status", "planned"))
        detail = (f"<br><span class='muted'>Requires: {html.escape(str(prerequisite))}</span>"
                  if prerequisite else "")
        angles = " ".join(str(value) for value in item.get("coverage_angles", []))
        phase_order = int(item.get("phase", 9))
        if program_status == "complete" or phase_order < current_phase_order:
            continue
        phase_label = str(item.get("phase_label", f"Phase {phase_order}"))
        summary_entries.append((
            status_order.get(planned_status, 1), phase_order,
            str(item["label"]), angles,
            "<tr data-subsearch-coverage-angle='{}'>"
            f"<td data-sort='{phase_order}'>{html.escape(phase_label)}</td>"
            f"<td>{html.escape(str(item['label']))}{detail}</td>"
            f"<td><span class='badge pending'>{html.escape(planned_status)}</span></td>"
            "<td data-sort=''>—</td><td>—</td><td>—</td>"
            "</tr>"
        ))
    summary_entries.sort(key=lambda item: (item[0], item[1], item[2]))
    summary_rows = [entry[4].format(html.escape(entry[3]))
                    for entry in summary_entries]

    phase_display = {
        "baseline-and-s-closure": "Phase 1 · baseline / S closure",
        "kn-grids-and-canonical-extensions": "Phase 2 · K/N grids / S extensions",
        "coupled": "Phase 3 · coupled refinement",
    }.get(current_phase, current_phase)

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
    coverage_angles = sorted({float(item["search"]["coverage"])
                              for item in candidate_rows})
    angle_filters = (
        "<button type='button' class='angle-filter' data-angle-filter='all' "
        "aria-pressed='true'>All angles</button>" + "".join(
            f"<button type='button' class='angle-filter' "
            f"data-angle-filter='{angle:g}' aria-pressed='false'>{angle:g}°</button>"
            for angle in coverage_angles
        )
    )
    subsearch_angles = sorted({summary["coverage"] for summary in summaries} |
                              {float(angle) for item in planned
                               for angle in item.get("coverage_angles", [])})
    subsearch_angle_filters = (
        "<button type='button' class='angle-filter' data-subsearch-angle-filter='all' "
        "aria-pressed='true'>All angles</button>" + "".join(
            f"<button type='button' class='angle-filter' "
            f"data-subsearch-angle-filter='{angle:g}' aria-pressed='false'>{angle:g}°</button>"
            for angle in subsearch_angles
        )
    )
    learning_effects = learning["matched_effects"]
    fixed_cells = learning["fixed_k4_n10_cells"]
    endpoint_cells = sum(cell["winner_at_sampled_boundary"] for cell in fixed_cells)
    learning_cards = "".join(
        f"<div class='card'><strong>{html.escape(parameter.upper())} "
        f"{effect.get('median_delta', {}).get('score', 0):+.2f}</strong>"
        f"median adjacent score change · {effect['count']} matched pairs</div>"
        for parameter, effect in learning_effects.items()
    )

    document = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh}
<title>Mouth-size / coverage grid</title><style>
:root{{color-scheme:dark;--bg:#0c1014;--panel:#121820;--panel-2:#161f29;--ink:#e5edf2;--muted:#94a3ad;--line:#2b3844;--line-soft:#22303b;--accent:#69d6c8;--good:#16856b;--warn:#b7791f;--bad:#b45353}}
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}main{{width:100%;padding:20px}}
h1,h2,h3{{margin:0 0 12px}}p{{line-height:1.45}}a{{color:var(--accent)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:14px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{background:var(--panel-2);white-space:nowrap}}
.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-bottom:4px}}
.learning-cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}}.learning-cards .card{{background:var(--panel-2);font-size:.85rem;color:var(--muted)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.9rem;text-transform:uppercase;letter-spacing:.02em}}.badge.complete{{background:rgba(22,133,107,.18);color:#8de8cc}}.badge.running{{background:rgba(183,121,31,.2);color:#f6d39a}}.badge.failed{{background:rgba(180,83,83,.2);color:#ffb2b2}}.badge.pending{{background:rgba(148,163,189,.16);color:#c8d0d8}}
.best{{background:#173c39;color:#9af0df;font-weight:700}}.worst{{background:#482321;color:#ffaaa3;font-weight:700}}
.wide td:nth-child(5), .wide td:nth-child(6), .wide td:nth-child(7), .wide td:nth-child(8), .wide td:nth-child(9){{white-space:nowrap}}
.sortable{{cursor:pointer;user-select:none}}.axis-pair{{white-space:normal}}[hidden]{{display:none!important}}
.column-controls,.angle-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 12px}}.column-toggle,.angle-filter{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true'],.angle-filter[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}.filter-count{{margin-left:5px;color:var(--muted);font-size:.9rem}}
.show-more{{display:block;margin:14px auto 2px;border:1px solid var(--accent);border-radius:999px;padding:8px 16px;background:#173c39;color:var(--ink);cursor:pointer}}
.design-map{{table-layout:fixed;min-width:1100px}}.design-map th:first-child{{width:210px;overflow:hidden}}.design-cell{{min-width:142px;border:1px solid var(--line);background:#17212a}}.design-cell>span{{display:block;margin-top:4px;font-size:.82rem;color:#c1cbd2;white-space:nowrap}}.design-score{{display:block;font-size:1.5rem;line-height:1}}.design-score a{{color:inherit;text-decoration:none}}.design-cell.excellent{{background:#174638}}.design-cell.good{{background:#173c3c}}.design-cell.fair{{background:#3d3820}}.design-cell.low{{background:#452827}}.design-cell.unmeasured{{background:#131920;text-align:center;vertical-align:middle}}.design-state{{width:max-content;padding:2px 6px;border-radius:999px;text-transform:uppercase;letter-spacing:.03em;font-size:.68rem!important}}.design-state.refined,.design-state.bounded{{background:rgba(105,214,200,.16);color:#9af0df}}.design-state.baseline{{background:rgba(148,163,189,.16);color:#c8d0d8}}.design-state.provisional{{background:rgba(183,121,31,.25);color:#f6d39a}}.design-state.limited{{background:rgba(180,83,83,.25);color:#ffb2b2}}
.sampling-matrix{{table-layout:fixed;min-width:1100px}}.sampling-matrix th:first-child{{width:210px}}.sampling-matrix td{{padding:3px}}.sampling-cell{{width:100%;min-height:68px;border:1px solid transparent;border-radius:6px;padding:7px;background:#17212a;color:var(--ink);text-align:left;cursor:pointer}}.sampling-cell.active{{border-color:var(--accent);background:#173c39}}.sampling-cell strong,.sampling-cell span{{display:block}}.sampling-cell span{{margin-top:3px;color:var(--muted);font-size:.78rem;white-space:nowrap}}.sampling-empty{{color:var(--muted);text-align:center}}.sampling-views{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}.sampling-view{{min-width:0;background:#0d1319;border:1px solid var(--line);border-radius:8px;padding:8px}}.sampling-view h3{{font-size:1rem}}.sampling-canvas{{display:block;width:100%;height:390px;touch-action:none}}#sampling-3d{{cursor:grab}}#sampling-3d:active{{cursor:grabbing}}.sampling-caption{{color:var(--muted);font-size:.82rem;margin:6px 0 0}}#sampling-selection{{color:var(--accent)}}
.muted{{color:var(--muted)}}
@media(max-width:1100px){{.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:900px){{.sampling-views{{grid-template-columns:1fr}}}}
@media(max-width:700px){{.summary,.learning-cards{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Mouth-size / coverage grid</h1>
<p>Supported domain: 25°–50° half-coverage and 250–500 mm mouth size.</p>
<p class='muted'>Candidates are ranked by the final surface score. Previous rank and previous diagnostic score are shown beside it for direct comparison. The final score weights profile RMS error 30%, slice-energy departure 25%, mean containment 20%, outward-rise violation 15%, and the secondary −6 dB line 10%.</p>
<section class='summary'>
<div class='card'><strong>{started}&nbsp;/<wbr> {total}</strong> started</div>
<div class='card'><strong>{running}</strong> running sub-searches</div>
<div class='card'><strong>{complete}</strong> complete sub-searches</div>
<div class='card'><strong>{completed_candidates}</strong> completed candidates</div>
</section>
<section>
<h2>Provisional learning</h2>
<p>{learning['unique_candidate_count']} unique scored physical designs currently support {learning['mouth_coverage_cell_count']} mouth/coverage cells. {endpoint_cells} of {len(fixed_cells)} fixed K=4, N=10 cells still place their measured winner on an observed S endpoint.</p>
<div class='learning-cards'>{learning_cards}</div>
<p class='muted'>These are aggregate matched comparisons, not universal steering rules. Positive means increasing the control improved score at the median adjacent step. Regime-conditioned and held-out checks are required before using a direction to propose a horn.</p>
</section>
<section>
<h2>Project range</h2>
<table><tr><th>Coverage targets</th><th>Mouth sizes</th><th>Fixed K&nbsp;/ N</th><th>Sweep&nbsp;/ crossover</th><th>Length-mouth ratios</th></tr>
<tr><td>{coverage_targets} deg</td><td>{mouth_sizes} mm</td><td>K={fixed_k}, N={fixed_n}</td><td>{sweep_lower}-{sweep_upper} Hz&nbsp;/<wbr> {crossover} Hz</td><td>{", ".join(f"{ratio:g}" for ratio in ratios) if ratios != "—" else "—"}</td></tr></table>
</section>
<section>
<h2>Design map</h2>
<p class='muted'>Choose a mouth and target half-coverage, then open the best measured score in that cell. Parameters are the current best prescription; provisional cells may change as their searches finish.</p>
{design_map_html}
</section>
<section>
<h2>Sampling extent</h2>
<p class='muted'>Select a mouth/coverage cell to inspect measured S, K, and N coordinates. Counts and ranges include actual completed candidates only.</p>
{sampling_matrix_html}
<p><strong id='sampling-selection'></strong></p>
<div class='sampling-views'>
<div class='sampling-view'><h3>S × K, colored by N</h3><canvas id='sampling-2d' class='sampling-canvas'></canvas><p class='sampling-caption'>Point size increases with surface score. Click a point to open its candidate report.</p></div>
<div class='sampling-view'><h3>Measured S / K / N point cloud</h3><canvas id='sampling-3d' class='sampling-canvas'></canvas><p class='sampling-caption'>Drag to rotate; wheel to zoom. No interpolated surface is drawn.</p></div>
</div>
</section>
<section>
<h2>Candidates</h2>
<div class='angle-controls' aria-label='Filter candidates by coverage angle'>{angle_filters}<span id='candidate-filter-count' class='filter-count'>{len(candidate_rows)} candidates</span></div>
<div class='column-controls' aria-label='Candidate table columns'>{column_toggles}</div>
<table id='candidate-table' class='wide sortable-table'>
<thead><tr><th class='sortable' data-sort='text'>Candidate</th><th class='sortable' data-column='surface-score' data-sort='number'>Final surface score</th><th class='sortable' data-sort='number'>Date</th><th class='sortable' data-column='legacy-rank' hidden data-sort='number'>Previous rank</th><th class='sortable' data-column='legacy-score' hidden data-sort='number'>Previous diagnostic score</th><th class='sortable' data-column='containment-mean' hidden data-sort='number'>Mean containment H&nbsp;/ V</th><th class='sortable' data-column='profile-rms' hidden data-sort='number'>Profile RMS error H&nbsp;/ V</th><th class='sortable' data-column='outward-rise' hidden data-sort='number'>Outward-rise violation H&nbsp;/ V</th><th class='sortable' data-column='slice-rms' hidden data-sort='number'>Slice-energy RMS departure H&nbsp;/ V</th><th class='sortable' data-column='line-rms' hidden data-sort='number'>−6 dB RMS error H&nbsp;/ V</th><th class='sortable' data-column='length' hidden data-sort='number'>Length mm</th><th class='sortable' data-column='length-mouth-ratio' hidden data-sort='number'>Length-mouth ratio</th><th class='sortable' data-column='extension' hidden data-sort='number'>Extension mm</th><th class='sortable' data-column='osse' hidden data-sort='number'>OS-SE H&nbsp;/ V</th><th class='sortable' data-column='k' hidden data-sort='number'>K H&nbsp;/ V</th><th class='sortable' data-column='s' hidden data-sort='number'>S H&nbsp;/ V</th><th class='sortable' data-column='n' hidden data-sort='number'>N H&nbsp;/ V</th><th class='sortable' data-column='trait' hidden data-sort='text'>Distinguishing trait</th><th class='sortable' data-column='mouth-height' hidden data-sort='number'>Mouth height</th><th class='sortable' data-column='mouth-width' hidden data-sort='number'>Mouth width</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<button type='button' id='candidate-show-more' class='show-more'>Show 25 more</button>
</section>
<section>
<h2>Sub-searches</h2>
<p><strong>Unified queue:</strong> {html.escape(program_status)} · {html.escape(phase_display)}. Rows are initially grouped by live status and then execution phase.</p>
<div class='angle-controls' aria-label='Filter sub-searches by coverage angle'>{subsearch_angle_filters}<span id='subsearch-filter-count' class='filter-count'>{len(summary_rows)} sub-searches</span></div>
<table id='subsearch-table' class='sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>Queue phase</th><th class='sortable' data-sort='text'>Sub-search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Date complete</th><th class='sortable' data-sort='number'>Complete&nbsp;/ Failed&nbsp;/ Proposed</th><th>Links</th></tr></thead>
<tbody>{''.join(summary_rows)}</tbody>
</table>
</section>
<script>
(() => {{
  const samplingPoints = {sampling_data_json};
  let samplingKey = {default_sampling_json};
  let samplingYaw = -0.65, samplingPitch = 0.65, samplingZoom = 0.82, samplingDrag = null;
  let projected2d = [];
  const sampling2d = document.getElementById('sampling-2d');
  const sampling3d = document.getElementById('sampling-3d');
  const samplingSelection = document.getElementById('sampling-selection');
  const cellPoints = () => {{
    const [mouth, coverage] = samplingKey.split(':').map(Number);
    return samplingPoints.filter(point => point.mouth === mouth && point.coverage === coverage);
  }};
  const canvasContext = canvas => {{
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
    const context = canvas.getContext('2d'); context.setTransform(ratio,0,0,ratio,0,0);
    context.clearRect(0,0,rect.width,rect.height); return [context,rect];
  }};
  const limits = (points, name) => {{
    const values = points.map(point => point[name]);
    let low=Math.min(...values), high=Math.max(...values);
    const pad=Math.max((high-low)*.1,.08); return [low-pad,high+pad];
  }};
  const nColor = (n, range) => {{
    const fraction=(n-range[0])/Math.max(range[1]-range[0],1e-9);
    return `hsl(${{Math.round(190-fraction*150)}} 70% 62%)`;
  }};
  const drawSampling2d = () => {{
    const points=cellPoints(); if (!points.length) return;
    const [context,rect]=canvasContext(sampling2d), margin={{left:48,right:18,top:22,bottom:42}};
    const sRange=limits(points,'s'), kRange=limits(points,'k'), nRange=limits(points,'n');
    const sx=s=>margin.left+(s-sRange[0])/(sRange[1]-sRange[0])*(rect.width-margin.left-margin.right);
    const sy=k=>rect.height-margin.bottom-(k-kRange[0])/(kRange[1]-kRange[0])*(rect.height-margin.top-margin.bottom);
    context.strokeStyle='#263541'; context.fillStyle='#94a3ad'; context.font='11px system-ui';
    for(let i=0;i<5;i++){{const f=i/4,x=margin.left+f*(rect.width-margin.left-margin.right),y=margin.top+f*(rect.height-margin.top-margin.bottom);context.beginPath();context.moveTo(x,margin.top);context.lineTo(x,rect.height-margin.bottom);context.moveTo(margin.left,y);context.lineTo(rect.width-margin.right,y);context.stroke();context.fillText((sRange[0]+f*(sRange[1]-sRange[0])).toFixed(2),x-10,rect.height-20);context.fillText((kRange[1]-f*(kRange[1]-kRange[0])).toFixed(2),5,y+4);}}
    projected2d=points.map(point=>({{point,x:sx(point.s),y:sy(point.k)}}));
    for(const item of projected2d){{const radius=3+Math.max(0,item.point.score-70)*.08;context.beginPath();context.arc(item.x,item.y,radius,0,Math.PI*2);context.fillStyle=nColor(item.point.n,nRange);context.globalAlpha=.78;context.fill();context.globalAlpha=1;context.strokeStyle='#071015';context.stroke();}}
    context.fillStyle='#e5edf2';context.font='12px system-ui';context.fillText('S',rect.width/2,rect.height-5);context.save();context.translate(13,rect.height/2);context.rotate(-Math.PI/2);context.fillText('K',0,0);context.restore();context.fillStyle=nColor(nRange[0],nRange);context.fillText(`N ${{nRange[0].toFixed(1)}}`,margin.left,14);context.fillStyle=nColor(nRange[1],nRange);context.fillText(`N ${{nRange[1].toFixed(1)}}`,margin.left+58,14);
  }};
  const drawSampling3d = () => {{
    const points=cellPoints(); if (!points.length) return;
    const [context,rect]=canvasContext(sampling3d); const sRange=limits(points,'s'),kRange=limits(points,'k'),nRange=limits(points,'n');
    const normalized=point=>({{x:(point.s-sRange[0])/(sRange[1]-sRange[0])*2-1,y:(point.k-kRange[0])/(kRange[1]-kRange[0])*2-1,z:(point.n-nRange[0])/(nRange[1]-nRange[0])*2-1,point}});
    const scale=Math.min(rect.width,rect.height)*.3*samplingZoom;
    const project=value=>{{const x=value.x*Math.cos(samplingYaw)-value.y*Math.sin(samplingYaw),y=value.x*Math.sin(samplingYaw)+value.y*Math.cos(samplingYaw);return {{x:rect.width/2+x*scale,y:rect.height/2+(y*Math.cos(samplingPitch)-value.z*Math.sin(samplingPitch))*scale,depth:y*Math.sin(samplingPitch)+value.z*Math.cos(samplingPitch),point:value.point}};}};
    const projected=points.map(normalized).map(project).sort((a,b)=>a.depth-b.depth);
    context.strokeStyle='#30414d';context.beginPath();context.moveTo(rect.width*.15,rect.height*.82);context.lineTo(rect.width*.85,rect.height*.82);context.stroke();
    for(const item of projected){{context.beginPath();context.arc(item.x,item.y,3.8,0,Math.PI*2);context.fillStyle=nColor(item.point.n,nRange);context.globalAlpha=.82;context.fill();context.globalAlpha=1;context.strokeStyle='#071015';context.stroke();}}
    context.fillStyle='#94a3ad';context.font='12px system-ui';context.fillText('S / K / N measured coordinates',12,20);
  }};
  const renderSampling = () => {{
    const [mouth,coverage]=samplingKey.split(':'); const points=cellPoints();
    samplingSelection.textContent=`${{mouth}} mm / ${{coverage}}° — ${{points.length}} measured candidates`;
    document.querySelectorAll('[data-sampling-key]').forEach(button=>button.classList.toggle('active',button.dataset.samplingKey===samplingKey));
    drawSampling2d();drawSampling3d();
  }};
  document.querySelectorAll('[data-sampling-key]').forEach(button=>button.addEventListener('click',()=>{{samplingKey=button.dataset.samplingKey;renderSampling();}}));
  sampling2d.addEventListener('click',event=>{{const rect=sampling2d.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;const nearest=projected2d.reduce((best,item)=>{{const distance=Math.hypot(item.x-x,item.y-y);return !best||distance<best.distance?{{...item,distance}}:best;}},null);if(nearest&&nearest.distance<12&&nearest.point.report)location.href=nearest.point.report;}});
  sampling3d.addEventListener('pointerdown',event=>{{samplingDrag=[event.clientX,event.clientY];sampling3d.setPointerCapture(event.pointerId);}});
  sampling3d.addEventListener('pointermove',event=>{{if(!samplingDrag)return;samplingYaw+=(event.clientX-samplingDrag[0])*.008;samplingPitch=Math.max(.15,Math.min(1.3,samplingPitch+(event.clientY-samplingDrag[1])*.006));samplingDrag=[event.clientX,event.clientY];drawSampling3d();}});
  sampling3d.addEventListener('pointerup',()=>samplingDrag=null);
  sampling3d.addEventListener('wheel',event=>{{event.preventDefault();samplingZoom=Math.max(.55,Math.min(1.4,samplingZoom-event.deltaY*.001));drawSampling3d();}},{{passive:false}});
  window.addEventListener('resize',renderSampling);renderSampling();
  document.querySelectorAll('[data-column-toggle]').forEach((button) => {{
    button.addEventListener('click', () => {{
      const visible = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', String(visible));
      document.querySelectorAll(`[data-column="${{button.dataset.columnToggle}}"]`).forEach((cell) => {{
        cell.hidden = !visible;
      }});
    }});
  }});
  const candidateTable = document.getElementById('candidate-table');
  const candidateCount = document.getElementById('candidate-filter-count');
  const candidateShowMore = document.getElementById('candidate-show-more');
  let candidateAngle = 'all';
  let candidateLimit = 25;
  const renderCandidates = () => {{
    let matched = 0;
    let shown = 0;
    Array.from(candidateTable.tBodies[0].rows).forEach((row) => {{
      const matches = candidateAngle === 'all' || row.dataset.coverageAngle === candidateAngle;
      if (matches) matched += 1;
      const visible = matches && shown < candidateLimit;
      row.hidden = !visible;
      if (visible) shown += 1;
    }});
    candidateCount.textContent = `Showing ${{shown}} of ${{matched}} candidate${{matched === 1 ? '' : 's'}}`;
    candidateShowMore.hidden = shown >= matched;
  }};
  document.querySelectorAll('[data-angle-filter]').forEach((button) => {{
    button.addEventListener('click', () => {{
      candidateAngle = button.dataset.angleFilter;
      candidateLimit = 25;
      document.querySelectorAll('[data-angle-filter]').forEach((item) => {{
        item.setAttribute('aria-pressed', String(item === button));
      }});
      renderCandidates();
    }});
  }});
  candidateShowMore.addEventListener('click', () => {{
    candidateLimit += 25;
    renderCandidates();
  }});
  renderCandidates();
  const subsearchTable = document.getElementById('subsearch-table');
  const subsearchCount = document.getElementById('subsearch-filter-count');
  document.querySelectorAll('[data-subsearch-angle-filter]').forEach((button) => {{
    button.addEventListener('click', () => {{
      const selected = button.dataset.subsearchAngleFilter;
      let visible = 0;
      document.querySelectorAll('[data-subsearch-angle-filter]').forEach((item) => {{
        item.setAttribute('aria-pressed', String(item === button));
      }});
      Array.from(subsearchTable.tBodies[0].rows).forEach((row) => {{
        const angles = row.dataset.subsearchCoverageAngle.split(' ');
        row.hidden = selected !== 'all' && !angles.includes(selected);
        if (!row.hidden) visible += 1;
      }});
      subsearchCount.textContent = `${{visible}} sub-search${{visible === 1 ? '' : 'es'}}`;
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
      if (table === candidateTable) renderCandidates();
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
    temporary = output.with_name(
        f".{output.name}.{os.getpid()}.{threading.get_ident()}.tmp")
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
    # A long-lived study coordinator may have loaded an older report renderer.
    # Refresh active search reports here as well so their planned blank rows and
    # current presentation stay synchronized without restarting any solver.
    try:
        from .run_bem_search import write_report
    except ImportError:
        from run_bem_search import write_report
    for state_path in args.project_root.glob("*deg/*x*/search_state.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("status") == "running":
            write_report(state_path.parent, state)
    repository_root = Path(__file__).resolve().parents[2]
    maintained_root = repository_root / "examples" / "mouth-size-coverage-grid"
    if args.project_root.resolve() == maintained_root.resolve():
        analysis = analyze_design_space(args.project_root)
        analysis_root = repository_root / "docs" / "reference" / "research"
        artifacts = {
            analysis_root / "current_bem_design_space_analysis.json":
                json.dumps(analysis, indent=2) + "\n",
            analysis_root / "current_bem_design_space_analysis.md":
                render_markdown(analysis),
        }
        for path, document in artifacts.items():
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temporary.write_text(document, encoding="utf-8")
            temporary.replace(path)


if __name__ == "__main__":
    main()
