#!/usr/bin/env python3
"""Run the central-angle alternating K/N and length closure program."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from typing import Any

import yaml

from .generate_coverage_s_grid import _candidate_values, length_for_s
from .generate_mouth_size_coverage_grid_report import generate_report
from .run_bem_search import run_search


CENTRAL_45_MOUTHS = (350, 400, 450)
CANONICAL_S = tuple(0.5 + 0.25 * index for index in range(13))
MINIMUM_NONCONTROL_SCORE_GAIN = 0.75


def _score(record: dict[str, Any]) -> float:
    return float((record.get("surface_diagnostics", {}).get("score") or {})
                 .get("overall_percent", float("-inf")))


def best_record(state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    complete = [item for item in state.get("candidates", [])
                if item.get("status") == "complete"]
    if not complete:
        raise ValueError(f"no completed candidates in {state_path}")
    return max(complete, key=_score)


def best_project(search_dir: Path) -> Path:
    record = best_record(search_dir / "search_state.json")
    return search_dir / "candidates" / record["id"] / "project.yaml"


def anchor_selection(root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    """Select matched controls plus only materially better scale contrasts."""
    selected: list[Path] = []
    evidence: list[dict[str, Any]] = []
    for angle in (40, 45, 50):
        baselines = sorted((root / f"{angle}deg").glob("*x*-s-grid"))
        if angle == 45:
            baselines = [path for path in baselines
                         if int(path.name.split("x", 1)[0]) in CENTRAL_45_MOUTHS]
        scored = [(_score(best_record(path / "search_state.json")), path)
                  for path in baselines]
        matched = root / f"{angle}deg" / "400x400-s-grid"
        control_score = _score(best_record(matched / "search_state.json"))
        best_score, best = max(scored, key=lambda item: item[0])
        selected.append(matched)
        evidence.append({
            "coverage_deg": angle, "baseline": str(matched.relative_to(root)),
            "role": "matched 400 mm control", "score": control_score,
            "selected": True,
        })
        if best != matched:
            gain = best_score - control_score
            keep = gain >= MINIMUM_NONCONTROL_SCORE_GAIN
            evidence.append({
                "coverage_deg": angle, "baseline": str(best.relative_to(root)),
                "role": "best distinct mouth", "score": best_score,
                "score_gain_over_control": gain, "selected": keep,
                "reason": ("material score and scale contrast" if keep else
                           "score gain too small to justify a redundant coupled anchor"),
            })
            if keep:
                selected.append(best)
    return list(dict.fromkeys(selected)), evidence


def selected_baselines(root: Path) -> list[Path]:
    return anchor_selection(root)[0]


def prerequisites_complete(root: Path) -> bool:
    paths = [root / "30deg" / f"{mouth}x{mouth}-s-grid" /
             "search_state.json"
             for mouth in (250, 300, 350, 400, 450, 500)]
    paths.extend(root / f"{angle}deg" / f"{mouth}x{mouth}-s-grid" /
             "search_state.json"
             for angle in (40, 50) for mouth in (250, 300, 350, 400, 450, 500))
    paths.append(root / "45deg" / "450x450-kn-grid" / "search_state.json")
    boundary_certificate = root / "s_boundary_closure.json"
    return all(path.exists() and
               json.loads(path.read_text(encoding="utf-8")).get("status") == "complete"
               for path in paths) and boundary_certificate.exists() and json.loads(
                   boundary_certificate.read_text(encoding="utf-8")).get("status") == "complete"


def _source_search(baseline: Path) -> dict[str, Any]:
    return yaml.safe_load((baseline / "search.yaml").read_text(encoding="utf-8"))[
        "bem_candidate_search"]


def canonical_extension_targets(baseline: Path) -> tuple[float, ...]:
    """Return missing canonical points near the peak plus matched references."""
    state = json.loads((baseline / "search_state.json").read_text(encoding="utf-8"))
    complete = [item for item in state.get("candidates", [])
                if item.get("status") == "complete"]
    incumbent = max(complete, key=_score)
    best_s = float(incumbent["derived"]["s_h"])
    measured = [float(item["derived"]["s_h"]) for item in complete]
    missing = [s for s in CANONICAL_S
               if not any(abs(s - value) <= 0.02 for value in measured)]
    selected = {s for s in missing if abs(s - best_s) <= 0.55}
    selected.update(s for s in (0.5,) if s in missing)
    return tuple(sorted(selected))


def materialize_canonical_s_extension(baseline: Path, output: Path) -> Path:
    if (output / "search.yaml").exists():
        return output
    targets = canonical_extension_targets(baseline)
    if not targets:
        raise ValueError(f"no missing canonical S targets for {baseline}")
    source = _source_search(baseline)
    seed = yaml.safe_load(best_project(baseline).read_text(encoding="utf-8"))
    config = seed["horncad_config"]
    g, h, v = config["global"], config["horizontal_basis"], config["vertical_basis"]
    lengths = [length_for_s(config, target) for target in targets]
    g["length"] = lengths[0]
    g["measured_total_length"] = lengths[0] + float(g.get("conical_extension_length", 0))
    h["solved_s"] = v["solved_s"] = targets[0]
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    coverage, k, n = float(h["coverage_deg"]), float(h["k"]), float(h["n"])
    pool = [{"label": f"canonical S={s:g}, L={length:g} mm",
             "values": _candidate_values(length, coverage, k, n)}
            for s, length in zip(targets[1:], lengths[1:])]
    solver = copy.deepcopy(source["solver"])
    solver["workers"] = 10
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage, "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": len(targets), "initial_candidates": len(pool),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [min(targets) - 0.01, max(targets) + 0.01],
        "sampling_stability_points": float(source.get("sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source.get("confirmation_points_per_octave", 16)),
        "bounds": {
            "length_mm": [min(lengths) - 0.001, max(lengths) + 0.001],
            "extension_mm": [0.0, 1e-6],
            "osse_coverage_h_deg": [coverage, coverage + 1e-6],
            "osse_coverage_v_deg": [coverage, coverage + 1e-6],
            "k_h": [k, k + 1e-6], "k_v": [k, k + 1e-6],
            "n_h": [n, n + 1e-6], "n_v": [n, n + 1e-6],
        }, "initial_pool": pool, "solver": solver,
    }
    (output / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False), encoding="utf-8")
    return output


def materialize_kn_closure(seed_project: Path, baseline: Path,
                           output: Path) -> Path:
    if (output / "search_state.json").exists():
        return output
    seed = yaml.safe_load(seed_project.read_text(encoding="utf-8"))
    source = _source_search(baseline)
    config = seed["horncad_config"]
    g, h, v = config["global"], config["horizontal_basis"], config["vertical_basis"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    length = float(g["length"])
    extension = float(g.get("conical_extension_length", 0))
    solver = copy.deepcopy(source["solver"])
    solver["workers"] = 10
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": float(h["coverage_deg"]),
        "intended_coverage_v_deg": float(v["coverage_deg"]),
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": 80, "initial_candidates": 0,
        "minimum_candidate_distance": 0.001, "derived_s_bounds": [0.0, 8.0],
        "sampling_stability_points": float(source.get("sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source.get("confirmation_points_per_octave", 16)),
        "adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.5, "minimum_k_step": 0.25,
            "minimum_k": 1.0, "maximum_k": 7.0,
            "initial_n_step": 5.0, "minimum_n_step": 1.0,
            "minimum_n": 2.0, "maximum_n": 40.0,
            "high_s_low_n_rescue": True,
            "rescue_minimum_s": 2.0, "rescue_minimum_n": 8.0,
            "rescue_n_step": 2.0, "rescue_score_margin_points": 3.0,
        },
        "bounds": {
            "length_mm": [length - 0.001, length + 0.001],
            "extension_mm": [extension, extension + 1e-6],
            "osse_coverage_h_deg": [float(h["coverage_deg"]), float(h["coverage_deg"]) + 1e-6],
            "osse_coverage_v_deg": [float(v["coverage_deg"]), float(v["coverage_deg"]) + 1e-6],
            "k_h": [1.0, 7.000001], "k_v": [1.0, 7.000001],
            "n_h": [2.0, 40.000001], "n_v": [2.0, 40.000001],
        },
        "initial_pool": [], "solver": solver,
    }
    (output / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False),
        encoding="utf-8")
    return output


def materialize_local_s(seed_project: Path, baseline: Path,
                        output: Path) -> tuple[Path, float]:
    if (output / "search_state.json").exists():
        seed = yaml.safe_load((output / "project.yaml").read_text(encoding="utf-8"))
        return output, float(seed["horncad_config"]["horizontal_basis"]["solved_s"])
    seed = yaml.safe_load(seed_project.read_text(encoding="utf-8"))
    source = _source_search(baseline)
    config = seed["horncad_config"]
    g, h, v = config["global"], config["horizontal_basis"], config["vertical_basis"]
    center = float(h["solved_s"])
    targets = tuple(sorted({round(max(0.05, center + delta), 4)
                            for delta in (-0.30, -0.15, 0.0, 0.15, 0.30)}))
    lengths = [length_for_s(config, target) for target in targets]
    g["length"] = lengths[0]
    g["measured_total_length"] = lengths[0] + float(g.get("conical_extension_length", 0))
    h["solved_s"] = v["solved_s"] = targets[0]
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    coverage, k, n = float(h["coverage_deg"]), float(h["k"]), float(h["n"])
    pool = [{"label": f"local S={s:g}, L={length:g} mm",
             "values": _candidate_values(length, coverage, k, n)}
            for s, length in zip(targets[1:], lengths[1:])]
    solver = copy.deepcopy(source["solver"])
    solver["workers"] = 10
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage, "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": len(targets), "initial_candidates": len(pool),
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [min(targets) - 0.01, max(targets) + 0.01],
        "sampling_stability_points": float(source.get("sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source.get("confirmation_points_per_octave", 16)),
        "bounds": {
            "length_mm": [min(lengths) - 0.001, max(lengths) + 0.001],
            "extension_mm": [0.0, 1e-6],
            "osse_coverage_h_deg": [coverage, coverage + 1e-6],
            "osse_coverage_v_deg": [coverage, coverage + 1e-6],
            "k_h": [k, k + 1e-6], "k_v": [k, k + 1e-6],
            "n_h": [n, n + 1e-6], "n_v": [n, n + 1e-6],
        }, "initial_pool": pool, "solver": solver,
    }
    (output / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False), encoding="utf-8")
    return output, center


def run_anchor(root: Path, baseline: Path, max_rounds: int = 3) -> str:
    angle_dir, mouth = baseline.parent, baseline.name.split("-", 1)[0]
    existing_kn = angle_dir / f"{mouth}-kn-grid"
    candidates = [baseline]
    canonical = angle_dir / f"{mouth}-canonical-s"
    if (canonical / "search_state.json").exists():
        candidates.append(canonical)
    if ((existing_kn / "search_state.json").exists() and
            json.loads((existing_kn / "search_state.json").read_text()).get("status") == "complete"):
        candidates.append(existing_kn)
    seed_dir = max(candidates, key=lambda path: _score(
        best_record(path / "search_state.json")))
    seed_project = best_project(seed_dir)
    for round_number in range(1, max_rounds + 1):
        prefix = angle_dir / f"{mouth}-coupled-r{round_number:02d}"
        kn_dir = materialize_kn_closure(
            seed_project, baseline, prefix.with_name(prefix.name + "-kn"))
        run_search(kn_dir / "search.yaml", kn_dir, None)
        kn_best = best_project(kn_dir)
        s_dir, center_s = materialize_local_s(
            kn_best, baseline, prefix.with_name(prefix.name + "-s"))
        run_search(s_dir / "search.yaml", s_dir, None)
        s_best_record = best_record(s_dir / "search_state.json")
        generate_report(root, root / "index.html")
        if abs(float(s_best_record["derived"]["s_h"]) - center_s) <= 0.075:
            return f"{angle_dir.name}/{mouth}: converged in {round_number} round(s)"
        seed_project = best_project(s_dir)
    return f"{angle_dir.name}/{mouth}: unresolved after {max_rounds} rounds"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    while not prerequisites_complete(args.project_root):
        if not args.wait:
            raise RuntimeError("40/50 baselines and active 45-degree K/N prerequisite are incomplete")
        time.sleep(args.poll_seconds)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        extension_baselines = [args.project_root / "45deg" /
                               f"{mouth}x{mouth}-s-grid"
                               for mouth in (300, 350, 400, 450, 500)]
        extension_dirs = [materialize_canonical_s_extension(
            baseline, baseline.with_name(
                baseline.name.removesuffix("-s-grid") + "-canonical-s"))
            for baseline in extension_baselines]
        extension_futures = [executor.submit(
            run_search, path / "search.yaml", path, None)
            for path in extension_dirs]
        for future in as_completed(extension_futures):
            future.result()
            generate_report(args.project_root, args.project_root / "index.html")

    baselines = selected_baselines(args.project_root)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_anchor, args.project_root, path)
                   for path in baselines]
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
