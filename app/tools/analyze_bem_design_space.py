#!/usr/bin/env python3
"""Build a provisional, repeatable analysis of the BEM design-space study."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable


PARAMETERS = ("s", "k", "n")
DIAGNOSTICS = (
    "score", "mean_containment", "profile_rms_error_db",
    "slice_energy_departure_db", "outward_rise_violation_db",
    "minus_six_rms_error_deg", "high_frequency_coverage_error_deg",
)


@dataclass(frozen=True)
class Candidate:
    search_path: Path
    candidate_id: str
    completed_at: float
    mouth_mm: float
    coverage_deg: float
    length_mm: float
    s: float
    k: float
    n: float
    score: float
    diagnostics: dict[str, float]
    dominant_bunching_hz: float | None

    @property
    def report_path(self) -> Path | None:
        return_path = self.search_path.parent / str(self.candidate_id)
        return return_path if return_path.is_file() else None


def _mean_axis(result: dict[str, Any], getter) -> float:
    values = [getter(result[axis]) for axis in ("horizontal", "vertical")]
    return sum(float(value) for value in values) / len(values)


def _candidate_from_record(state_path: Path, record: dict[str, Any]) -> Candidate | None:
    if record.get("status") != "complete":
        return None
    result = record.get("surface_diagnostics", {})
    score = (result.get("score") or {}).get("overall_percent")
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        return None
    try:
        coverage = float(state_path.parent.parent.name.removesuffix("deg"))
        mouth = float(state_path.parent.name.split("x", 1)[0])
        values = record["values"]
        derived = record["derived"]
        axis_scores = result["score"]
        diagnostics = {
            "score": float(score),
            "mean_containment": _mean_axis(
                axis_scores, lambda axis: axis["components"]["mean_containment"]),
            "profile_rms_error_db": _mean_axis(
                result, lambda axis: axis["distribution"]["rms_profile_error_db"]),
            "slice_energy_departure_db": _mean_axis(
                result, lambda axis: axis["slice_energy_stability"]["rms_departure_db"]),
            "outward_rise_violation_db": _mean_axis(
                result, lambda axis: axis["distribution"]["rms_outward_rise_violation_db"]),
            "minus_six_rms_error_deg": _mean_axis(
                result, lambda axis: axis["minus_six_line"]["rms_coverage_error_deg"]),
            "high_frequency_coverage_error_deg": _mean_axis(
                result, lambda axis: sum(
                    axis["traces"]["minus_six_error_deg"][-55:]) /
                    len(axis["traces"]["minus_six_error_deg"][-55:])),
        }
        dominant = _mean_axis(
            result,
            lambda axis: axis["slice_energy_stability"]["highest_departure_frequency_hz"],
        )
        return Candidate(
            search_path=state_path,
            candidate_id=str(record.get("report_file", record.get("id", ""))),
            completed_at=float(record.get("completed_at_unix", 0.0)),
            mouth_mm=mouth,
            coverage_deg=coverage,
            length_mm=float(values["length_mm"]),
            s=(float(derived["s_h"]) + float(derived["s_v"])) / 2,
            k=(float(values["k_h"]) + float(values["k_v"])) / 2,
            n=(float(values["n_h"]) + float(values["n_v"])) / 2,
            score=float(score), diagnostics=diagnostics,
            dominant_bunching_hz=float(dominant),
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def load_candidates(root: Path) -> tuple[list[Candidate], dict[str, int]]:
    candidates: list[Candidate] = []
    states = Counter()
    for state_path in sorted(root.glob("*deg/*x*/search_state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            states["unreadable"] += 1
            continue
        states[str(state.get("status", "unknown"))] += 1
        for record in state.get("candidates", []):
            candidate = _candidate_from_record(state_path, record)
            if candidate is not None:
                candidates.append(candidate)
    return deduplicate(candidates), dict(sorted(states.items()))


def deduplicate(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Keep one result for an exactly repeated physical design."""
    chosen: dict[tuple[float, ...], Candidate] = {}
    for candidate in candidates:
        key = tuple(round(value, 3) for value in (
            candidate.mouth_mm, candidate.coverage_deg, candidate.length_mm,
            candidate.k, candidate.n,
        ))
        previous = chosen.get(key)
        if previous is None or candidate.completed_at > previous.completed_at:
            chosen[key] = candidate
    return sorted(chosen.values(), key=lambda item: (
        item.coverage_deg, item.mouth_mm, item.length_mm, item.k, item.n))


