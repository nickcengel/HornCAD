#!/usr/bin/env python3
"""Learn transferable BEM diagnostic response surfaces from completed evidence.

The unit of validation is a complete mouth/coverage cell. This prevents dense
local optimizer traces from making a model look accurate when it cannot transfer
to a new design request.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .analyze_bem_design_space import DIAGNOSTICS, Candidate, load_candidates
from .bem_learning import merged_candidate_policy
from .bem_learning import nominal_candidate_rejections
from .run_bem_domain_mapping_program import (
    Proposal, _baseline, _existing_symmetric_points,
    _independent_control_geometry, _normalized_profile, _physical_distance,
    _source_project, snap_k_n,
)


PROFILE_COMPONENTS = 3
RIDGE_LAMBDAS = (1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)


def _quadratic(x: np.ndarray) -> np.ndarray:
    columns = [np.ones(len(x)), *[x[:, index] for index in range(x.shape[1])]]
    columns.extend(
        x[:, left] * x[:, right]
        for left in range(x.shape[1])
        for right in range(left, x.shape[1])
    )
    return np.column_stack(columns)


def _ridge_fit(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    gram = x.T @ x
    regularizer = np.eye(x.shape[1]) * penalty
    regularizer[0, 0] = 0.0
    return np.linalg.solve(gram + regularizer, x.T @ y)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = actual - predicted
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "r2": 1.0 - float(np.sum(error ** 2)) / max(denominator, 1e-12),
    }


def build_physical_dataset(root: Path) -> tuple[list[Candidate], np.ndarray, dict[str, Any]]:
    policy = merged_candidate_policy()
    allowed_angles = set(policy["coverage_deg"])
    allowed_mouths = set(policy["mouth_mm"])
    candidates, _ = load_candidates(root)
    candidates = [item for item in candidates
                  if item.coverage_deg in allowed_angles and item.mouth_mm in allowed_mouths]
    profiles = []
    for item in candidates:
        baseline = _baseline(root, int(item.coverage_deg), int(item.mouth_mm))
        config = _source_project(baseline)["horncad_config"]
        profiles.append(_normalized_profile(
            config, item.coverage_deg, item.length_mm, item.k, item.n))
    profiles_array = np.asarray(profiles)
    profile_center = np.mean(profiles_array, axis=0)
    centered = profiles_array - profile_center
    _, singular, basis = np.linalg.svd(centered, full_matrices=False)
    profile_basis = basis[:PROFILE_COMPONENTS]
    scores = centered @ profile_basis.T
    captured = float(np.sum(singular[:PROFILE_COMPONENTS] ** 2) /
                     max(np.sum(singular ** 2), 1e-12))
    # Physical coordinates only. K, N and S remain labels for steering rules;
    # they cannot create model information if the actual horn surface is unchanged.
    raw = np.column_stack([
        [item.coverage_deg for item in candidates],
        [item.mouth_mm for item in candidates],
        [item.length_mm / item.mouth_mm for item in candidates],
        scores,
    ])
    center = np.mean(raw, axis=0)
    scale = np.maximum(np.std(raw, axis=0), 1e-9)
    x = (raw - center) / scale
    metadata = {
        "coordinate_names": [
            "coverage_deg", "mouth_mm", "length_over_mouth",
            *[f"radial_profile_pc{index + 1}" for index in range(PROFILE_COMPONENTS)],
        ],
        "coordinate_center": center.tolist(),
        "coordinate_scale": scale.tolist(),
        "profile_center": profile_center.tolist(),
        "profile_basis": profile_basis.tolist(),
        "profile_variance_captured": captured,
    }
    return candidates, x, metadata


def leave_cell_out_analysis(root: Path) -> dict[str, Any]:
    candidates, x, metadata = build_physical_dataset(root)
    design = _quadratic(x)
    groups: dict[tuple[float, float], list[int]] = defaultdict(list)
    for index, item in enumerate(candidates):
        groups[(item.coverage_deg, item.mouth_mm)].append(index)
    outputs: dict[str, Any] = {}
    for diagnostic in DIAGNOSTICS:
        y = np.asarray([item.diagnostics[diagnostic] for item in candidates])
        predictions = np.empty(len(y))
        chosen_penalties = []
        cell_results = []
        for cell, held_indices in sorted(groups.items()):
            held = np.asarray(held_indices, dtype=int)
            train = np.asarray([index for index in range(len(y))
                                if index not in set(held_indices)], dtype=int)
            # Choose regularization without looking at the held-out cell.
            validation = train[::5]
            fit = np.asarray([index for index in train if index not in set(validation)],
                             dtype=int)
            penalty = min(RIDGE_LAMBDAS, key=lambda value: _metrics(
                y[validation], design[validation] @ _ridge_fit(
                    design[fit], y[fit], value))["rmse"])
            coefficient = _ridge_fit(design[train], y[train], penalty)
            predictions[held] = design[held] @ coefficient
            chosen_penalties.append(penalty)
            cell_results.append({
                "coverage_deg": cell[0], "mouth_mm": cell[1],
                "count": len(held), **_metrics(y[held], predictions[held]),
            })
        outputs[diagnostic] = {
            **_metrics(y, predictions),
            "median_selected_ridge_penalty": float(np.median(chosen_penalties)),
            "worst_cells": sorted(cell_results, key=lambda item: item["rmse"],
                                  reverse=True)[:5],
            "cells": cell_results,
        }
    return {
        "schema_version": 1,
        "method": "leave-one-mouth-coverage-cell-out quadratic ridge in physical geometry",
        "candidate_count": len(candidates), "cell_count": len(groups),
        "physical_representation": metadata,
        "diagnostic_validation": outputs,
    }


def _cell_transfer_priority(analysis: dict[str, Any]) -> dict[tuple[int, int], float]:
    """Combine normalized diagnostic transfer errors without privileging final score."""
    priority: dict[tuple[int, int], list[float]] = defaultdict(list)
    for result in analysis["diagnostic_validation"].values():
        scale = max(float(result["rmse"]), 1e-9)
        for cell in result["cells"]:
            key = (int(cell["coverage_deg"]), int(cell["mouth_mm"]))
            priority[key].append(float(cell["rmse"]) / scale)
    return {key: float(np.mean(values)) for key, values in priority.items()}


def plan_controlled_learning_batch(
        root: Path, analysis: dict[str, Any], batch_size: int = 30,
        learning_round: int = 1,
        ) -> dict[str, Any]:
    """Select direct one-control contrasts where current transfer is weakest."""
    policy = merged_candidate_policy()
    length_materiality = float(policy["normalized_length_materiality_fraction"])
    profile_materiality = float(
        policy["normalized_profile_rms_materiality_fraction"])
    priorities = _cell_transfer_priority(analysis)
    pool: dict[tuple[int, int, float, float, float], dict[str, Any]] = {}
    audit_counts: dict[str, int] = defaultdict(int)
    for (coverage, mouth), cell_priority in sorted(priorities.items()):
        baseline = _baseline(root, coverage, mouth)
        config = _source_project(baseline)["horncad_config"]
        completed, _ = load_candidates(root)
        anchor_candidate = max(
            (item for item in completed if item.coverage_deg == coverage and
             item.mouth_mm == mouth and abs(item.k - 4) < 0.01 and
             abs(item.n - 10) < 0.01), key=lambda item: item.score)
        anchors = _existing_symmetric_points(
            root, coverage, mouth, anchor_candidate.length_mm, config)
        for anchor in anchors:
            variants = [
                ("length", anchor["length_mm"] * factor, anchor["k"], anchor["n"])
                for factor in (0.85, 1.15)
            ]
            variants += [
                ("k", anchor["length_mm"], *snap_k_n(anchor["k"] + delta,
                                                       anchor["n"]))
                for delta in (-1.0, 1.0)
            ]
            variants += [
                ("n", anchor["length_mm"], *snap_k_n(anchor["k"],
                                                       anchor["n"] + delta))
                for delta in (-4.0, 4.0)
            ]
            for control, length, k, n in variants:
                if (control == "length" and
                        policy.get("reject_repeated_k4_n10_length_axis") and
                        abs(k - 4.0) < 0.01 and abs(n - 10.0) < 0.01):
                    audit_counts["rejected_existing_k4_n10_length_axis"] += 1
                    continue
                rejected_rules = nominal_candidate_rejections(
                    coverage, mouth, k, n)
                if rejected_rules:
                    audit_counts["rejected_by_nominal_learning_rules"] += 1
                    continue
                if not (2.0 <= k <= 6.0 and 3.0 <= n <= 17.0):
                    audit_counts["outside_informative_control_bounds"] += 1
                    continue
                geometry = _independent_control_geometry(
                    config, coverage, length, k, n)
                if geometry is None:
                    audit_counts["geometry_rejected"] += 1
                    continue
                profile = _normalized_profile(config, coverage, length, k, n)
                anchor_profile_rms = float(np.sqrt(np.mean(
                    (profile - anchor["profile"]) ** 2)))
                if control in {"k", "n"} and anchor_profile_rms < profile_materiality:
                    audit_counts[f"{control}_rejected_no_material_surface_change"] += 1
                    continue
                distances = [_physical_distance(
                    length, profile, item["length_mm"], item["profile"],
                    anchor_candidate.length_mm, length_materiality,
                    profile_materiality)[0] for item in anchors]
                nearest = min(distances)
                if nearest < 1.0:
                    audit_counts["rejected_near_existing_geometry"] += 1
                    continue
                key = (coverage, mouth, round(length, 3), k, n)
                contrast_change = (
                    abs(length / anchor["length_mm"] - 1) / length_materiality
                    if control == "length" else
                    anchor_profile_rms / profile_materiality)
                # Prefer material but local contrasts. Very remote points already proved
                # boundaries and are not useful response-surface measurements.
                locality = 1.0 / (1.0 + abs(contrast_change - 2.0))
                value = {
                    "coverage_deg": coverage, "mouth_mm": mouth,
                    "control": control, "length_mm": round(length, 3),
                    "k": k, "n": n, "s": float(geometry["s"]),
                    "exit_angle_deg": float(geometry["exit_angle_deg"]),
                    "normalized_curvature_radius": float(
                        geometry["normalized_curvature_radius"]),
                    "cell_transfer_priority": cell_priority,
                    "nearest_existing_physical_distance": nearest,
                    "anchor_profile_rms_change_fraction": anchor_profile_rms,
                    "selection_value": cell_priority + 0.5 * locality +
                    0.1 * min(nearest, 3.0),
                    "contrast_search": anchor["search"],
                    "contrast_candidate_id": anchor["candidate_id"],
                    "anchor_length_mm": anchor["length_mm"],
                    "anchor_k": anchor["k"], "anchor_n": anchor["n"],
                }
                compared = (length, k, n)[("length", "k", "n").index(control)]
                anchor_compared = anchor[
                    ("length_mm", "k", "n")[("length", "k", "n").index(control)]]
                value["direction"] = (
                    "increase" if compared > anchor_compared else "decrease")
                if key not in pool or value["selection_value"] > pool[key]["selection_value"]:
                    pool[key] = value
    selected: list[dict[str, Any]] = []
    per_cell: dict[tuple[int, int], int] = defaultdict(int)
    per_cell_control: set[tuple[int, int, str]] = set()
    # A balanced batch gives each control an equal opportunity while still focusing
    # measurements on demonstrated transfer gaps.
    quota = math.ceil(batch_size / 3)
    for control in ("length", "k", "n"):
        options = sorted((item for item in pool.values()
                          if item["control"] == control),
                         key=lambda item: item["selection_value"], reverse=True)
        direction_quota = quota // 2
        for direction in ("decrease", "increase"):
            for item in (candidate for candidate in options
                         if candidate["direction"] == direction):
                cell = (item["coverage_deg"], item["mouth_mm"])
                cell_control = (*cell, control)
                if per_cell[cell] >= 2 or cell_control in per_cell_control:
                    continue
                selected.append(item)
                per_cell[cell] += 1
                per_cell_control.add(cell_control)
                if sum(candidate["control"] == control and
                       candidate["direction"] == direction
                       for candidate in selected) >= direction_quota:
                    break
        for item in options:
            if sum(candidate["control"] == control for candidate in selected) >= quota:
                break
            cell = (item["coverage_deg"], item["mouth_mm"])
            cell_control = (*cell, control)
            if per_cell[cell] >= 2 or cell_control in per_cell_control:
                continue
            selected.append(item)
            per_cell[cell] += 1
            per_cell_control.add(cell_control)
    selected = selected[:batch_size]
    proposals = []
    for slot, item in enumerate(selected):
        control = item["control"]
        direction = item["direction"]
        hypothesis = (
            f"At fixed {', '.join(name for name in ('length', 'K', 'N') if name.lower() != control)}, "
            f"{direction} {control} materially changes the horn surface and tests diagnostic "
            f"transfer in a cell with normalized held-cell error {item['cell_transfer_priority']:.2f}."
        )
        proposal = Proposal(
            coverage_deg=item["coverage_deg"], mouth_mm=item["mouth_mm"],
            batch=2, slot=slot, s=item["s"], length_mm=item["length_mm"],
            k=item["k"], n=item["n"],
            mouth_length_ratio=item["mouth_mm"] / item["length_mm"],
            exit_angle_deg=item["exit_angle_deg"],
            normalized_curvature_radius=item["normalized_curvature_radius"],
            acquisition="held-cell transfer gap + direct physical contrast",
            nearest_distance=item["nearest_existing_physical_distance"],
            matched_parameter=control,
            anchor_length_mm=item["anchor_length_mm"],
            anchor_k=item["anchor_k"], anchor_n=item["anchor_n"],
            coordinate_label=f"learn-{control}-{slot:02d}",
            hypothesis=hypothesis,
            contrast_search=item["contrast_search"],
            contrast_candidate_id=item["contrast_candidate_id"],
            enforced_learning_rules=(
                "study-domain-v1", "remote-extremes-closed-v1",
                "coarse-control-grid-v1", "reuse-existing-length-axis-v1",
                "physical-profile-materiality-v1", "score-materiality-v1"),
            learning_round=learning_round,
        )
        proposals.append(proposal)
        item["proposal"] = proposal.__dict__
        item["hypothesis"] = hypothesis
    return {
        "schema_version": 1,
        "design": "held-cell-error-controlled-physical-contrasts",
        "batch_size": len(selected),
        "control_counts": {control: sum(item["control"] == control for item in selected)
                           for control in ("length", "k", "n")},
        "direction_counts": {
            f"{control}_{direction}": sum(
                item["control"] == control and item["direction"] == direction
                for item in selected)
            for control in ("length", "k", "n")
            for direction in ("decrease", "increase")
        },
        "cell_counts": {f"{key[0]}deg/{key[1]}mm": value
                        for key, value in sorted(per_cell.items()) if value},
        "audit_rejections": dict(sorted(audit_counts.items())),
        "candidates": selected,
    }


def render_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BEM transferable-response audit", "",
        f"This audit uses {analysis['candidate_count']} completed candidates in "
        f"{analysis['cell_count']} retained mouth/coverage cells. Entire cells are held out "
        "during validation; dense local samples cannot leak into their own test set.", "",
        f"Three normalized radial-profile modes retain "
        f"{100 * analysis['physical_representation']['profile_variance_captured']:.3f}% "
        "of measured profile variance. K, N, and S are retained as steering labels but are "
        "not model coordinates: they only matter through the horn surface they create.", "",
        "| Diagnostic | Held-cell MAE | RMSE | R² |", "| --- | ---: | ---: | ---: |",
    ]
    for name, result in analysis["diagnostic_validation"].items():
        lines.append(f"| {name} | {result['mae']:.3f} | {result['rmse']:.3f} | "
                     f"{result['r2']:.3f} |")
    lines += ["", "## Largest transfer gaps", ""]
    for name, result in analysis["diagnostic_validation"].items():
        cells = ", ".join(
            f"{item['mouth_mm']:g} mm/{item['coverage_deg']:g}° (RMSE {item['rmse']:.2f})"
            for item in result["worst_cells"])
        lines.append(f"- **{name}:** {cells}.")
    lines += ["", "These gaps, combined with physical novelty and a matched existing "
              "contrast, determine the next measured batch. Matrix rank alone does not."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--learning-round", type=int, default=1)
    args = parser.parse_args()
    analysis = leave_cell_out_analysis(args.root)
    if args.json:
        args.json.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(analysis), encoding="utf-8")
    if args.manifest:
        manifest = plan_controlled_learning_batch(
            args.root, analysis, args.batch_size, args.learning_round)
        args.manifest.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not args.json and not args.markdown and not args.manifest:
        print(render_markdown(analysis), end="")


if __name__ == "__main__":
    main()
