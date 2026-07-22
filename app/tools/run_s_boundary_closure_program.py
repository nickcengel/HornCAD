#!/usr/bin/env python3
"""Bracket every uniform-S winner before K/N or coupled refinement begins."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import time
from typing import Any

import yaml

from .generate_coverage_s_grid import _candidate_values, length_for_s
from .generate_mouth_size_coverage_grid_report import generate_report
from .run_bem_search import run_search


INITIAL_BOUNDARY_STEP = 0.3
MINIMUM_S = 0.05
MAXIMUM_S = 8.0
MAXIMUM_PROBES = 32
BASELINE_NAME = re.compile(r"^\d+x\d+-s-grid$")
S_LABEL = re.compile(r"S=([0-9.]+)")


def _score(record: dict[str, Any]) -> float:
    return float((record.get("surface_diagnostics", {}).get("score") or {})
                 .get("overall_percent", float("-inf")))


def baseline_searches(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("*deg/*-s-grid")
                  if BASELINE_NAME.fullmatch(path.name))


def baselines_complete(root: Path) -> bool:
    paths = baseline_searches(root)
    return bool(paths) and all(
        (path / "search_state.json").exists() and
        json.loads((path / "search_state.json").read_text()).get("status") == "complete"
        for path in paths)


def completed_points(search_dirs: list[Path]) -> list[tuple[float, float, Path]]:
    points = []
    for search_dir in search_dirs:
        state_path = search_dir / "search_state.json"
        if not state_path.exists():
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for record in state.get("candidates", []):
            if (record.get("status") == "complete" and
                    record.get("derived", {}).get("s_h") is not None):
                points.append((float(record["derived"]["s_h"]),
                               _score(record),
                               search_dir / "candidates" / record["id"] /
                               "project.yaml"))
    return points


def authored_sentinel(baseline: Path) -> float:
    """Return the highest S coordinate authored by a uniform baseline."""
    search = yaml.safe_load((baseline / "search.yaml").read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    project = yaml.safe_load((baseline / "project.yaml").read_text(encoding="utf-8"))
    values = [float(project["horncad_config"]["horizontal_basis"]["solved_s"])]
    for item in search.get("initial_pool", []):
        match = S_LABEL.search(str(item.get("label", "")))
        if match:
            values.append(float(match.group(1)))
    return max(values)


def closure_status(points: list[tuple[float, float, Path]]) -> tuple[str, float]:
    """Return closed/lower/upper and the best measured S coordinate."""
    if not points:
        raise ValueError("S closure requires at least one completed point")
    best = max(points, key=lambda item: item[1])
    values = [item[0] for item in points]
    lower = any(value < best[0] - 1e-3 for value in values)
    upper = any(value > best[0] + 1e-3 for value in values)
    if lower and upper:
        return "closed", best[0]
    return ("lower" if not lower else "upper"), best[0]


def next_probe_s(status: str, best_s: float,
                 directional_probe_count: int = 0) -> float | None:
    step = INITIAL_BOUNDARY_STEP * 2 ** max(0, directional_probe_count)
    if status == "lower":
        if best_s <= MINIMUM_S + 1e-6:
            return None
        return round(max(MINIMUM_S, best_s - step), 4)
    if status == "upper":
        if best_s >= MAXIMUM_S - 1e-6:
            return None
        return round(min(MAXIMUM_S, best_s + step), 4)
    return None


def geometry_rejections(search_dirs: list[Path]) -> list[dict[str, Any]]:
    """Return authored S coordinates rejected before a BEM evaluation."""
    output = []
    for search_dir in search_dirs:
        state_path = search_dir / "search_state.json"
        if not state_path.exists():
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") != "geometry-rejected":
            continue
        rejection = state.get("geometry_rejection", {})
        value = rejection.get("derived", {}).get("s_h")
        if value is None:
            continue
        output.append({
            "s": float(value),
            "reason": rejection.get("reason", "geometry rejected"),
            "search_dir": search_dir,
        })
    return output


def materialize_probe(seed_project: Path, baseline: Path, output: Path,
                      target_s: float) -> Path:
    if (output / "search.yaml").exists():
        # Repair probe directories authored by the pre-single-evaluation
        # implementation before they reach the queue.
        path = output / "search.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        search = document["bem_candidate_search"]
        if search.get("max_evaluations") == 1 and search.get("initial_pool") == []:
            search.pop("initial_pool")
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return output
    seed = yaml.safe_load(seed_project.read_text(encoding="utf-8"))
    source = yaml.safe_load((baseline / "search.yaml").read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    config = seed["horncad_config"]
    g, h, v = config["global"], config["horizontal_basis"], config["vertical_basis"]
    length = length_for_s(config, target_s)
    g["length"] = length
    g["measured_total_length"] = length + float(g.get("conical_extension_length", 0))
    h["solved_s"] = v["solved_s"] = target_s
    output.mkdir(parents=True, exist_ok=True)
    (output / "project.yaml").write_text(
        yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    solver = copy.deepcopy(source["solver"])
    solver["workers"] = 10
    coverage = float(h["coverage_deg"])
    values = _candidate_values(length, coverage, float(h["k"]), float(h["n"]))
    search = {
        "version": 1, "seed_yaml": "project.yaml",
        "intended_coverage_h_deg": coverage,
        "intended_coverage_v_deg": coverage,
        "lower_frequency_hz": float(source["lower_frequency_hz"]),
        "crossover_hz": float(source["crossover_hz"]),
        "upper_frequency_hz": float(source["upper_frequency_hz"]),
        "max_evaluations": 1, "initial_candidates": 0,
        "minimum_candidate_distance": 0.001,
        "derived_s_bounds": [target_s - 0.001, target_s + 0.001],
        "sampling_stability_points": float(source.get("sampling_stability_points", 2)),
        "confirmation_points_per_octave": float(source.get("confirmation_points_per_octave", 16)),
        "bounds": {
            "length_mm": [length - 0.001, length + 0.001],
            "extension_mm": [values["extension_mm"], values["extension_mm"] + 1e-6],
            "osse_coverage_h_deg": [coverage, coverage + 1e-6],
            "osse_coverage_v_deg": [coverage, coverage + 1e-6],
            "k_h": [values["k_h"], values["k_h"] + 1e-6],
            "k_v": [values["k_v"], values["k_v"] + 1e-6],
            "n_h": [values["n_h"], values["n_h"] + 1e-6],
            "n_v": [values["n_v"], values["n_v"] + 1e-6],
        },
        "solver": solver,
    }
    (output / "search.yaml").write_text(
        yaml.safe_dump({"bem_candidate_search": search}, sort_keys=False),
        encoding="utf-8")
    return output


def close_baseline(root: Path, baseline: Path) -> dict[str, Any]:
    rounds = sorted(baseline.parent.glob(
        baseline.name.removesuffix("-s-grid") + "-s-boundary-r*"))
    for probe_number in range(1, MAXIMUM_PROBES + 1):
        points = completed_points([baseline, *rounds])
        rejected = geometry_rejections(rounds)
        sentinel_s = authored_sentinel(baseline)
        sentinel_resolved = (
            any(abs(point[0] - sentinel_s) <= 0.02 for point in points) or
            any(abs(item["s"] - sentinel_s) <= 0.02 for item in rejected)
        )
        status, best_s = closure_status(points)
        blocking_rejection = next((item for item in rejected if (
            status == "lower" and item["s"] < best_s - 1e-3) or (
            status == "upper" and item["s"] > best_s + 1e-3)), None)
        if blocking_rejection is not None:
            return {
                "baseline": str(baseline.relative_to(root)),
                "status": "geometry-limited", "side": status,
                "best_s": best_s, "rejected_s": blocking_rejection["s"],
                "reason": blocking_rejection["reason"], "probes": len(rounds),
            }
        if not sentinel_resolved:
            target = sentinel_s
            status = "sentinel"
        else:
            baseline_best_s = max(completed_points([baseline]),
                                  key=lambda item: item[1])[0]
            directional_probe_count = sum(
                (item[0] < baseline_best_s - 1e-3 if status == "lower"
                 else item[0] > baseline_best_s + 1e-3)
                for item in completed_points(rounds))
            directional_probe_count += sum(
                (item["s"] < baseline_best_s - 1e-3 if status == "lower"
                 else item["s"] > baseline_best_s + 1e-3)
                for item in rejected)
            target = next_probe_s(status, best_s, directional_probe_count)
        if status == "closed":
            return {"baseline": str(baseline.relative_to(root)),
                    "status": "closed", "best_s": best_s,
                    "sentinel_s": sentinel_s, "probes": len(rounds)}
        if target is None:
            return {"baseline": str(baseline.relative_to(root)),
                    "status": "boundary-limited", "best_s": best_s,
                    "side": status, "sentinel_s": sentinel_s,
                    "probes": len(rounds)}
        output = baseline.with_name(
            baseline.name.removesuffix("-s-grid") +
            f"-s-boundary-r{probe_number:02d}")
        seed_project = max(points, key=lambda item: item[1])[2]
        materialize_probe(seed_project, baseline, output, target)
        state_path = output / "search_state.json"
        if not state_path.exists() or json.loads(state_path.read_text()).get("status") != "complete":
            probe_state = run_search(output / "search.yaml", output, None)
            if probe_state.get("status") == "geometry-rejected":
                rejection = probe_state.get("geometry_rejection", {})
                return {
                    "baseline": str(baseline.relative_to(root)),
                    "status": "geometry-limited", "best_s": best_s,
                    "rejected_s": rejection.get("derived", {}).get("s_h"),
                    "reason": rejection.get("reason", "geometry rejected"),
                    "probes": len(rounds) + (output not in rounds),
                }
        if output not in rounds:
            rounds.append(output)
        generate_report(root, root / "index.html")
    return {"baseline": str(baseline.relative_to(root)), "status": "unresolved",
            "probes": len(rounds)}


def run_program(root: Path, workers: int = 2) -> dict[str, Any]:
    baselines = baseline_searches(root)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(close_baseline, root, baseline)
                   for baseline in baselines]
        results = [future.result() for future in as_completed(futures)]
    results.sort(key=lambda item: item["baseline"])
    acceptable = {"closed", "geometry-limited"}
    status = "complete" if all(item["status"] in acceptable
                               for item in results) else "blocked"
    certificate = {"status": status, "results": results}
    path = root / "s_boundary_closure.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    generate_report(root, root / "index.html")
    return certificate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    while not baselines_complete(args.project_root):
        if not args.wait:
            raise RuntimeError("uniform-S baselines are incomplete")
        time.sleep(args.poll_seconds)
    result = run_program(args.project_root, args.workers)
    if result["status"] != "complete":
        raise RuntimeError("one or more S winners remain boundary-limited")


if __name__ == "__main__":
    main()