def _pair_key(candidate: Candidate, parameter: str) -> tuple[float, ...]:
    base = [candidate.mouth_mm, candidate.coverage_deg]
    if parameter != "s":
        base.append(candidate.length_mm)
    if parameter != "k":
        base.append(candidate.k)
    if parameter != "n":
        base.append(candidate.n)
    return tuple(round(value, 3) for value in base)


def matched_pairs(candidates: Iterable[Candidate], parameter: str) -> list[dict[str, Any]]:
    """Return adjacent, one-control perturbations in comparable groups."""
    groups: dict[tuple[float, ...], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[_pair_key(candidate, parameter)].append(candidate)
    pairs = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: getattr(item, parameter))
        for lower, upper in zip(ordered, ordered[1:]):
            delta_parameter = getattr(upper, parameter) - getattr(lower, parameter)
            if delta_parameter <= 1e-6:
                continue
            pairs.append({
                "mouth_mm": lower.mouth_mm,
                "coverage_deg": lower.coverage_deg,
                "from": getattr(lower, parameter),
                "to": getattr(upper, parameter),
                "delta_parameter": delta_parameter,
                "start": dict(lower.diagnostics),
                "start_s": lower.s,
                "start_k": lower.k,
                "start_n": lower.n,
                "delta": {
                    name: upper.diagnostics[name] - lower.diagnostics[name]
                    for name in DIAGNOSTICS
                },
                "dominant_bunching_shift_octaves": (
                    math.log2(upper.dominant_bunching_hz / lower.dominant_bunching_hz)
                    if lower.dominant_bunching_hz and upper.dominant_bunching_hz else None
                ),
            })
    return pairs


def _summarize_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"count": len(pairs)}
    if not pairs:
        return summary
    summary["score_improved_fraction"] = sum(
        pair["delta"]["score"] > 0 for pair in pairs) / len(pairs)
    summary["median_delta"] = {
        name: median(pair["delta"][name] for pair in pairs)
        for name in DIAGNOSTICS
    }
    shifts = [pair["dominant_bunching_shift_octaves"] for pair in pairs
              if pair["dominant_bunching_shift_octaves"] is not None]
    if shifts:
        summary["median_dominant_bunching_shift_octaves"] = median(shifts)
    return summary


