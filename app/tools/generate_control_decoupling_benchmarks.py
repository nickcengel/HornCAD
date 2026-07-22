#!/usr/bin/env python3
"""Register the best compatible historical result in every control-study cell."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .interactive_results import load_run
from .plan_control_decoupling_study import (
    ANGLES, MOUTHS, _baseline, _search_config, reusable_results,
)
from .surface_diagnostics import surface_diagnostics


def _mean_axis(result: dict[str, Any], path: tuple[str, ...]) -> float | None:
    values = []
    for axis in ("horizontal", "vertical"):
        selected: Any = result.get(axis, {})
        for key in path:
            selected = selected.get(key) if isinstance(selected, dict) else None
        if not isinstance(selected, (int, float)) or not math.isfinite(selected):
            return None
        values.append(float(selected))
    return sum(values) / 2


def build_benchmarks(source_root: Path, study_root: Path) -> dict[str, Any]:
    manifest = json.loads((study_root / "manifest.json").read_text())
    references = {
        (row["coverage_deg"], row["mouth_mm"]): row
        for row in manifest["coordinates"] if row["kind"] == "reference-anchor"
    }
    rescored = []
    state_cache: dict[str, dict[str, Any]] = {}
    for item in reusable_results(source_root):
        search = _search_config(
            _baseline(source_root, item.coverage_deg, item.mouth_mm) / "search.yaml")
        fixed_grid = np.geomspace(
            float(search["crossover_hz"]), float(search["upper_frequency_hz"]),
            int(math.ceil(math.log2(float(search["upper_frequency_hz"]) /
                                    float(search["crossover_hz"])) * 48)) + 1)
        response = source_root / item.response_path
        run = load_run(response.parent)
        diagnostics = surface_diagnostics(
            run, fixed_grid, fixed_band=True)
        score = (diagnostics.get("score") or {}).get("overall_percent")
        if diagnostics.get("status") != "available" or not isinstance(
                score, (int, float)):
            continue
        project = response.parent.parent / "project.yaml"
        if item.search_path not in state_cache:
            state_cache[item.search_path] = json.loads(
                (source_root / item.search_path / "search_state.json").read_text())
        records = [record for record in
                   state_cache[item.search_path].get("candidates", [])
                   if str(record.get("id")) == item.candidate_id]
        derived = records[0].get("derived", {}) if len(records) == 1 else {}
        s_values = [derived.get("s_h"), derived.get("s_v")]
        finite_s = [float(value) for value in s_values
                    if isinstance(value, (int, float)) and math.isfinite(value)]
        rescored.append((item, diagnostics, float(score),
                         sum(finite_s) / len(finite_s) if finite_s else None,
                         project))
    benchmarks = []
    for angle in ANGLES:
        for mouth in MOUTHS:
            cell = [row for row in rescored
                    if row[0].coverage_deg == angle and row[0].mouth_mm == mouth]
            if not cell:
                raise RuntimeError(f"no compatible historical benchmark: {angle}°/{mouth}")
            item, diagnostics, score, s, project = max(cell, key=lambda row: row[2])
            reference = references[(angle, mouth)]
            benchmarks.append({
                "id": f"benchmark-{angle}d-{mouth}mm",
                "coverage_deg": angle, "mouth_mm": mouth,
                "length_mm": item.length_mm,
                "length_factor": item.length_mm / reference["length_mm"],
                "k": item.k, "n": item.n, "s": s, "score": score,
                "date_unix": item.completed_at_unix,
                "search": item.search_path, "candidate_id": item.candidate_id,
                "response": item.response_path,
                "report": (f"../mouth-size-coverage-grid/{item.report_path}"
                           if item.report_path else None),
                "project": str(project.relative_to(source_root)),
                "same_as_reference": (
                    item.search_path == reference["reused_from"]["search"] and
                    item.candidate_id == reference["reused_from"]["candidate_id"]),
                "diagnostics": {
                    "containment": _mean_axis(
                        diagnostics, ("containment", "mean_fraction")),
                    "profile_rms": _mean_axis(
                        diagnostics, ("distribution", "rms_profile_error_db")),
                    "slice_rms": _mean_axis(
                        diagnostics, ("slice_energy_stability", "rms_departure_db")),
                    "outward_rise": _mean_axis(
                        diagnostics,
                        ("distribution", "rms_outward_rise_violation_db")),
                    "minus_six_rms": _mean_axis(
                        diagnostics, ("minus_six_line", "rms_coverage_error_deg")),
                },
            })
    return {
        "schema_version": 1,
        "role": "external historical benchmarks; excluded from the canonical design, primary fit, closure, pruning, and validation",
        "selection": "highest current surface score among solver-compatible retained symmetric zero-extension results in each cell",
        "benchmark_count": len(benchmarks),
        "benchmarks": benchmarks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path("examples/mouth-size-coverage-grid"))
    parser.add_argument("--study", type=Path,
                        default=Path("examples/control-decoupling"))
    args = parser.parse_args()
    output = build_benchmarks(args.source, args.study)
    path = args.study / "benchmarks.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
