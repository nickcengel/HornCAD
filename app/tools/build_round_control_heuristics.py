#!/usr/bin/env python3
"""Build measured round-control seed heuristics from the canonical evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "examples/control-decoupling/model_source/training_index.json"
CHALLENGE = (
    ROOT / "examples/round-control-v2-validation/validation_results.json")
RIDGE = ROOT / "examples/round-control-ridge-closure/results.json"
SHORT_CLOSURE = (
    ROOT / "examples/round-control-short-length-closure/results.json")
ACTIVE_WINNERS = (
    ROOT / "examples/round-control-parameter-maps-v2-3/winners.json")
WIDE_CLOSURE = (
    ROOT / "examples/round-control-wide-coverage-closure/results.json")
OUTPUT = ROOT / "models/round_control_heuristics_v1"
ANGLES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _active_winner_seeds(
    winners: dict[str, Any],
    reference_lengths: dict[str, dict[str, float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if winners.get("score_version") != "v2.3":
        raise ValueError("active winner map must use surface score v2.3")
    cells: dict[str, Any] = {}
    by_coverage: dict[str, list[float]] = defaultdict(list)
    for angle in ANGLES:
        for mouth in MOUTHS:
            cell_id = f"{angle}deg-{mouth}mm"
            row = winners["cells"][cell_id]["v2_3_winner"]
            reference = float(reference_lengths[str(angle)][str(mouth)])
            seed = {
                "id": row["id"],
                "length_mm": float(row["length_mm"]),
                "length_factor": float(row["length_mm"])/reference,
                "k": float(row["k"]),
                "n": float(row["n"]),
                "s": float(row["s"]),
                "surface_score_v2_3": float(row["score_v2_3"]),
                "source_path": row["source_path"],
                "response_sha256": row["response_sha256"],
            }
            cells[cell_id] = seed
            by_coverage[str(angle)].append(seed["s"])
    s_guidance = {
        angle: {
            "minimum": float(min(values)),
            "median": float(np.median(values)),
            "maximum": float(max(values)),
        }
        for angle, values in by_coverage.items()
    }
    return cells, s_guidance


def _canonical_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in index["rows"]
        if row["role"] == "fit"
        and row["provenance"] == "canonical"
        and row["kind"] == "canonical-grid"
    ]


def _cell(rows: list[dict[str, Any]], angle: int,
          mouth: int) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if int(row["coverage_deg"]) == angle
        and int(row["mouth_mm"]) == mouth
    ]


def _length_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    direct_gains = []
    winning_cells = 0
    references: dict[str, dict[str, float]] = {}
    for angle in ANGLES:
        references[str(angle)] = {}
        for mouth in MOUTHS:
            selected = [
                row for row in _cell(rows, angle, mouth)
                if float(row["k"]) == 4.0 and float(row["n"]) == 8.0
            ]
            center = min(
                selected, key=lambda row: abs(row["length_factor"]-1.0))
            references[str(angle)][str(mouth)] = float(
                center["reference_length_mm"])
            alternatives = [
                row for row in selected
                if abs(float(row["length_factor"])-1.0) > 0.1
            ]
            center_score = float(center["responses"]["surface_score"])
            gains = [
                center_score-float(row["responses"]["surface_score"])
                for row in alternatives
            ]
            direct_gains.extend(gains)
            winning_cells += all(gain > 0.0 for gain in gains)

    complete_groups = 0
    length_wins: Counter[float] = Counter()
    interaction_margins = []
    for angle in ANGLES:
        for mouth in MOUTHS:
            groups: dict[tuple[float, float], dict[float, float]] = defaultdict(
                dict)
            for row in _cell(rows, angle, mouth):
                groups[(float(row["k"]), float(row["n"]))][
                    round(float(row["length_factor"]), 1)
                ] = float(row["responses"]["surface_score"])
            for values in groups.values():
                if set(values) != {0.8, 1.0, 1.2}:
                    continue
                complete_groups += 1
                winner = max(values, key=values.get)
                length_wins[winner] += 1
                interaction_margins.append(
                    values[1.0]-max(values[0.8], values[1.2]))

    return {
        "reference_length_mm": references,
        "center_control_comparison": {
            "controls": {"k": 4.0, "n": 8.0},
            "cells": len(ANGLES)*len(MOUTHS),
            "cells_where_reference_length_won": winning_cells,
            "direct_comparisons": len(direct_gains),
            "direct_comparisons_won": sum(gain > 0.0 for gain in direct_gains),
            "median_surface_score_gain": float(np.median(direct_gains)),
            "minimum_surface_score_gain": float(min(direct_gains)),
            "p10_surface_score_gain": float(np.percentile(direct_gains, 10)),
        },
        "interaction_audit": {
            "complete_k_n_groups": complete_groups,
            "winning_length_factor_counts": {
                f"{factor:.1f}": length_wins[factor]
                for factor in (0.8, 1.0, 1.2)
            },
            "reference_length_win_fraction": (
                length_wins[1.0]/complete_groups),
            "median_reference_margin_over_other_lengths": float(
                np.median(interaction_margins)),
        },
    }


def _axis_audit(rows: list[dict[str, Any]], variable: str,
                fixed: dict[str, float]) -> dict[str, Any]:
    wins: Counter[float] = Counter()
    score_ranges = []
    for angle in ANGLES:
        for mouth in MOUTHS:
            selected = _cell(rows, angle, mouth)
            values = {}
            for row in selected:
                if all(
                    abs(float(row[name])-value) < 1e-7
                    for name, value in fixed.items()
                ):
                    values[float(row[variable])] = float(
                        row["responses"]["surface_score"])
            if len(values) < 2:
                raise ValueError(
                    f"incomplete {variable} comparison at {angle}/{mouth}")
            wins[max(values, key=values.get)] += 1
            score_ranges.append(max(values.values())-min(values.values()))
    return {
        "cells": len(ANGLES)*len(MOUTHS),
        "winning_value_counts": {
            f"{key:g}": value for key, value in sorted(wins.items())},
        "median_surface_score_range": float(np.median(score_ranges)),
        "p10_surface_score_range": float(np.percentile(score_ranges, 10)),
        "fixed_coordinates": fixed,
    }


def _branch_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    definitions = {
        "short_low_k": {"length_factor": 0.8, "k": 2.0, "n": 8.0},
        "center": {"length_factor": 1.0, "k": 4.0, "n": 8.0},
        "long_high_k": {"length_factor": 1.2, "k": 6.0, "n": 8.0},
    }
    cells = {}
    wins: Counter[str] = Counter()
    for angle in ANGLES:
        for mouth in MOUTHS:
            selected = _cell(rows, angle, mouth)
            branches = {}
            for name, coordinate in definitions.items():
                matches = [
                    row for row in selected
                    if round(float(row["length_factor"]), 1)
                    == coordinate["length_factor"]
                    and float(row["k"]) == coordinate["k"]
                    and float(row["n"]) == coordinate["n"]
                ]
                if len(matches) != 1:
                    raise ValueError(
                        f"missing {name} branch at {angle}/{mouth}")
                row = matches[0]
                branches[name] = {
                    "surface_score": float(
                        row["responses"]["surface_score"]),
                    "s": float(row["s"]),
                }
            winner = max(
                branches, key=lambda name: branches[name]["surface_score"])
            wins[winner] += 1
            cells[f"{angle}deg-{mouth}mm"] = {
                "winner": winner,
                "branches": branches,
            }
    return {
        "definitions": definitions,
        "cells": cells,
        "winning_cell_counts": dict(sorted(wins.items())),
        "interpretation": (
            "K=4 wins one-axis K comparisons, but coordinated length/K "
            "changes expose short/low-K and long/high-K competitive ridges"),
    }


def _all_measured_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    roles = {"fit", "locked_validation", "historical_challenge"}
    rows = [
        row for row in index["rows"]
        if row["role"] in roles
        and int(row["coverage_deg"]) in ANGLES
        and int(row["mouth_mm"]) in MOUTHS
    ]
    challenge = _read(CHALLENGE)
    rows.extend({
        "id": row["id"],
        "coverage_deg": row["coverage_deg"],
        "mouth_mm": row["mouth_mm"],
        "length_factor": row["length_factor"],
        "k": row["k"],
        "n": row["n"],
        "s": row["derived_s"],
        "responses": row["responses"],
        "benchmark": False,
        "provenance": "fresh-v2-locked",
    } for row in challenge["evidence"])
    ridge = _read(RIDGE)
    rows.extend({
        "id": row["id"],
        "coverage_deg": row["coverage_deg"],
        "mouth_mm": row["mouth_mm"],
        "length_factor": row["length_factor"],
        "k": row["k"],
        "n": row["n"],
        "s": row["derived_s"],
        "responses": row["responses"],
        "benchmark": False,
        "provenance": "ridge-closure",
    } for row in ridge["evidence"])
    short_closure = _read(SHORT_CLOSURE)
    rows.extend({
        "id": row["id"],
        "coverage_deg": row["coverage_deg"],
        "mouth_mm": row["mouth_mm"],
        "length_factor": row["length_factor"],
        "k": row["k"],
        "n": row["n"],
        "s": row["derived_s"],
        "responses": row["responses"],
        "benchmark": False,
        "provenance": "short-length-closure",
    } for row in short_closure["evidence"])
    return rows


def _coordinate(row: dict[str, Any]) -> dict[str, float]:
    return {
        "length_factor": float(row["length_factor"]),
        "k": float(row["k"]),
        "n": float(row["n"]),
        "s": float(row["s"]),
    }


def _distance(first: dict[str, Any], second: dict[str, Any]) -> float:
    return float(np.sqrt(
        ((first["length_factor"]-second["length_factor"])/0.2)**2
        + ((first["k"]-second["k"])/2.0)**2
        + ((first["n"]-second["n"])/4.0)**2
    ))


def _components(rows: list[dict[str, Any]],
                maximum_distance: float) -> list[list[dict[str, Any]]]:
    remaining = set(range(len(rows)))
    output = []
    while remaining:
        seed = remaining.pop()
        pending = [seed]
        indexes = [seed]
        while pending:
            current = pending.pop()
            nearby = [
                index for index in list(remaining)
                if _distance(rows[current], rows[index]) <= maximum_distance
            ]
            for index in nearby:
                remaining.remove(index)
                pending.append(index)
                indexes.append(index)
        output.append([rows[index] for index in indexes])
    return output


def _zone_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    score_window = 1.0
    connection_distance = 1.1
    cells = {}
    best_s_by_coverage: dict[int, list[float]] = defaultdict(list)
    confirmed_cells = []
    hint_cells = []
    for angle in ANGLES:
        for mouth in MOUTHS:
            selected = _cell(rows, angle, mouth)
            benchmarks = [row for row in selected if row.get("benchmark")]
            if len(benchmarks) != 1:
                raise ValueError(
                    f"expected one benchmark at {angle}/{mouth}, "
                    f"found {len(benchmarks)}")
            benchmark = benchmarks[0]
            best = max(
                selected, key=lambda row: row["responses"]["surface_score"])
            best_score = float(best["responses"]["surface_score"])
            competitive = [
                row for row in selected
                if best_score-float(row["responses"]["surface_score"])
                <= score_window
            ]
            components = _components(competitive, connection_distance)
            benchmark_component = next((
                index for index, component in enumerate(components)
                if any(row["id"] == benchmark["id"] for row in component)
            ), None)
            best_component = next(
                index for index, component in enumerate(components)
                if any(row["id"] == best["id"] for row in component))
            alternative = [
                component for index, component in enumerate(components)
                if index != benchmark_component
            ]
            confirmed = [component for component in alternative
                         if len(component) >= 2]
            hints = [component for component in alternative
                     if len(component) == 1]
            cell_id = f"{angle}deg-{mouth}mm"
            if confirmed:
                confirmed_cells.append(cell_id)
            if hints:
                hint_cells.append(cell_id)
            cells[cell_id] = {
                "measured_count": len(selected),
                "benchmark": {
                    "id": benchmark["id"],
                    "surface_score": float(
                        benchmark["responses"]["surface_score"]),
                    "coordinate": _coordinate(benchmark),
                },
                "best": {
                    "id": best["id"],
                    "surface_score": best_score,
                    "coordinate": _coordinate(best),
                },
                "best_minus_benchmark_score": (
                    best_score
                    - float(benchmark["responses"]["surface_score"])),
                "best_to_benchmark_normalized_distance": _distance(
                    best, benchmark),
                "competitive_point_count": len(competitive),
                "competitive_component_sizes": sorted(
                    (len(component) for component in components),
                    reverse=True),
                "benchmark_in_competitive_set": (
                    benchmark_component is not None),
                "best_in_benchmark_component": (
                    benchmark_component == best_component),
                "confirmed_alternative_zone_count": len(confirmed),
                "single_point_alternative_hint_count": len(hints),
                "best_is_sampled_boundary": (
                    round(float(best["length_factor"]), 1) in {0.8, 1.2}
                    or float(best["k"]) in {2.0, 6.0}
                    or float(best["n"]) in {4.0, 16.0}
                ),
            }
            best_s_by_coverage[angle].append(float(best["s"]))

    s_guidance = {}
    for angle, values in sorted(best_s_by_coverage.items()):
        s_guidance[str(angle)] = {
            "cell_best_s": values,
            "minimum": float(min(values)),
            "median": float(np.median(values)),
            "maximum": float(max(values)),
        }
    return {
        "definition": {
            "competitive_score_window": score_window,
            "component_connection_distance": connection_distance,
            "distance_scaling": {
                "length_factor": 0.2, "k": 2.0, "n": 4.0},
            "confirmed_zone_minimum_points": 2,
            "interpretation": (
                "observed topology at sampled resolution; does not prove that "
                "unsampled zones are absent"),
        },
        "cells": cells,
        "cells_with_confirmed_alternative_zones": confirmed_cells,
        "cells_with_single_point_alternative_hints": hint_cells,
        "confirmed_alternative_cell_count": len(confirmed_cells),
        "single_point_hint_cell_count": len(hint_cells),
        "s_guidance_by_coverage": s_guidance,
    }


def _ridge_closure_audit(
    rows: list[dict[str, Any]],
    ridge: dict[str, Any],
) -> dict[str, Any]:
    cells = {}
    outward_k_wins = 0
    final_best_from_ridge = 0
    for cell_id, result in sorted(ridge["cells"].items()):
        angle_text, mouth_text = cell_id.split("-")
        angle = int(angle_text.removesuffix("deg"))
        mouth = int(mouth_text.removesuffix("mm"))
        outward_k = float(result["k"])
        inner_k = 2.0 if outward_k == 1.0 else 6.0
        n = float(result["n"])
        selected = _cell(rows, angle, mouth)
        ridge_rows = [
            row for row in selected
            if row.get("provenance") == "ridge-closure"
        ]
        inner_rows = [
            row for row in selected
            if row.get("provenance") != "ridge-closure"
            and float(row["k"]) == inner_k
            and float(row["n"]) == n
        ]
        if len(ridge_rows) != 3:
            raise ValueError(f"{cell_id}: expected three ridge responses")
        if not inner_rows:
            raise ValueError(f"{cell_id}: missing K={inner_k:g}/N={n:g} evidence")
        outward_best = max(
            ridge_rows, key=lambda row: row["responses"]["surface_score"])
        inner_best = max(
            inner_rows, key=lambda row: row["responses"]["surface_score"])
        final_best = max(
            selected, key=lambda row: row["responses"]["surface_score"])
        outward_score = float(outward_best["responses"]["surface_score"])
        inner_score = float(inner_best["responses"]["surface_score"])
        wins = outward_score > inner_score
        outward_k_wins += wins
        final_best_from_ridge += (
            final_best.get("provenance") == "ridge-closure"
        )
        cells[cell_id] = {
            "branch": result["branch"],
            "outward_k": outward_k,
            "inner_k": inner_k,
            "n": n,
            "length_bracketed_at_outward_k": bool(
                result["length_bracketed"]),
            "outward_best": {
                "id": outward_best["id"],
                "surface_score": outward_score,
                "coordinate": _coordinate(outward_best),
            },
            "inner_best": {
                "id": inner_best["id"],
                "surface_score": inner_score,
                "coordinate": _coordinate(inner_best),
            },
            "outward_minus_inner_score": outward_score-inner_score,
            "registered_k_boundary_status": (
                "best-measured-at-registered-k-boundary"
                if wins else "turned-over-by-inner-k-evidence"
            ),
            "final_measured_best": {
                "id": final_best["id"],
                "surface_score": float(
                    final_best["responses"]["surface_score"]),
                "coordinate": _coordinate(final_best),
                "provenance": final_best.get("provenance"),
            },
        }
    return {
        "tested_cells": len(cells),
        "length_bracketed_at_outward_k_cells": sum(
            row["length_bracketed_at_outward_k"] for row in cells.values()),
        "outward_k_won_over_inner_k_cells": outward_k_wins,
        "outward_k_turned_over_cells": len(cells)-outward_k_wins,
        "final_measured_best_from_ridge_cells": final_best_from_ridge,
        "cells": cells,
        "interpretation": (
            "closure is local to measured inner/outward K evidence; a winning "
            "K=1 or K=7 point is a registered-domain boundary seed, not a "
            "proven unconstrained optimum"
        ),
    }


def build() -> dict[str, Any]:
    index = _read(INDEX)
    ridge_result = _read(RIDGE)
    short_closure = _read(SHORT_CLOSURE)
    active_winners = _read(ACTIVE_WINNERS)
    wide_closure = _read(WIDE_CLOSURE)
    rows = _canonical_rows(index)
    length = _length_audit(rows)
    k_audit = _axis_audit(
        rows, "k", {"length_factor": 1.0, "n": 8.0})
    n_audit = _axis_audit(
        rows, "n", {"length_factor": 1.0, "k": 4.0})
    branches = _branch_audit(rows)
    measured_rows = _all_measured_rows(index)
    zones = _zone_audit(measured_rows)
    ridge = _ridge_closure_audit(measured_rows, ridge_result)
    active_seeds, active_s_guidance = _active_winner_seeds(
        active_winners, length["reference_length_mm"])
    artifact = {
        "schema_version": 1,
        "heuristic_id": "round_control_heuristics_v1",
        "status": (
            "surface-v2.3 measured seed rules; not a score predictor"),
        "domain": {
            "mouth_mm": list(MOUTHS),
            "coverage_half_angle_deg": list(ANGLES),
            "geometry": (
                "axisymmetric round-mouth, zero extension, 6 degree throat"),
        },
        "seed_controls": {"k": 4.0, "n": 8.0},
        "reference_length_mm": length["reference_length_mm"],
        "coupled_branch_seeds": branches,
        "active_surface_score_version": "v2.3",
        "active_measured_cell_seeds": active_seeds,
        "s_guidance_by_coverage": active_s_guidance,
        "rules": [
            {
                "id": "reference-length-seed",
                "action": (
                    "start each axis at the tabulated/bilinearly interpolated "
                    "reference OSSE length"),
                "evidence": length["center_control_comparison"],
            },
            {
                "id": "k4-seed",
                "action": (
                    "start K at 4; do not infer that larger K is better"),
                "evidence": k_audit,
            },
            {
                "id": "n8-seed",
                "action": (
                    "start N at 8; N=4 is the first alternate and N=16 is "
                    "not an initial candidate"),
                "evidence": n_audit,
            },
            {
                "id": "recheck-length-after-control-change",
                "action": (
                    "after a material K/N change, preserve the coverage-level "
                    "S seed first, then recheck at least ±10% length because "
                    "the preferred length interacts with K/N"),
                "evidence": length["interaction_audit"],
            },
            {
                "id": "coverage-s-seed",
                "action": (
                    "use the median S of active surface-v2.3 measured cell "
                    "winners as a physical ridge seed when K or N changes"),
                "evidence": active_s_guidance,
            },
            {
                "id": "coupled-length-k-branches",
                "action": (
                    "carry the short/low-K, center, and long/high-K branches "
                    "as distinct starts; do not optimize length or K alone"),
                "evidence": {
                    "winning_cell_counts": branches["winning_cell_counts"],
                    "winner_by_cell": {
                        key: value["winner"]
                        for key, value in branches["cells"].items()
                    },
                },
            },
            {
                "id": "retain-alternative-zones",
                "action": (
                    "retain observed competitive components outside the "
                    "benchmark component as alternate search starts"),
                "evidence": {
                    "confirmed_cells":
                        zones["cells_with_confirmed_alternative_zones"],
                    "single_point_hint_cells":
                        zones["cells_with_single_point_alternative_hints"],
                },
            },
            {
                "id": "respect-ridge-closure-status",
                "action": (
                    "use the active surface-v2.3 per-cell measured seed; "
                    "where K=1 or K=7 wins, label it a registered-domain "
                    "boundary rather than an unconstrained optimum"),
                "evidence": {
                    "outward_k_won_over_inner_k_cells":
                        ridge["outward_k_won_over_inner_k_cells"],
                    "outward_k_turned_over_cells":
                        ridge["outward_k_turned_over_cells"],
                    "length_bracketed_at_outward_k_cells":
                        ridge["length_bracketed_at_outward_k_cells"],
                },
            },
            {
                "id": "short-k1-length-brackets",
                "action": (
                    "use the measured Lx0.9 K=1/N=8 seed in the three "
                    "formerly unbracketed short cells; Lx0.8 closed the "
                    "short side in every case"),
                "evidence": short_closure["summary"],
            },
            {
                "id": "wide-coverage-mouth-edge-hypothesis",
                "action": (
                    "do not spend more round-horn simulations on the current "
                    "45/50-degree deficit; carry mouth-edge diffraction as "
                    "the leading provisional mechanism into intended "
                    "non-round and baffle geometry"),
                "status": (
                    "working physical hypothesis; infinite-baffle controls "
                    "were deliberately not run"),
                "evidence": {
                    "completed_candidates":
                        wide_closure["completed_candidate_count"],
                    "best_improvement_points":
                        wide_closure["best_initial_candidate"][
                            "surface_delta_points"],
                    "conditional_status":
                        wide_closure["conditional_status"],
                },
            },
            {
                "id": "hv-flat-compromise",
                "action": (
                    "for unequal H/V targets, combine independent axis seed "
                    "lengths using mouth-width/height score weights"),
                "status": "geometric seed; asymmetric acoustics unvalidated",
            },
            {
                "id": "hv-sag-compensation",
                "action": (
                    "optionally shorten only the axis with the shorter seed "
                    "length by using cylindrical sag equal to the axis-length "
                    "difference"),
                "status": (
                    "exact at principal mouth edges in current geometry; "
                    "acoustic benefit unvalidated"),
            },
        ],
        "audit": {
            "canonical_factorial_rows": len(rows),
            "length": length,
            "k": k_audit,
            "n": n_audit,
            "coupled_branches": branches,
            "ridge_closure": ridge,
            "short_length_closure": {
                "candidate_count": short_closure["candidate_count"],
                "summary": short_closure["summary"],
                "cells": short_closure["cells"],
            },
            "active_surface_v2_3_cell_seeds": {
                "cell_count": len(active_seeds),
                "cells": active_seeds,
            },
            "wide_coverage_closure": wide_closure,
            "observed_high_score_zones": zones,
        },
        "provenance": {
            "training_index": str(INDEX.relative_to(ROOT)),
            "training_index_sha256": _file_hash(INDEX),
            "challenge_results": str(CHALLENGE.relative_to(ROOT)),
            "challenge_results_sha256": _file_hash(CHALLENGE),
            "ridge_results": str(RIDGE.relative_to(ROOT)),
            "ridge_results_sha256": _file_hash(RIDGE),
            "short_length_closure_results": str(
                SHORT_CLOSURE.relative_to(ROOT)),
            "short_length_closure_results_sha256":
                _file_hash(SHORT_CLOSURE),
            "active_surface_v2_3_winners": str(
                ACTIVE_WINNERS.relative_to(ROOT)),
            "active_surface_v2_3_winners_sha256":
                _file_hash(ACTIVE_WINNERS),
            "wide_coverage_closure_results": str(
                WIDE_CLOSURE.relative_to(ROOT)),
            "wide_coverage_closure_results_sha256":
                _file_hash(WIDE_CLOSURE),
            "builder_sha256": _file_hash(Path(__file__)),
        },
    }
    _write(OUTPUT / "heuristics.json", artifact)
    card = f"""# Round Control Heuristics v1