def _transition_summaries(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        grouped[(round(pair["from"], 3), round(pair["to"], 3))].append(pair)
    return [{
        "from": transition[0], "to": transition[1], "count": len(group),
        "score_improved_fraction": sum(
            pair["delta"]["score"] > 0 for pair in group) / len(group),
        "median_score_delta": median(pair["delta"]["score"] for pair in group),
    } for transition, group in sorted(grouped.items())]


def _effect_strata(pairs: list[dict[str, Any]], parameter: str) -> list[dict[str, Any]]:
    """Expose sign reversals without pretending they establish a causal rule."""
    if not pairs:
        return []
    strata: list[tuple[str, list[dict[str, Any]]]] = []
    for coverage in sorted(set(pair["coverage_deg"] for pair in pairs)):
        strata.append((f"coverage {coverage:g}°", [
            pair for pair in pairs if pair["coverage_deg"] == coverage]))
    if parameter == "s":
        bins = (("S < 1", lambda value: value < 1),
                ("1 ≤ S < 2", lambda value: 1 <= value < 2),
                ("S ≥ 2", lambda value: value >= 2))
        for label, predicate in bins:
            strata.append((label, [pair for pair in pairs
                                  if predicate(pair["start_s"])]))
    else:
        for diagnostic in (
                "mean_containment", "profile_rms_error_db",
                "slice_energy_departure_db", "outward_rise_violation_db",
                "minus_six_rms_error_deg", "high_frequency_coverage_error_deg"):
            midpoint = median(pair["start"][diagnostic] for pair in pairs)
            strata.append((f"low starting {diagnostic}", [
                pair for pair in pairs if pair["start"][diagnostic] < midpoint]))
            strata.append((f"high starting {diagnostic}", [
                pair for pair in pairs if pair["start"][diagnostic] >= midpoint]))
    output = []
    for label, group in strata:
        if len(group) < 3:
            continue
        output.append({
            "stratum": label, "count": len(group),
            "score_improved_fraction": sum(
                pair["delta"]["score"] > 0 for pair in group) / len(group),
            "median_score_delta": median(pair["delta"]["score"] for pair in group),
        })
    return output


def _cell_summaries(candidates: Iterable[Candidate]) -> list[dict[str, Any]]:
    cells: dict[tuple[float, float], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if abs(candidate.k - 4) <= 0.01 and abs(candidate.n - 10) <= 0.01:
            cells[(candidate.coverage_deg, candidate.mouth_mm)].append(candidate)
    output = []
    for (coverage, mouth), group in sorted(cells.items()):
        unique_s = {}
        for item in group:
            previous = unique_s.get(round(item.s, 3))
            if previous is None or item.score > previous.score:
                unique_s[round(item.s, 3)] = item
        ordered = sorted(unique_s.values(), key=lambda item: item.s)
        best = max(ordered, key=lambda item: item.score)
        index = ordered.index(best)
        output.append({
            "coverage_deg": coverage, "mouth_mm": mouth,
            "sample_count": len(ordered), "minimum_s": ordered[0].s,
            "maximum_s": ordered[-1].s, "best_s": best.s,
            "best_length_mm": best.length_mm, "best_score": best.score,
            "winner_at_sampled_boundary": index in (0, len(ordered) - 1),
            "lower_score": ordered[index - 1].score if index > 0 else None,
            "upper_score": ordered[index + 1].score if index + 1 < len(ordered) else None,
        })
    return output


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _study_progress(root: Path) -> dict[str, Any]:
    program = _read_json(root / "study_program_state.json")
    domain = _read_json(root / "domain_mapping_state.json")
    closure = _read_json(root / "s_boundary_closure.json")
    closure_results = closure.get("results", [])
    closure_counts = Counter(
        str(item.get("status", "unknown"))
        for item in closure_results if isinstance(item, dict)
    )
    running_searches = []
    for state_path in sorted(root.glob("*deg/*x*/search_state.json")):
        state = _read_json(state_path)
        if state.get("status") != "running":
            continue
        candidates = state.get("candidates", [])
        running_searches.append({
            "search": str(state_path.parent.relative_to(root)),
            "phase": str(state.get("phase", "unknown")),
            "completed_candidates": sum(
                record.get("status") == "complete" for record in candidates),
            "planned_candidates": int(state.get(
                "max_evaluations", state.get("search", {}).get(
                    "max_evaluations", len(candidates)))),
            "solver_workers": int(state.get("search", {}).get(
                "solver", {}).get("workers", 0)),
        })
    active = domain if domain else program
    return {
        "program_status": str(active.get("status", "unknown")),
        "program_phase": str(active.get("phase", "unknown")),
        "s_closure_status": str(closure.get("status", "unknown")),
        "s_closure_cell_count": len(closure_results),
        "s_closure_counts": dict(sorted(closure_counts.items())),
        "running_searches": running_searches,
        "domain_mapping": {
            "status": str(domain.get("status", "not-started")),
            "phase": str(domain.get("phase", "not-started")),
            "total_candidates": int(domain.get("total_candidates", 144)),
            "planned_slot_count": len(domain.get("planned_slots", [])),
            "completed_searches": int(domain.get("completed_searches", 0)),
            "score_materiality_points": float(
                domain.get("score_materiality_points", 1.0)),
        },
    }


def _coverage_winner_summary(candidates: Iterable[Candidate]) -> list[dict[str, Any]]:
    """Describe the angle trend without letting dense cells dominate it."""
    cells: dict[tuple[float, float], list[Candidate]] = defaultdict(list)
    for item in candidates:
        cells[(item.coverage_deg, item.mouth_mm)].append(item)
    winners = [max(group, key=lambda item: item.score) for group in cells.values()]
    output = []
    for coverage in sorted(set(item.coverage_deg for item in winners)):
        group = [item for item in winners if item.coverage_deg == coverage]
        output.append({
            "coverage_deg": coverage, "cell_count": len(group),
            "median_score": median(item.score for item in group),
            "median_mouth_length_ratio": median(
                item.mouth_mm / item.length_mm for item in group),
            **{f"median_{name}": median(item.diagnostics[name] for item in group)
               for name in ("mean_containment", "profile_rms_error_db",
                            "slice_energy_departure_db",
                            "outward_rise_violation_db",
                            "minus_six_rms_error_deg")},
        })
    return output


def _remote_stratum(candidate: Candidate) -> str:
    if candidate.k <= 1.5 and candidate.n <= 2.5:
        return "K≈1 / N≈2 corner"
    if candidate.k >= 6.5 and candidate.n >= 18.0:
        return "K≈7 / N≈20 corner"
    return ("low K" if candidate.k < 4 else "high K") + " / " + (
        "low N" if candidate.n < 10 else "high N")


def _domain_mapping_meta(candidates: Iterable[Candidate],
                         started_at: float | None) -> dict[str, Any]:
    """Measure whether Phase 4 adds regions, tradeoffs, or only boundaries."""
    items = list(candidates)
    remote = [item for item in items if item.search_path is not None and
              "-domain-map-b" in item.search_path.parent.name]
    baseline = [item for item in items if item not in remote and (
        started_at is None or item.completed_at <= started_at)]
    by_cell: dict[tuple[float, float], list[Candidate]] = defaultdict(list)
    for item in baseline:
        by_cell[(item.coverage_deg, item.mouth_mm)].append(item)

    def coordinate(item: Candidate) -> tuple[float, ...]:
        return (
            (item.mouth_mm / item.length_mm - 0.5) / 5.5,
            (item.s - 0.05) / 3.95,
            (item.k - 1) / 6,
            (item.n - 2) / 18,
        )

    records = []
    for item in remote:
        cell = by_cell.get((item.coverage_deg, item.mouth_mm), [])
        if not cell:
            continue
        incumbent = max(cell, key=lambda candidate: candidate.score)
        point = coordinate(item)
        nearest = min(math.dist(point, coordinate(other)) for other in cell)
        delta = item.score - incumbent.score
        component_changes = {
            "containment": (
                item.diagnostics["mean_containment"] -
                incumbent.diagnostics["mean_containment"]),
            "profile_rms_db": (
                item.diagnostics["profile_rms_error_db"] -
                incumbent.diagnostics["profile_rms_error_db"]),
            "slice_energy_db": (
                item.diagnostics["slice_energy_departure_db"] -
                incumbent.diagnostics["slice_energy_departure_db"]),
            "outward_rise_db": (
                item.diagnostics["outward_rise_violation_db"] -
                incumbent.diagnostics["outward_rise_violation_db"]),
            "minus_six_rms_deg": (
                item.diagnostics["minus_six_rms_error_deg"] -
                incumbent.diagnostics["minus_six_rms_error_deg"]),
        }
        meaningful_tradeoff = (
            component_changes["containment"] >= 0.5 or
            component_changes["profile_rms_db"] <= -0.1 or
            component_changes["slice_energy_db"] <= -0.1 or
            component_changes["outward_rise_db"] <= -0.1 or
            component_changes["minus_six_rms_deg"] <= -0.5
        )
        if nearest < 0.08:
            classification = "redundant-near-existing"
        elif delta > 0:
            classification = "new-cell-winner"
        elif delta >= -1:
            classification = "competitive-remote"
        elif delta <= -3:
            classification = "boundary-confirmation"
        elif meaningful_tradeoff:
            classification = "diagnostic-tradeoff"
        else:
            classification = "inconclusive"
        records.append({
            "coverage_deg": item.coverage_deg, "mouth_mm": item.mouth_mm,
            "s": item.s, "k": item.k, "n": item.n,
            "mouth_length_ratio": item.mouth_mm / item.length_mm,
            "nearest_pre_phase_distance": nearest,
            "score": item.score, "incumbent_score": incumbent.score,
            "score_delta": delta, "stratum": _remote_stratum(item),
            "classification": classification,
            "component_changes": component_changes,
        })
    counts = Counter(record["classification"] for record in records)
    strata = []
    for label in sorted(set(record["stratum"] for record in records)):
        group = [record for record in records if record["stratum"] == label]
        competitive = sum(record["classification"] in (
            "new-cell-winner", "competitive-remote") for record in group)
        tradeoffs = sum(record["classification"] == "diagnostic-tradeoff"
                        for record in group)
        boundaries = sum(record["classification"] == "boundary-confirmation"
                         for record in group)
        angle_count = len(set(record["coverage_deg"] for record in group))
        if competitive:
            recommendation = "continue: competitive remote evidence"
        elif (len(group) >= 6 and angle_count >= 3 and not tradeoffs and
              boundaries / len(group) >= 0.8):
            recommendation = "stop stratum: low-value boundary established"
        else:
            recommendation = "collect distributed sentinels"
        strata.append({
            "stratum": label, "completed": len(group),
            "angle_count": angle_count, "competitive": competitive,
            "diagnostic_tradeoffs": tradeoffs,
            "boundary_confirmations": boundaries,
            "median_score_delta": median(record["score_delta"] for record in group),
            "recommendation": recommendation,
        })
    if len(records) >= 2:
        xs = [record["nearest_pre_phase_distance"] for record in records]
        ys = [record["score_delta"] for record in records]
        x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) *
                                sum((y - y_mean) ** 2 for y in ys))
        correlation = numerator / denominator if denominator else None
    else:
        correlation = None
    competitive_total = counts["new-cell-winner"] + counts["competitive-remote"]
    if competitive_total:
        assessment = "remote competitive region found"
    elif len(records) < 12:
        assessment = "insufficient distributed evidence"
    elif counts["boundary-confirmation"] / len(records) >= 0.75:
        assessment = "remote samples mainly support the existing ridge"
    else:
        assessment = "mixed remote evidence"
    return {
        "completed_remote_candidates": len(records),
        "assessment": assessment,
        "classification_counts": dict(sorted(counts.items())),
        "median_nearest_pre_phase_distance": (
            median(record["nearest_pre_phase_distance"] for record in records)
            if records else None),
        "median_score_delta": (
            median(record["score_delta"] for record in records) if records else None),
        "distance_score_correlation": correlation,
        "strata": strata, "candidates": records,
    }


