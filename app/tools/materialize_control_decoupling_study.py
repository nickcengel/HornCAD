#!/usr/bin/env python3
"""Materialize the frozen control-decoupling manifest without running BEM."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import yaml

from .plan_control_decoupling_study import _baseline, _search_config
from .run_bem_search import VARIABLES, load_search, materialize_candidate


WAVES = (
    "core-axis", "boundary-sentinel", "axis-closure",
    "two-factor-face", "three-factor-corner", "locked-validation",
)


def _launch_review(plan: dict[str, Any]) -> str:
    rows = [
        f"| {wave} | {plan['wave_counts'][wave]['searches']} | "
        f"{plan['wave_counts'][wave]['candidates']} |"
        for wave in WAVES
    ]
    return f"""# Launch review

No BEM work is started by the planner or materializer. This file describes the
exact materialized queue that must be reviewed before launch.

- Frozen manifest SHA-256: `{plan['manifest_sha256']}`
- Required feasible, profile-distinct factorial/validation candidates: {plan['required_candidate_count']}
- Conditional axis-closure candidates: {plan['conditional_candidate_count']}
- Absolute new-BEM ceiling if every closure probe triggers: {plan['candidate_count']}
- Search directories: {plan['search_count']}
- Parallelism: two independent searches, ten solver workers each.
- Domain: 30-50 degree coverage half-angle and 250-450 mm square mouths.
- Geometry: symmetric, square, zero-extension round OS-SE horns only.

| Ordered wave | Searches | Candidates |
| --- | ---: | ---: |
{chr(10).join(rows)}

Every feasible, profile-distinct canonical center, axis, face, and corner runs.
There is no score-based factorial pruning because control effects may reverse by
mouth, coverage, derived S, or length. Locked validation runs last and is never
used to fit or select candidates.

Axis-closure searches are materialized but run only when the corresponding inner
endpoint points outward by the registered score/diagnostic rule. N=2 is never a
regular grid point; it is only the lower safety-bound probe after N=4 improves
over N=8.

