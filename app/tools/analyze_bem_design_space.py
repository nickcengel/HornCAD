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


def analyze(root: Path) -> dict[str, Any]:
    candidates, search_states = load_candidates(root)
    coverage_counts = Counter(candidate.coverage_deg for candidate in candidates)
    pairs = {parameter: matched_pairs(candidates, parameter)
             for parameter in PARAMETERS}
    latest = max((candidate.completed_at for candidate in candidates), default=0)
    return {
        "schema_version": 1,
        "snapshot_completed_at": (
            datetime.fromtimestamp(latest).astimezone().isoformat() if latest else None),
        "provisional": any(key not in ("complete",) for key in search_states),
        "search_states": search_states,
        "unique_candidate_count": len(candidates),
        "coverage_counts": {f"{key:g}": coverage_counts[key]
                            for key in sorted(coverage_counts)},
        "mouth_coverage_cell_count": len(set(
            (item.mouth_mm, item.coverage_deg) for item in candidates)),
        "fixed_k4_n10_cells": _cell_summaries(candidates),
        "matched_effects": {
            parameter: {
                **_summarize_pairs(parameter_pairs),
                "strata": _effect_strata(parameter_pairs, parameter),
            }
            for parameter, parameter_pairs in pairs.items()
        },
    }


def _number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(analysis: dict[str, Any]) -> str:
    state_text = ", ".join(
        f"{key}: {value}" for key, value in analysis["search_states"].items())
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
        "- Candidate counts by coverage half-angle: " + ", ".join(
            f"{key}°: {value}" for key, value in analysis["coverage_counts"].items()) + ".",
        "",
        "The counts are evidence density, not evidence quality. Incomplete 30° work and "
        "unfinished closure studies must not yet be used for final cross-angle recommendations.",
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
        "1. Split matched effects by mouth, coverage, S region, and starting diagnostic state.",
        "2. Test whether diagnostic-conditioned directions repeat across independent cells.",
        "3. Compare absolute and length/mouth-normalized bunching frequencies to identify which "
        "physical scale moves each frequency feature.",
        "4. Freeze completed results as training evidence and use later completions as held-out "
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
