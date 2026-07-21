#!/usr/bin/env python3
"""Create comparable intermediate-angle S sweeps for the coverage study."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import yaml

try:
    from .generate_coverage_s_grid import _candidate_values, length_for_s
except ImportError:
    from generate_coverage_s_grid import _candidate_values, length_for_s


COVERAGES = (30.0, 40.0, 50.0)
MOUTH_SIZES_MM = (250, 300, 350, 400, 450, 500)
S_TARGETS = tuple(round(0.5 + 0.25 * index, 2) for index in range(15))
COMPARABLE_30_S_TARGETS = (0.7, 1.0, 1.3, 1.6, 1.9, 2.2, 2.5, 2.8, 3.0)


def study_grid(coverage: float) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Return the authored grid appropriate to an intermediate coverage."""
    if coverage == 30.0:
        return ((200, 250, 300, 350, 400, 450, 500),
                COMPARABLE_30_S_TARGETS)
    return (MOUTH_SIZES_MM, S_TARGETS)


def materialize_coverage_sweep(source_project: Path, source_search: Path,
                               output_dir: Path, coverage: float,
                               targets: tuple[float, ...] = S_TARGETS) -> Path:
    if (output_dir / "search_state.json").exists():
        raise FileExistsError(f"refusing to overwrite started search: {output_dir}")
    seed = yaml.safe_load(source_project.read_text(encoding="utf-8"))
    source = yaml.safe_load(source_search.read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    config = seed["horncad_config"]
    for axis in ("horizontal_basis", "vertical_basis"):
        config[axis]["coverage_deg"] = float(coverage)
        config[axis]["k"] = 4.0
        config[axis]["n"] = 10.0
    intent = config.setdefault("operating_intent", {})
    intent["horizontal_coverage_deg"] = float(coverage)
    intent["vertical_coverage_deg"] = float(coverage)
    lengths = [length_for_s(config, target) for target in targets]
    global_config = config["global"]
    global_config["length"] = lengths[0]
    global_config["measured_total_length"] = (
        lengths[0] + float(global_config.get("conical_extension_length", 0)))
    for axis in ("horizontal_basis", "vertical_basis"):
        config[axis]["solved_s"] = targets[0]

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    pool = [{
        "label": f"coverage {coverage:g}°, S={target:g}, L={length:g} mm",
        "values": _candidate_values(length, coverage, 4.0, 10.0),
    } for target, length in zip(targets[1:], lengths[1:])]
    # Preserve one far-boundary observation even when the declining points
    # before it are adaptively pruned. This detects an unexpected second rise
    # without densely filling a known-poor tail.
    pool[-1]["required"] = True
    solver = copy.deepcopy(source.get("solver", {
        "points_per_octave": 12, "elements_per_wavelength": 6,
        "angles": 91, "workers": 0,
    }))
    solver["workers"] = 10
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": float(coverage),
        "intended_coverage_v_deg": float(coverage),
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": len(targets),
        "initial_candidates": len(pool),
        "random_seed": int(source.get("random_seed", 17)),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [min(targets) - 0.01, max(targets) + 0.01],
        "sampling_stability_points": float(
            source.get("sampling_stability_points", 2.0)),
        "confirmation_points_per_octave": float(
            source.get("confirmation_points_per_octave", 16)),
        "adaptive_pruning": {
            "enabled": True, "minimum_evaluations": 5,
            "required_consecutive_declines": 3,
            "margin_points": 3.0, "confidence_sigma": 2.0,
            "uncertainty_floor_points": 1.5,
        },
        "bounds": {
            "length_mm": [min(lengths) - 0.001, max(lengths) + 0.001],
            "extension_mm": [0.0, 1e-6],
            "osse_coverage_h_deg": [coverage, coverage + 1e-6],
            "osse_coverage_v_deg": [coverage, coverage + 1e-6],
            "k_h": [4.0, 4.000001], "k_v": [4.0, 4.000001],
            "n_h": [10.0, 10.000001], "n_v": [10.0, 10.000001],
        },
        "initial_pool": pool, "solver": solver,
    }
    (output_dir / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False),
        encoding="utf-8")
    return output_dir


def generate_all(project_root: Path) -> list[Path]:
    outputs = []
    for coverage in COVERAGES:
        mouths, targets = study_grid(coverage)
        for mouth in mouths:
            template_angle = 45 if (project_root / "45deg" / f"{mouth}x{mouth}").is_dir() else 35
            source_dir = project_root / f"{template_angle}deg" / f"{mouth}x{mouth}"
            output = project_root / f"{coverage:g}deg" / f"{mouth}x{mouth}-s-grid"
            if (output / "search.yaml").exists():
                outputs.append(output)
                continue
            outputs.append(materialize_coverage_sweep(
                source_dir / "project.yaml", source_dir / "search.yaml",
                output, coverage, targets))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    for output in generate_all(args.project_root):
        print(output)


if __name__ == "__main__":
    main()
