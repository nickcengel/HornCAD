#!/usr/bin/env python3
"""Materialize adaptive K/N studies around selected coverage-grid winners."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import yaml


ANCHORS = (
    ("25deg/300x300-s-grid", "candidate-000"),
    ("25deg/450x450-s-grid", "candidate-000"),
    ("35deg/300x300-s-grid", "candidate-000"),
    ("35deg/400x400-s-grid", "candidate-002"),
    ("45deg/350x350", "candidate-003"),
    ("45deg/450x450-s-grid", "candidate-005"),
    ("60deg/300x300-s-grid", "candidate-008"),
    ("60deg/450x450-s-grid", "candidate-008"),
)
KN_POINTS = (
    (3.5, 10), (4.5, 10), (4, 5), (4, 15),
    (3, 10), (5, 10), (4, 2), (4, 20),
    (3.5, 5), (3.5, 15), (4.5, 5), (4.5, 15),
)


def _candidate_values(config: dict[str, Any], k: float, n: float) -> dict[str, float]:
    global_config = config["global"]
    horizontal = config["horizontal_basis"]
    vertical = config["vertical_basis"]
    return {
        "length_mm": float(global_config["length"]),
        "extension_mm": float(global_config.get("conical_extension_length", 0)),
        "osse_coverage_h_deg": float(horizontal["coverage_deg"]),
        "osse_coverage_v_deg": float(vertical["coverage_deg"]),
        "k_h": float(k), "k_v": float(k),
        "n_h": float(n), "n_v": float(n),
    }


def materialize_kn_search(source_project: Path, source_search: Path,
                          output_dir: Path) -> Path:
    if (output_dir / "search_state.json").exists():
        raise FileExistsError(f"refusing to overwrite started search: {output_dir}")
    seed = yaml.safe_load(source_project.read_text(encoding="utf-8"))
    source = yaml.safe_load(source_search.read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    config = seed["horncad_config"]
    intent = config.get("operating_intent", {})
    output_dir.mkdir(parents=True, exist_ok=True)
    output_seed = copy.deepcopy(seed)
    for axis in ("horizontal_basis", "vertical_basis"):
        output_seed["horncad_config"][axis]["k"] = 4.0
        output_seed["horncad_config"][axis]["n"] = 10.0
    (output_dir / "project.yaml").write_text(
        yaml.safe_dump(output_seed, sort_keys=False), encoding="utf-8")

    baseline = _candidate_values(config, 4, 10)
    pool = [{"label": f"K={k:g}, N={n:g}",
             "values": _candidate_values(config, k, n)}
            for k, n in KN_POINTS]
    solver = copy.deepcopy(source.get("solver", {
        "points_per_octave": 12,
        "elements_per_wavelength": 6,
        "angles": 91,
        "workers": 0,
    }))
    solver["workers"] = 10
    length = baseline["length_mm"]
    extension = baseline["extension_mm"]
    h_coverage = baseline["osse_coverage_h_deg"]
    v_coverage = baseline["osse_coverage_v_deg"]
    search = {
        "version": 1,
        "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": float(intent.get(
            "horizontal_coverage_deg", h_coverage)),
        "intended_coverage_v_deg": float(intent.get(
            "vertical_coverage_deg", v_coverage)),
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": 1 + len(pool),
        "initial_candidates": len(pool),
        "random_seed": int(source.get("random_seed", 17)),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [0.0, 8.0],
        "sampling_stability_points": float(
            source.get("sampling_stability_points", 2.0)),
        "confirmation_points_per_octave": float(
            source.get("confirmation_points_per_octave", 16)),
        "adaptive_kn": {
            "enabled": True,
            "margin_points": 3.0,
            "uncertainty_points": 1.5,
        },
        "bounds": {
            "length_mm": [length - 0.001, length + 0.001],
            "extension_mm": [extension, extension + 1e-6],
            "osse_coverage_h_deg": [h_coverage, h_coverage + 1e-6],
            "osse_coverage_v_deg": [v_coverage, v_coverage + 1e-6],
            "k_h": [3.0, 5.000001], "k_v": [3.0, 5.000001],
            "n_h": [2.0, 20.000001], "n_v": [2.0, 20.000001],
        },
        "initial_pool": pool,
        "solver": solver,
    }
    (output_dir / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False),
        encoding="utf-8")
    return output_dir


def generate_all(project_root: Path) -> list[Path]:
    outputs = []
    for relative_search, candidate_id in ANCHORS:
        source_dir = project_root / relative_search
        source_project = source_dir / "candidates" / candidate_id / "project.yaml"
        coverage_dir = source_dir.parent.name
        mouth = source_dir.name.split("-", 1)[0]
        output_dir = project_root / coverage_dir / f"{mouth}-kn-grid"
        outputs.append(materialize_kn_search(
            source_project, source_dir / "search.yaml", output_dir))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    for output in generate_all(args.project_root):
        print(output)


if __name__ == "__main__":
    main()