def _phase_three_audit(root: Path) -> dict[str, Any]:
    """Summarize the practical value of completed coupled K/N refinement."""
    search_count = completed_count = quarter_k_count = 0
    winner_advantages = []
    anchors: dict[tuple[float, float], list[dict[str, float]]] = defaultdict(list)
    for state_path in sorted(root.glob("*deg/*coupled*-kn/search_state.json")):
        state = _read_json(state_path)
        completed = []
        for record in state.get("candidates", []):
            if record.get("status") != "complete":
                continue
            score = record.get("surface_diagnostics", {}).get(
                "score", {}).get("overall_percent")
            values = record.get("values", {})
            if score is None or values.get("k_h") is None or values.get("n_h") is None:
                continue
            item = {
                "k": float(values["k_h"]), "n": float(values["n_h"]),
                "score": float(score),
            }
            completed.append(item)
            quarter_k_count += not math.isclose(
                item["k"] * 2, round(item["k"] * 2), abs_tol=1e-6)
        if not completed:
            continue
        search_count += 1
        completed_count += len(completed)
        best = max(completed, key=lambda item: item["score"])
        alternatives = [
            item for item in completed
            if math.isclose(item["n"], best["n"], abs_tol=1e-6) and
            1e-6 < abs(item["k"] - best["k"]) <= 0.500001
        ]
        if alternatives:
            winner_advantages.append(
                best["score"] - max(item["score"] for item in alternatives))
        coverage = float(state_path.parent.parent.name.removesuffix("deg"))
        mouth = float(state_path.parent.name.split("x", 1)[0])
        anchors[(coverage, mouth)].append({
            "seed_score": completed[0]["score"], "best_score": best["score"],
        })
    anchor_gains = []
    for (coverage, mouth), rounds in sorted(anchors.items()):
        local_s_paths = sorted(root.glob(
            f"{coverage:g}deg/{mouth:g}x{mouth:g}-coupled-r*-s/search_state.json"))
        local_s_status = "not-run"
        final_values: dict[str, float | str] = {}
        if local_s_paths:
            latest_s_state = _read_json(local_s_paths[-1])
            sampled = []
            for record in latest_s_state.get("candidates", []):
                score = record.get("surface_diagnostics", {}).get(
                    "score", {}).get("overall_percent")
                if record.get("status") != "complete" or score is None:
                    continue
                sampled.append({
                    "s": float(record["derived"]["s_h"]),
                    "length": float(record["values"]["length_mm"]),
                    "k": float(record["values"]["k_h"]),
                    "n": float(record["values"]["n_h"]),
                    "score": float(score),
                })
            if sampled:
                ordered = sorted(sampled, key=lambda item: item["s"])
                center = ordered[len(ordered) // 2]
                best_s = max(ordered, key=lambda item: item["score"])
                center_delta = abs(best_s["s"] - center["s"])
                gain_over_center = best_s["score"] - center["score"]
                if center_delta <= 0.075:
                    local_s_status = "converged"
                elif len(local_s_paths) >= 3 and gain_over_center < 0.5:
                    local_s_status = "practical-stop-unbracketed"
                else:
                    local_s_status = "unresolved"
                final_values = {
                    "local_s_round_count": len(local_s_paths),
                    "local_s_status": local_s_status,
                    "final_score": best_s["score"], "final_s": best_s["s"],
                    "final_length_mm": best_s["length"],
                    "final_k": best_s["k"], "final_n": best_s["n"],
                    "local_s_gain_over_center_points": gain_over_center,
                    "local_s_winner_at_edge": best_s in (ordered[0], ordered[-1]),
                }
        anchor_gains.append({
            "coverage_deg": coverage, "mouth_mm": mouth,
            "first_seed_score": rounds[0]["seed_score"],
            "latest_kn_score": rounds[-1]["best_score"],
            "gain_points": rounds[-1]["best_score"] - rounds[0]["seed_score"],
            "round_count": len(rounds),
            **final_values,
        })
    return {
        "search_count": search_count,
        "completed_candidate_count": completed_count,
        "quarter_step_k_candidate_count": quarter_k_count,
        "median_winner_advantage_over_nearby_k": (
            median(winner_advantages) if winner_advantages else None),
        "maximum_winner_advantage_over_nearby_k": (
            max(winner_advantages) if winner_advantages else None),
        "anchor_gains": anchor_gains,
        "adopted_minimum_k_step": 0.5,
        "adopted_minimum_n_step": 1.0,
        "score_asymptote_tolerance_points": 0.5,
    }


def analyze(root: Path) -> dict[str, Any]:
    candidates, search_states = load_candidates(root)
    progress = _study_progress(root)
    coverage_counts = Counter(candidate.coverage_deg for candidate in candidates)
    pairs = {parameter: matched_pairs(candidates, parameter)
             for parameter in PARAMETERS}
    latest = max((candidate.completed_at for candidate in candidates), default=0)
    phase_three_audit = _phase_three_audit(root)
    domain_state = _read_json(root / "domain_mapping_state.json")
    domain_meta = _domain_mapping_meta(
        candidates, domain_state.get("started_at_unix"))
    coupled_unresolved = any(
        item.get("local_s_status") not in (None, "converged")
        for item in phase_three_audit["anchor_gains"])
    return {
        "schema_version": 1,
        "snapshot_completed_at": (
            datetime.fromtimestamp(latest).astimezone().isoformat() if latest else None),
        "provisional": (
            progress["program_status"] != "complete" or
            any(key in search_states for key in ("running", "pending")) or
            coupled_unresolved
        ),
        "study_progress": progress,
        "phase_three_audit": phase_three_audit,
        "domain_mapping_meta_analysis": domain_meta,
        "search_states": search_states,
        "unique_candidate_count": len(candidates),
        "coverage_counts": {f"{key:g}": coverage_counts[key]
                            for key in sorted(coverage_counts)},
        "mouth_coverage_cell_count": len(set(
            (item.mouth_mm, item.coverage_deg) for item in candidates)),
        "fixed_k4_n10_cells": _cell_summaries(candidates),
        "coverage_winner_summary": _coverage_winner_summary(candidates),
        "matched_effects": {
            parameter: {
                **_summarize_pairs(parameter_pairs),
                "strata": _effect_strata(parameter_pairs, parameter),
                "transitions": _transition_summaries(parameter_pairs),
            }
            for parameter, parameter_pairs in pairs.items()
        },
    }


def _number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(analysis: dict[str, Any]) -> str:
    state_text = ", ".join(
        f"{key}: {value}" for key, value in analysis["search_states"].items())
    progress = analysis.get("study_progress", {})
    phase = progress.get("program_phase", "unknown")
    program_status = progress.get("program_status", "unknown")
    closure_status = progress.get("s_closure_status", "unknown")
    closure_counts = progress.get("s_closure_counts", {})
    closure_text = ", ".join(
        f"{key}: {value}" for key, value in closure_counts.items()) or "unavailable"
    lines = [
        "# Current BEM design-space analysis",
        "",
        f"Snapshot through `{analysis['snapshot_completed_at']}`. This analysis is "
        f"**{'provisional' if analysis['provisional'] else 'complete'}** and can be regenerated as solves finish.",
        "",
        "## Evidence inventory",
        "",
        f"- {analysis['unique_candidate_count']} unique scored physical designs across "
        f"{analysis['mouth_coverage_cell_count']} mouth/coverage cells.",
        f"- Search states: {state_text}.",
        f"- Study program: `{phase}` ({program_status}).",
        f"- S-closure certificate: {closure_status}; {closure_text}.",
        "- Candidate counts by coverage half-angle: " + ", ".join(
            f"{key}°: {value}" for key, value in analysis["coverage_counts"].items()) + ".",
        "",
        ("The counts are evidence density, not evidence quality. The production queue has "
         "finished, but practical-stop or unbracketed coupled anchors remain explicitly "
         "provisional; expected geometry rejections describe the admissible design boundary "
         "rather than missing solver evidence." if program_status == "complete" else
         "The counts are evidence density, not evidence quality. Cross-angle conclusions remain "
         "provisional while the study program is running; expected geometry rejections describe "
         "the admissible design boundary rather than missing solver evidence."),
        "",
        "## Controlled adjacent effects",
        "",
        "Positive score deltas mean increasing the named control improved the surface score. "
        "For error diagnostics, negative deltas are improvements. S comparisons hold K and N "
        "fixed; K comparisons hold physical length and N fixed; N comparisons hold physical "
        "length and K fixed.",
        "",
        "| Increase | Pairs | Score improves | Median score Δ | Containment Δ | Profile RMS Δ dB | Slice-energy Δ dB | Outward-rise Δ dB | -6 dB RMS Δ deg | Bunching shift oct |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    running_searches = progress.get("running_searches", [])
    if running_searches:
        lines.extend(
            f"- Running: `{item['search']}` — {item['phase']}; "
            f"{item['completed_candidates']}/{item['planned_candidates']} candidates complete; "
            f"{item['solver_workers']} solver workers."
            for item in running_searches
        )
    for parameter in PARAMETERS:
        item = analysis["matched_effects"][parameter]
        delta = item.get("median_delta", {})
        lines.append(
            f"| {parameter.upper()} | {item['count']} | "
            f"{100 * item.get('score_improved_fraction', 0):.0f}% | "
            f"{_number(delta.get('score'))} | {_number(delta.get('mean_containment'))} | "
            f"{_number(delta.get('profile_rms_error_db'), 3)} | "
            f"{_number(delta.get('slice_energy_departure_db'), 3)} | "
            f"{_number(delta.get('outward_rise_violation_db'), 3)} | "
            f"{_number(delta.get('minus_six_rms_error_deg'), 2)} | "
            f"{_number(item.get('median_dominant_bunching_shift_octaves'), 3)} |"
        )
    cells = analysis["fixed_k4_n10_cells"]
    boundary = [cell for cell in cells if cell["winner_at_sampled_boundary"]]
    lines += [
        "",
        "These are aggregate directional summaries, not universal steering rules. A control "
        "can reverse sign by mouth, coverage, S, or the other OS-SE controls. The next pass "
        "must stratify matched effects by the starting diagnostic state before promoting a rule.",
        "",
        "### Where the aggregate direction reverses",
        "",
        "| Control increase | Starting regime | Pairs | Score improves | Median score Δ |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for parameter in PARAMETERS:
        strata = analysis["matched_effects"][parameter]["strata"]
        selected = sorted(strata, key=lambda item: (
            -abs(item["median_score_delta"]), -item["count"]))[:8]
        for item in selected:
            lines.append(
                f"| {parameter.upper()} | {item['stratum']} | {item['count']} | "
                f"{100 * item['score_improved_fraction']:.0f}% | "
                f"{item['median_score_delta']:.2f} |"
            )
    lines += [
        "",
        "This table is a screening device. Coverage/S regimes are descriptive, while splits "
        "on a starting diagnostic are hypotheses that still need repetition across independent "
        "mouth/coverage cells and held-out confirmation.",
        "",
        "### Sampled K and N transitions",
        "",
        "| Control | Transition | Pairs | Score improves | Median score Δ |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for parameter in ("k", "n"):
        for item in analysis["matched_effects"][parameter]["transitions"]:
            lines.append(
                f"| {parameter.upper()} | {item['from']:g} → {item['to']:g} | "
                f"{item['count']} | {100 * item['score_improved_fraction']:.0f}% | "
                f"{item['median_score_delta']:.2f} |"
            )
    lines += [
        "",
        "The transition table is the current K/N conclusion: it is rebuilt from matched physical "
        "designs on every refresh. A direction is not promoted to a general rule until it repeats "
        "across independent mouth/coverage cells; later K/N results can therefore reverse an "
        "earlier provisional interpretation without leaving stale prose in this document.",
        "",
        "## Phase 3 coupled-search audit",
        "",
    ]
    audit = analysis["phase_three_audit"]
    lines += [
        f"Across {audit['search_count']} coupled K/N rounds, "
        f"{audit['completed_candidate_count']} candidates were completed; "
        f"{audit['quarter_step_k_candidate_count']} used quarter-step K values. "
        f"At the selected winners, the median advantage over a measured nearby K choice at "
        f"the same N was {_number(audit['median_winner_advantage_over_nearby_k'], 3)} points "
        f"and the maximum was {_number(audit['maximum_winner_advantage_over_nearby_k'], 3)}. "
        "That resolution did not change a practical design decision.",
        "",
        "The coupled phase remains useful at coarse resolution: it showed that useful K and N "
        "move with length and are not fixed at the original K=4, N=10 seed. Future closure uses "
        f"K steps no finer than {audit['adopted_minimum_k_step']:g}, N steps no finer than "
        f"{audit['adopted_minimum_n_step']:g}, and hands off to local S/length when the measured "
        f"neighborhood is within {audit['score_asymptote_tolerance_points']:g} score points.",
        "",
        "| Coverage | Mouth | K/N rounds | First seed | Final score | Final S / L | Final K / N | Status |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in audit["anchor_gains"]:
        lines.append(
            f"| {item['coverage_deg']:g}° | {item['mouth_mm']:g} | "
            f"{item['round_count']} | {item['first_seed_score']:.2f} | "
            f"{item.get('final_score', item['latest_kn_score']):.2f} | "
            f"{_number(item.get('final_s'), 2)} / {_number(item.get('final_length_mm'), 1)} mm | "
            f"{_number(item.get('final_k'), 2)} / {_number(item.get('final_n'), 2)} | "
            f"{item.get('local_s_status', 'not run')} |"
        )
    lines += [
        "",
        "## Coverage and mouth/length trend",
        "",
        "The current wide-coverage penalty is not a general loss of surface smoothness. "
        "Profile and slice-energy errors improve through the central angles, while outward-rise "
        "violation grows as the preferred horn becomes shorter relative to its mouth. This "
        "supports testing longer, higher-K wide horns, but does not yet establish a causal rule.",
        "",
        "| Coverage | Cells | Median score | Mouth / length | Profile RMS dB | Slice-energy dB | Outward rise dB | -6 dB RMS deg |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in analysis["coverage_winner_summary"]:
        lines.append(
            f"| {item['coverage_deg']:g}° | {item['cell_count']} | "
            f"{item['median_score']:.2f} | {item['median_mouth_length_ratio']:.3f} | "
            f"{item['median_profile_rms_error_db']:.3f} | "
            f"{item['median_slice_energy_departure_db']:.3f} | "
            f"{item['median_outward_rise_violation_db']:.3f} | "
            f"{item['median_minus_six_rms_error_deg']:.2f} |"
        )
    meta = analysis["domain_mapping_meta_analysis"]
    lines += [
        "",
        "## Phase 4 remote-sample value",
        "",
        f"Assessment: **{meta['assessment']}**. "
        f"{meta['completed_remote_candidates']} remote candidates are complete; median score "
        f"change from the pre-Phase-4 cell incumbent is "
        f"{_number(meta['median_score_delta'], 2)} points and median normalized distance from "
        f"pre-Phase-4 evidence is {_number(meta['median_nearest_pre_phase_distance'], 3)}. "
        "Boundary confirmations are useful until a distributed stratum is established; later "
        "repetition in that stratum should be skipped.",
        "",
        "| Remote stratum | Complete | Angles | Competitive | Diagnostic tradeoffs | Boundary confirmations | Median score Δ | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in meta["strata"]:
        lines.append(
            f"| {item['stratum']} | {item['completed']} | {item['angle_count']} | "
            f"{item['competitive']} | {item['diagnostic_tradeoffs']} | "
            f"{item['boundary_confirmations']} | {item['median_score_delta']:.2f} | "
            f"{item['recommendation']} |"
        )
    lines += [
        "",
        "## Fixed K=4, N=10 S evidence",
        "",
        f"{len(cells)} mouth/coverage cells currently have fixed K=4, N=10 evidence; "
        f"{len(boundary)} have their measured winner on an observed S endpoint. An endpoint "
        "winner is unresolved unless the study metadata establishes that the endpoint is a "
        "deliberate terminal sentinel rather than an unfinished boundary.",
        "",
        "| Coverage | Mouth | Samples | S extent | Best S | Best L mm | Score | Endpoint winner |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for cell in cells:
        lines.append(
            f"| {cell['coverage_deg']:g}° | {cell['mouth_mm']:g} | {cell['sample_count']} | "
            f"{cell['minimum_s']:.2f}–{cell['maximum_s']:.2f} | {cell['best_s']:.2f} | "
            f"{cell['best_length_mm']:.1f} | {cell['best_score']:.2f} | "
            f"{'yes' if cell['winner_at_sampled_boundary'] else 'no'} |"
        )
    lines += [
        "",
        "## Immediate next analysis",
        "",
        "1. Complete four remote zero-extension candidates in every mouth/coverage cell.",
        "2. Test whether longer, higher-K wide-coverage candidates reduce outward-rise without "
        "losing containment.",
        "3. Test whether diagnostic-conditioned directions repeat across independent cells.",
        "4. Compare absolute and length/mouth-normalized bunching frequencies to identify which "
        "physical scale moves each frequency feature.",
        "5. Freeze completed results as training evidence and use later completions as held-out "
        "checks before any steering rule is labeled supported.",
        "",
        "Generated by `app/tools/analyze_bem_design_space.py`; do not edit this snapshot by hand.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    result = analyze(args.root)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(result), encoding="utf-8")
    if not args.json and not args.markdown:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
