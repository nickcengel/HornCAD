#!/usr/bin/env python3
"""Generate an overview report for the mouth-size/coverage survey grid."""
from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

import numpy as np
import yaml

try:
    from .surface_diagnostics import surface_score
except ImportError:
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
PLOT_COLORS = ("#69d6c8", "#f6bd60", "#f28482", "#8e9aef", "#90be6d")
NEAR_DUPLICATE_LENGTH_MM = 1.0


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


def _nice_plot_bounds(lower: float, upper: float) -> tuple[float, float]:
    """Add 5% breathing room and round outward to readable tick bounds."""
    span = max(upper - lower, 1.0)
    buffered_lower = lower - span * 0.05
    buffered_upper = upper + span * 0.05
    rough_step = (buffered_upper - buffered_lower) / 5
    magnitude = 10 ** math.floor(math.log10(max(rough_step, 1e-9)))
    normalized = rough_step / magnitude
    nice_factor = 1 if normalized <= 1 else 2 if normalized <= 2 else 5 if normalized <= 5 else 10
    step = nice_factor * magnitude
    return (math.floor(buffered_lower / step) * step,
            math.ceil(buffered_upper / step) * step)


def _scatter_svg(points: list[dict[str, Any]], x_label: str, y_label: str,
                 *, trends: bool = False, label_points: bool = False) -> str:
    if not points:
        return "<p class='muted'>No completed candidates yet.</p>"
    width, height = 720, 390
    left, right, top, bottom = 64, 22, 24, 52
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    x_min, x_max = min(xs), max(xs)
    # Focus the comparison on the useful upper half of candidate performance.
    # Values below the study mean remain part of the fitted trends but fall below
    # the displayed score window.
    y_min, y_max = _nice_plot_bounds(fmean(ys), max(ys))
    x_pad = max((x_max - x_min) * .06, .05)
    x_min, x_max = x_min - x_pad, x_max + x_pad
    plot_width, plot_height = width - left - right, height - top - bottom
    plot_clip = "plot-" + "".join(
        character if character.isalnum() else "-"
        for character in x_label.lower()).strip("-")

    def sx(value: float) -> float:
        return left + (value - x_min) * plot_width / max(x_max - x_min, 1e-9)

    def sy(value: float) -> float:
        return top + (y_max - value) * plot_height / max(y_max - y_min, 1e-9)

    coverages = sorted({float(point["coverage"]) for point in points})
    colors = {coverage: PLOT_COLORS[index % len(PLOT_COLORS)]
              for index, coverage in enumerate(coverages)}
    parts = [f"<svg class='trend-plot' viewBox='0 0 {width} {height}' role='img' "
             f"data-y-min='{y_min:.6f}' data-y-max='{y_max:.6f}'>",
             f"<defs><clipPath id='{html.escape(plot_clip)}'><rect x='{left}' y='{top}' "
             f"width='{plot_width}' height='{plot_height}'/></clipPath></defs>"]
    for index in range(6):
        fraction = index / 5
        x_value = x_min + fraction * (x_max - x_min)
        y_value = y_min + fraction * (y_max - y_min)
        x = sx(x_value)
        y = sy(y_value)
        parts.append(f"<line class='plot-grid' x1='{x:.2f}' x2='{x:.2f}' y1='{top}' y2='{height-bottom}'/>")
        parts.append(f"<text class='plot-tick' x='{x:.2f}' y='{height-bottom+20}' text-anchor='middle'>{x_value:.2g}</text>")
        parts.append(f"<line class='plot-grid' x1='{left}' x2='{width-right}' y1='{y:.2f}' y2='{y:.2f}'/>")
        parts.append(f"<text class='plot-tick' x='{left-9}' y='{y+4:.2f}' text-anchor='end'>{y_value:.3g}</text>")
    parts.append(f"<g clip-path='url(#{html.escape(plot_clip)})'>")
    if trends:
        for coverage in coverages:
            group = [point for point in points if float(point["coverage"]) == coverage]
            unique_x = sorted({float(point["x"]) for point in group})
            if len(unique_x) < 2:
                continue
            degree = min(2, len(unique_x) - 1)
            coefficients = np.polyfit(
                [float(point["x"]) for point in group],
                [float(point["y"]) for point in group], degree)
            trend_x = np.linspace(min(unique_x), max(unique_x), 48)
            coordinates = " ".join(
                f"{sx(float(x)):.2f},{sy(float(np.polyval(coefficients, x))):.2f}"
                for x in trend_x)
            parts.append(f"<polyline class='plot-trend' stroke='{colors[coverage]}' points='{coordinates}'/>")
    for point in points:
        if not y_min <= float(point["y"]) <= y_max:
            continue
        coverage = float(point["coverage"])
        color = colors[coverage]
        radius = float(point.get("radius", 4.2))
        tooltip = html.escape(str(point.get("tooltip", "candidate")))
        candidate_name = html.escape(str(point.get("candidate", "candidate")), quote=True)
        stats = html.escape(str(point.get("stats", point.get("tooltip", ""))), quote=True)
        report = html.escape(str(point.get("report", "")), quote=True)
        parts.append(
            f"<circle class='scatter-point' tabindex='0' role='button' "
            f"aria-label='Open {candidate_name} details' data-candidate='{candidate_name}' "
            f"data-stats='{stats}' data-report='{report}' "
            f"cx='{sx(float(point['x'])):.2f}' cy='{sy(float(point['y'])):.2f}' "
            f"r='{radius:.2f}' fill='{color}'><title>{tooltip}</title></circle>")
        if label_points and point.get("label"):
            parts.append(
                f"<text class='plot-label' x='{sx(float(point['x']))+6:.2f}' "
                f"y='{sy(float(point['y']))-6:.2f}'>{html.escape(str(point['label']))}</text>")
    parts.append("</g>")
    parts.extend([
        f"<text class='plot-axis-label' x='{left + plot_width/2:.2f}' y='{height-8}' text-anchor='middle'>{html.escape(x_label)}</text>",
        f"<text class='plot-axis-label' transform='translate(17 {top + plot_height/2:.2f}) rotate(-90)' text-anchor='middle'>{html.escape(y_label)}</text>",
    ])
    legend_x = left + 8
    for coverage in coverages:
        parts.append(f"<circle cx='{legend_x}' cy='{top+10}' r='4' fill='{colors[coverage]}'/>")
        parts.append(f"<text class='plot-label' x='{legend_x+7}' y='{top+14}'>{coverage:g}°</text>")
        legend_x += 66
    parts.append("</svg>")
    return "".join(parts)


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
            + ({"uniform S grid": " · uniform S grid",
                "adaptive K/N grid": " · adaptive K/N grid",
                "canonical S extension": " · canonical S extension",
                "coupled K/N closure": " · coupled K/N closure",
                "coupled local S": " · coupled local S"}.get(
                    study_label, ""))
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

    score_vs_s = []
    score_vs_ratio = []
    score_vs_normalized_length = []
    kn_score_vs_k = []
    kn_score_vs_n = []
    kn_score_vs_ratio = []
    best_by_pair: dict[tuple[float, float], dict[str, Any]] = {}
    for row in candidate_rows:
        score = row["surface_ranking_score"]
        if score is None:
            continue
        candidate = row["candidate"]
        summary = row["search"]
        derived = candidate.get("derived", {})
        s_values = [derived.get("s_h"), derived.get("s_v")]
        s_value = (fmean(float(value) for value in s_values)
                   if all(isinstance(value, (int, float)) for value in s_values)
                   else None)
        length = float(candidate.get("values", {}).get("length_mm", 0))
        normalized_length = (
            2.0 * length * math.tan(math.radians(summary["coverage"])) /
            float(summary["mouth_width"]))
        tooltip = (f"{row['artifact_stem']} · {summary['coverage']:g}° · "
                   f"{summary['mouth']:g} mm · score {score:.1f}%")
        report_url = (str(row["report_path"].relative_to(project_root))
                      if row["report_path"] is not None else "")
        stats = (
            f"Score {score:.1f}% · Coverage {summary['coverage']:g}° · "
            f"Mouth {summary['mouth_width']:g} × {summary['mouth_height']:g} mm · "
            f"Length {length:g} mm · S {s_value:.3f} · "
            f"Mouth/length {row['length_mouth_ratio']:.3f} · "
            f"Normalized length {normalized_length:.3f}"
            if s_value is not None else
            f"Score {score:.1f}% · Coverage {summary['coverage']:g}° · "
            f"Mouth {summary['mouth_width']:g} × {summary['mouth_height']:g} mm · "
            f"Length {length:g} mm · Mouth/length {row['length_mouth_ratio']:.3f} · "
            f"Normalized length {normalized_length:.3f}")
        common = {"y": score, "coverage": summary["coverage"],
                  "tooltip": tooltip, "candidate": row["artifact_stem"],
                  "stats": stats, "report": report_url}
        if summary["study"] in {"adaptive K/N grid", "coupled K/N closure"}:
            values = candidate.get("values", {})
            k_value = fmean((float(values.get("k_h", 0)),
                             float(values.get("k_v", 0))))
            n_value = fmean((float(values.get("n_h", 0)),
                             float(values.get("n_v", 0))))
            kn_common = {**common, "stats": (
                f"{stats} · K {k_value:g} · N {n_value:g} · "
                f"K/N {k_value / n_value:.3f}")}
            if n_value > 0:
                kn_score_vs_ratio.append({**kn_common, "x": k_value / n_value})
            if math.isclose(n_value, 10.0, abs_tol=1e-6):
                kn_score_vs_k.append({**kn_common, "x": k_value})
            if math.isclose(k_value, 4.0, abs_tol=1e-6):
                kn_score_vs_n.append({**kn_common, "x": n_value})
        if s_value is not None:
            score_vs_s.append({**common, "x": s_value})
        score_vs_ratio.append({**common, "x": row["length_mouth_ratio"]})
        score_vs_normalized_length.append({**common, "x": normalized_length})
        pair_key = (summary["coverage"], summary["mouth"])
        if pair_key not in best_by_pair or score > best_by_pair[pair_key]["y"]:
            best_by_pair[pair_key] = {
                **common, "x": summary["mouth"],
                "label": f"S={s_value:.2g}" if s_value is not None else "",
            }

    trend_plots = (
        ("Final surface score vs S",
         "The broad equal-opportunity sweep; curves are quadratic visual trends, not fitted design laws.",
         _scatter_svg(score_vs_s, "Derived S", "Final surface score (%)", trends=True)),
        ("Final surface score vs mouth/length ratio",
         "Translates the S sweep into the practical relative-length constraint.",
         _scatter_svg(score_vs_ratio, "Mouth width / length", "Final surface score (%)", trends=True)),
        ("Best score vs mouth width",
         "Best completed candidate for each mouth/coverage pair; labels report its S value.",
         _scatter_svg(list(best_by_pair.values()), "Mouth width (mm)",
                      "Best final surface score (%)", trends=True,
                      label_points=True)),
        ("Final surface score vs coverage-normalized length",
         "X = 2 × length × tan(coverage half-angle) / mouth width; curves test whether coverage families share a geometric constraint.",
         _scatter_svg(score_vs_normalized_length, "Coverage-normalized length",
                      "Final surface score (%)", trends=True)),
        ("K behavior at N=10",
         "Adaptive-study axis runs isolate the K trend while holding each anchor's mouth, length, coverage, and N fixed.",
         _scatter_svg(kn_score_vs_k, "K", "Final surface score (%)", trends=True)),
        ("N behavior at K=4",
         "Adaptive-study axis runs isolate the N trend; outer values appear only when the measured local trend remains competitive.",
         _scatter_svg(kn_score_vs_n, "N", "Final surface score (%)", trends=True)),
        ("Final surface score vs K/N ratio",
         "Exploratory view of K divided by N across adaptive and coupled K/N candidates; identical ratios can represent different K/N pairs, so this is not an isolated causal effect.",
         _scatter_svg(kn_score_vs_ratio, "K / N", "Final surface score (%)", trends=True)),
    )
    plots_html = "".join(
        f"<article class='plot-card'><h3>{html.escape(title)}</h3>"
        f"<p class='muted'>{html.escape(description)}</p>{plot}</article>"
        for title, description, plot in trend_plots)

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

    status_order = {"running": 0, "planned": 1, "not started": 1,
                    "conditional": 2, "complete": 3, "failed": 4}
    summary_entries = []
    for summary in summaries:
        report_link = (
            f"<a href='{html.escape(str(summary['report_path'].relative_to(project_root)))}'>search report</a>"
            if summary["report_path"] else "—"
        )
        status_badge = f"<span class='badge {html.escape(_ranking_class(summary))}'>{html.escape(summary['status'])}</span>"
        summary_entries.append((
            status_order.get(summary["status"], 2), summary["label"],
            f"{summary['coverage']:g}",
            "<tr data-subsearch-coverage-angle='{}'>"
            "<td>{}</td>"
            f"<td>{html.escape(summary['label'])}</td>"
            f"<td>{status_badge}</td>"
            f"<td>{summary['completed']}&nbsp;/<wbr> {summary['proposal_count']}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        ))
    plan_path = project_root / "study_plan.yaml"
    planned = (yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}).get(
        "planned_subsearches", []) if plan_path.is_file() else []
    for item in planned:
        prerequisite = item.get("prerequisite")
        planned_status = str(item.get("status", "planned"))
        detail = (f"<br><span class='muted'>after {html.escape(str(prerequisite))}</span>"
                  if prerequisite else "")
        angles = " ".join(str(value) for value in item.get("coverage_angles", []))
        summary_entries.append((
            status_order.get(planned_status, 1), str(item["label"]), angles,
            "<tr data-subsearch-coverage-angle='{}'>"
            "<td>{}</td>"
            f"<td>{html.escape(str(item['label']))}{detail}</td>"
            f"<td><span class='badge pending'>{html.escape(planned_status)}</span></td>"
            "<td>—</td><td>—</td>"
            "</tr>"
        ))
    summary_entries.sort(key=lambda item: (item[0], item[1]))
    summary_rows = [entry[3].format(html.escape(entry[2]), rank)
                    for rank, entry in enumerate(summary_entries, 1)]

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
.column-controls,.angle-controls{{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 12px}}.column-toggle,.angle-filter{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:var(--panel-2);color:var(--muted);cursor:pointer}}.column-toggle[aria-pressed='true'],.angle-filter[aria-pressed='true']{{border-color:var(--accent);color:var(--ink);background:#173c39}}.filter-count{{margin-left:5px;color:var(--muted);font-size:.9rem}}
.plot-grid-layout{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.plot-card{{min-width:0;background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:12px}}.plot-card .muted{{margin:0 0 8px;min-height:42px}}.trend-plot{{display:block;width:100%;height:auto;background:#0d1319;border-radius:6px}}.plot-grid{{stroke:#263541;stroke-width:1}}.plot-trend{{fill:none;stroke-width:2.4;opacity:.92}}.plot-tick,.plot-label{{fill:var(--muted);font-size:11px}}.plot-axis-label{{fill:var(--ink);font-size:12px;font-weight:600}}.trend-plot circle{{stroke:#0c1014;stroke-width:1;opacity:.82}}.scatter-point{{cursor:pointer}}.scatter-point:hover,.scatter-point:focus{{stroke:var(--ink);stroke-width:2;opacity:1;outline:none}}.scatter-popup{{position:fixed;z-index:30;width:min(340px,calc(100vw - 24px));padding:12px;border:1px solid var(--accent);border-radius:8px;background:#101820;box-shadow:0 12px 32px rgba(0,0,0,.45)}}.scatter-popup strong{{display:block;margin-bottom:6px}}.scatter-popup p{{margin:0 0 8px;color:var(--muted);font-size:.92rem}}
.muted{{color:var(--muted)}}
@media(max-width:1100px){{.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:900px){{.plot-grid-layout{{grid-template-columns:1fr}}}}@media(max-width:700px){{.summary{{grid-template-columns:1fr}}}}
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
<h2>Project range</h2>
<table><tr><th>Coverage targets</th><th>Mouth sizes</th><th>Fixed K&nbsp;/ N</th><th>Sweep&nbsp;/ crossover</th><th>Length-mouth ratios</th></tr>
<tr><td>{coverage_targets} deg</td><td>{mouth_sizes} mm</td><td>K={fixed_k}, N={fixed_n}</td><td>{sweep_lower}-{sweep_upper} Hz&nbsp;/<wbr> {crossover} Hz</td><td>{", ".join(f"{ratio:g}" for ratio in ratios) if ratios != "—" else "—"}</td></tr></table>
</section>
<section>
<h2>Candidate performance trends</h2>
<div class='plot-grid-layout'>{plots_html}</div>
<aside id='scatter-popup' class='scatter-popup' hidden><strong></strong><p></p><a href='#'>Open candidate report</a></aside>
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
</section>
<section>
<h2>Sub-searches</h2>
<div class='angle-controls' aria-label='Filter sub-searches by coverage angle'>{subsearch_angle_filters}<span id='subsearch-filter-count' class='filter-count'>{len(summary_rows)} sub-searches</span></div>
<table id='subsearch-table' class='sortable-table'>
<thead><tr><th class='sortable' data-sort='number'>#</th><th class='sortable' data-sort='text'>Sub-search</th><th class='sortable' data-sort='text'>Status</th><th class='sortable' data-sort='number'>Complete&nbsp;/ Proposed</th><th>Links</th></tr></thead>
<tbody>{''.join(summary_rows)}</tbody>
</table>
</section>
<script>
(() => {{
  const scatterPopup = document.getElementById('scatter-popup');
  const scatterTitle = scatterPopup.querySelector('strong');
  const scatterStats = scatterPopup.querySelector('p');
  const scatterLink = scatterPopup.querySelector('a');
  const closeScatterPopup = () => {{ scatterPopup.hidden = true; }};
  const openScatterPopup = (point) => {{
    scatterTitle.textContent = point.dataset.candidate || 'Candidate';
    scatterStats.textContent = point.dataset.stats || '';
    const report = point.dataset.report || '';
    scatterLink.hidden = !report;
    if (report) scatterLink.href = report;
    scatterPopup.hidden = false;
    const rect = point.getBoundingClientRect();
    const popupRect = scatterPopup.getBoundingClientRect();
    scatterPopup.style.left = `${{Math.max(12, Math.min(window.innerWidth - popupRect.width - 12, rect.left + 10))}}px`;
    scatterPopup.style.top = `${{Math.max(12, Math.min(window.innerHeight - popupRect.height - 12, rect.top + 14))}}px`;
  }};
  document.addEventListener('click', (event) => {{
    const point = event.target.closest?.('.scatter-point');
    if (point) {{ openScatterPopup(point); return; }}
    if (!scatterPopup.contains(event.target)) closeScatterPopup();
  }});
  document.addEventListener('keydown', (event) => {{
    if (event.key === 'Escape') closeScatterPopup();
    if ((event.key === 'Enter' || event.key === ' ') && event.target.matches?.('.scatter-point')) {{
      event.preventDefault(); openScatterPopup(event.target);
    }}
  }});
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
  document.querySelectorAll('[data-angle-filter]').forEach((button) => {{
    button.addEventListener('click', () => {{
      const selected = button.dataset.angleFilter;
      let visible = 0;
      document.querySelectorAll('[data-angle-filter]').forEach((item) => {{
        item.setAttribute('aria-pressed', String(item === button));
      }});
      Array.from(candidateTable.tBodies[0].rows).forEach((row) => {{
        row.hidden = selected !== 'all' && row.dataset.coverageAngle !== selected;
        if (!row.hidden) visible += 1;
      }});
      candidateCount.textContent = `${{visible}} candidate${{visible === 1 ? '' : 's'}}`;
    }});
  }});
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