The runner requires the exact hash above through
`--reviewed-manifest-sha256`; changing and rematerializing the manifest invalidates
that approval. A failed search releases its slot and is recorded while unrelated
work continues. The study reports blocked rather than complete if any isolated
failure remains.
"""


def _values(row: dict[str, Any]) -> dict[str, float]:
    return {
        "length_mm": float(row["length_mm"]), "extension_mm": 0.0,
        "osse_coverage_h_deg": float(row["coverage_deg"]),
        "osse_coverage_v_deg": float(row["coverage_deg"]),
        "k_h": float(row["k"]), "k_v": float(row["k"]),
        "n_h": float(row["n"]), "n_v": float(row["n"]),
    }


def coordinate_wave(row: dict[str, Any]) -> str | None:
    if row.get("status") == "conditional" and row.get("stage") == "axis-closure":
        return "axis-closure"
    if row.get("status") != "planned":
        return None
    stage = row["stage"]
    if stage in {"core-axis", "boundary-sentinel", "locked-validation"}:
        return stage
    if stage == "two-factor-face":
        return stage
    if stage == "three-factor-corner":
        return stage
    raise ValueError(f"planned coordinate has unknown stage: {stage}")


def _search_dir(output_root: Path, angle: int, mouth: int, wave: str,
                coordinate_id: str | None = None) -> Path:
    name = f"{mouth}x{mouth}"
    if coordinate_id:
        suffix = coordinate_id.split(f"{mouth}mm-", 1)[-1]
        name += "-" + suffix
    return output_root / "searches" / wave / f"{angle}deg" / name


def _manifest_hash(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def materialize_search(
        source_root: Path, output_root: Path, manifest_hash: str,
        wave: str, rows: list[dict[str, Any]], solver_workers: int = 10,
        coordinate_id: str | None = None) -> Path:
    first = rows[0]
    angle, mouth = int(first["coverage_deg"]), int(first["mouth_mm"])
    if any((row["coverage_deg"], row["mouth_mm"]) != (angle, mouth)
           for row in rows):
        raise ValueError("one fixed search may contain only one mouth/coverage cell")
    output = _search_dir(output_root, angle, mouth, wave, coordinate_id)
    existing_search = output / "search.yaml"
    if existing_search.is_file():
        existing = _search_config(existing_search)
        metadata = existing.get("control_decoupling", {})
        if (metadata.get("manifest_sha256") == manifest_hash and
                metadata.get("coordinate_ids") == [row["id"] for row in rows]):
            return output
        if (output / "search_state.json").exists():
            raise RuntimeError(f"refusing to replace a started search: {output}")
    source = _baseline(source_root, angle, mouth)
    source_search = _search_config(source / "search.yaml")
    seed = yaml.safe_load((source / "project.yaml").read_text(encoding="utf-8"))
    intent = {
        "intended_coverage_h_deg": angle,
        "intended_coverage_v_deg": angle,
        "lower_frequency_hz": float(source_search["lower_frequency_hz"]),
        "crossover_hz": float(source_search["crossover_hz"]),
        "upper_frequency_hz": float(source_search["upper_frequency_hz"]),
    }
    seed, _ = materialize_candidate(seed, _values(first), intent)
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    values = [_values(row) for row in rows]
    bounds: dict[str, list[float]] = {}
    for variable in VARIABLES:
        low = min(item[variable] for item in values)
        high = max(item[variable] for item in values)
        if high - low < 1e-6:
            low -= 1e-6
            high += 1e-6
        else:
            low -= 1e-6
            high += 1e-6
        bounds[variable] = [low, high]
    solver = copy.deepcopy(source_search["solver"])
    solver["workers"] = solver_workers
    search: dict[str, Any] = {
        "version": 1, "seed_yaml": "project.yaml",
        **intent, "max_evaluations": len(rows),
        "initial_candidates": max(0, len(rows) - 1),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.049, 4.001],
        "sampling_stability_points": float(source_search.get(
            "sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source_search.get(
            "confirmation_points_per_octave", 16)),
        "adaptive_pruning": {"enabled": False},
        "fixed_design": True, "bounds": bounds, "solver": solver,
        "control_decoupling": {
            "design": "canonical-three-level-factorial",
            "wave": wave, "manifest_sha256": manifest_hash,
            "coordinate_ids": [row["id"] for row in rows],
            "coordinates": rows,
        },
    }
    # The seed itself is proposal zero. A one-coordinate search must omit the
    # initial_pool key entirely; an explicit empty list is rejected by load_search.
    if len(rows) > 1:
        search["initial_pool"] = [{
            "label": row["id"], "values": _values(row),
        } for row in rows[1:]]
    (output / "search.yaml").write_text(yaml.safe_dump(
        {"bem_candidate_search": search}, sort_keys=False), encoding="utf-8")
    load_search(output / "search.yaml")
    return output


def materialize_study(source_root: Path, output_root: Path,
                      solver_workers: int = 10) -> dict[str, Any]:
    manifest_path = output_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = _manifest_hash(manifest)
    grouped: dict[tuple[str, int, int, str | None], list[dict[str, Any]]] = {}
    for row in manifest["coordinates"]:
        wave = coordinate_wave(row)
        if wave is None:
            continue
        coordinate_id = row["id"] if wave == "axis-closure" else None
        key = (wave, int(row["coverage_deg"]), int(row["mouth_mm"]),
               coordinate_id)
        grouped.setdefault(key, []).append(row)
    searches = []
    for (wave, angle, mouth, coordinate_id), rows in sorted(
            grouped.items(), key=lambda item: (
                WAVES.index(item[0][0]), item[0][1], item[0][2],
                item[0][3] or "")):
        path = materialize_search(
            source_root, output_root, digest, wave, rows, solver_workers,
            coordinate_id)
        searches.append({
            "wave": wave, "coverage_deg": angle, "mouth_mm": mouth,
            "path": str(path.relative_to(output_root)),
            "candidate_count": len(rows),
            "coordinate_ids": [row["id"] for row in rows],
        })
    planned_ids = {row["id"] for row in manifest["coordinates"]
                   if row["status"] in {"planned", "conditional"}}
    materialized_ids = {identifier for item in searches
                        for identifier in item["coordinate_ids"]}
    if materialized_ids != planned_ids:
        missing = sorted(planned_ids - materialized_ids)
        extra = sorted(materialized_ids - planned_ids)
        raise RuntimeError(f"materialization mismatch; missing={missing}, extra={extra}")
    expected_paths = {output_root / item["path"] for item in searches}
    stale_paths = sorted({path.parent for path in
                          (output_root / "searches").rglob("search.yaml")} -
                         expected_paths)
    for stale in stale_paths:
        if (stale / "search_state.json").exists():
            raise RuntimeError(f"refusing to remove a started stale search: {stale}")
        shutil.rmtree(stale)
    plan = {
        "schema_version": 1, "manifest_sha256": digest,
        "solver_workers": solver_workers,
        "search_count": len(searches),
        "candidate_count": len(materialized_ids),
        "required_candidate_count": sum(
            row["status"] == "planned" for row in manifest["coordinates"]),
        "conditional_candidate_count": sum(
            row["status"] == "conditional" for row in manifest["coordinates"]),
        "wave_counts": {
            wave: {
                "searches": sum(item["wave"] == wave for item in searches),
                "candidates": sum(item["candidate_count"] for item in searches
                                  if item["wave"] == wave),
            } for wave in WAVES
        },
        "searches": searches,
    }
    (output_root / "execution_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    (output_root / "launch_review.md").write_text(
        _launch_review(plan), encoding="utf-8")
    from .report_control_decoupling_study import refresh_index
    refresh_index(output_root)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("examples/mouth-size-coverage-grid"))
    parser.add_argument("--output", type=Path,
                        default=Path("examples/control-decoupling"))
    parser.add_argument("--solver-workers", type=int, default=10)
    args = parser.parse_args()
    plan = materialize_study(args.source, args.output, args.solver_workers)
    print(json.dumps({key: plan[key] for key in (
        "search_count", "candidate_count", "wave_counts")}, indent=2))


if __name__ == "__main__":
    main()
