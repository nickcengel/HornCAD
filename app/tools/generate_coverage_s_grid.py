#!/usr/bin/env python3
"""Materialize equal-opportunity S sweeps beside every coverage-grid search."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from scipy.optimize import brentq
import yaml

try:
    from .export_horncad import solved_s
except ImportError:
    from export_horncad import solved_s


DEFAULT_S_TARGETS = (0.7, 1.0, 1.3, 1.6, 1.9, 2.2, 2.5, 2.8, 3.0)


def length_for_s(config: dict[str, Any], target_s: float) -> float:
    global_config = config["global"]
    basis = config["horizontal_basis"]
    mouth_radius = float(global_config["mouth_width"]) / 2.0

    def error(length: float) -> float:
        return solved_s(
            length, float(global_config["throat_radius"]),
            float(basis["coverage_deg"]), float(basis["k"]),
            float(basis["n"]), mouth_radius,
            float(global_config["throat_angle_deg"])) - target_s

    lower = 1.0
    upper = max(100.0, float(global_config["mouth_width"]) * 5.0)
    if error(lower) < 0 or error(upper) > 0:
        raise ValueError(f"could not bracket S={target_s:g}")
    return round(float(brentq(error, lower, upper)), 3)


def _candidate_values(length: float, coverage: float, k: float,
                      n: float) -> dict[str, float]:
    return {
        "length_mm": length,
        "extension_mm": 0.0,
        "osse_coverage_h_deg": coverage,
        "osse_coverage_v_deg": coverage,
        "k_h": k,
        "k_v": k,
        "n_h": n,
        "n_v": n,
    }


def materialize_s_grid(source_search: Path, targets: tuple[float, ...]) -> Path:
    if len(targets) < 2 or any(target <= 0.0 for target in targets):
        raise ValueError("at least two positive S targets are required")
    if len(set(targets)) != len(targets):
        raise ValueError("S targets must be unique")
    source = yaml.safe_load(source_search.read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    source_seed = Path(source.get("seed_yaml", "project.yaml"))
    if not source_seed.is_absolute():
        source_seed = source_search.parent / source_seed
    seed = yaml.safe_load(source_seed.read_text(encoding="utf-8"))
    config = seed["horncad_config"]
    horizontal = config["horizontal_basis"]
    coverage = float(horizontal["coverage_deg"])
    k = float(horizontal["k"])
    n = float(horizontal["n"])
    lengths = [length_for_s(config, target) for target in targets]

    output_dir = source_search.parent.with_name(
        source_search.parent.name + "-s-grid")
    if (output_dir / "search_state.json").exists():
        raise FileExistsError(
            f"refusing to overwrite started search: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_seed = copy.deepcopy(seed)
    output_global = output_seed["horncad_config"]["global"]
    output_global["length"] = lengths[0]
    output_global["measured_total_length"] = lengths[0]
    for axis in ("horizontal_basis", "vertical_basis"):
        output_seed["horncad_config"][axis]["solved_s"] = targets[0]
    (output_dir / "project.yaml").write_text(
        yaml.safe_dump(output_seed, sort_keys=False), encoding="utf-8")

    initial_pool = []
    for target, length in zip(targets[1:], lengths[1:]):
        initial_pool.append({
            "label": f"uniform S={target:g}, L={length:g} mm",
            "values": _candidate_values(length, coverage, k, n),
        })
    length_min, length_max = min(lengths), max(lengths)
    search = {
        "version": 1,
        "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage,
        "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "search_size": "quick",
        "max_evaluations": len(targets),
        "initial_candidates": len(targets) - 1,
        "random_seed": int(source.get("random_seed", 17)),
        "minimum_candidate_distance": float(
            source.get("minimum_candidate_distance", 0.08)),
        "derived_s_bounds": [min(targets) - 0.01, max(targets) + 0.01],
        "inferior_screen_probability": float(
            source.get("inferior_screen_probability", 0.97)),
        "sampling_stability_points": float(
            source.get("sampling_stability_points", 2.0)),
        "confirmation_points_per_octave": float(
            source.get("confirmation_points_per_octave", 16)),
        "bounds": {
            "length_mm": [length_min - 0.001, length_max + 0.001],
            "extension_mm": [0.0, 1e-6],
            "osse_coverage_h_deg": [coverage, coverage + 1e-6],
            "osse_coverage_v_deg": [coverage, coverage + 1e-6],
            "k_h": [k, k + 1e-6],
            "k_v": [k, k + 1e-6],
            "n_h": [n, n + 1e-6],
            "n_v": [n, n + 1e-6],
        },
        "initial_pool": initial_pool,
        "solver": copy.deepcopy(source.get("solver", {
            "points_per_octave": 12,
            "elements_per_wavelength": 6,
            "angles": 91,
            "workers": 0,
        })),
    }
    (output_dir / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False),
        encoding="utf-8")
    return output_dir


def generate_all(project_root: Path,
                 targets: tuple[float, ...] = DEFAULT_S_TARGETS) -> list[Path]:
    searches = sorted(
        path for path in project_root.glob("*deg/*x*/search.yaml")
        if not path.parent.name.endswith("-s-grid"))
    return [materialize_s_grid(path, targets) for path in searches]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--targets", type=float, nargs="+",
                        default=DEFAULT_S_TARGETS)
    args = parser.parse_args()
    outputs = generate_all(args.project_root, tuple(args.targets))
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