Measured seed rules extracted from the canonical round factorial. This is not a
global score model.

- Reference length won
  {length['center_control_comparison']['direct_comparisons_won']} of
  {length['center_control_comparison']['direct_comparisons']} direct ±20%
  comparisons at K=4/N=8.
- Median score advantage was
  {length['center_control_comparison']['median_surface_score_gain']:.2f}
  points.
- K=4 won {k_audit['winning_value_counts'].get('4', 0)} of 25 center comparisons.
- N=8 won {n_audit['winning_value_counts'].get('8', 0)} of 25; N=4 won
  {n_audit['winning_value_counts'].get('4', 0)}; N=16 won
  {n_audit['winning_value_counts'].get('16', 0)}.
- {zones['confirmed_alternative_cell_count']} cells contain a measured
  competitive component outside the benchmark component; single-point hints
  are kept separate.
- Ridge closure bracketed length at the outward K in
  {ridge['length_bracketed_at_outward_k_cells']} of
  {ridge['tested_cells']} tested cells.
- The outward K=1/K=7 result beat the compatible inner-K evidence in
  {ridge['outward_k_won_over_inner_k_cells']} cells and turned over in
  {ridge['outward_k_turned_over_cells']} cells.
- The final measured cell best comes from ridge closure in
  {ridge['final_measured_best_from_ridge_cells']} of the 16 tested cells.
- The three formerly unbracketed K=1 short-length curves were all bracketed
  with three additional Lx0.8 measurements; no Lx0.7 cases were required.
- Active exact-cell seeds now come from the complete surface-v2.3 winner map.
- The ten-case wide-coverage closure found only a
  {wide_closure['best_initial_candidate']['surface_delta_points']:.3f}-point
  improvement. Further round cases and the conditional infinite-baffle controls
  were deliberately not run.

The H/V flat-length and sag outputs are starting constructions. No asymmetric or
sagged BEM evidence is claimed. Sag is excluded from total score and these
heuristics do not predict score.
"""
    (OUTPUT / "model_card.md").write_text(card, encoding="utf-8")
    return artifact


if __name__ == "__main__":
    result = build()
    print(f"built {result['heuristic_id']}")
