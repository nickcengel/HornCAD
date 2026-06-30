"""Run refinement scorecards for one or more HornCAD projects."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import time
from typing import Sequence

import yaml

from horncad.config import ConfigError, load_project, morph_rate, profile_k, profile_n, profile_q
from horncad.refine import (
    _bound_notes,
    objective_score,
    objective_terms,
    refine_project,
    roundover_target_rows,
)


def run_benchmark(projects: Sequence[Path], output: Path | None = None, workers: int | str | None = None) -> list[dict[str, str]]:
    rows = []
    for project in projects:
        started = time.perf_counter()
        config = load_project(project)
        result = refine_project(config, workers=workers)
        elapsed = time.perf_counter() - started
        best = result.best
        roundover_excess = max((row.excess_miss_percent for row in roundover_target_rows(best.config)), default=0.0)
        terms = objective_terms(best.config, best.surface, result.authored_config)
        row = {
            "project": str(project),
            "objective_score": f"{objective_score(best.config, best.surface, result.authored_config):.9g}",
            "area_rms_log": f"{best.surface.area_fit.rms_log_error:.9g}",
            "area_rms_percent": f"{best.surface.area_fit.rms_percent_error * 100.0:.9g}",
            "area_max_percent": f"{best.surface.area_fit.max_abs_percent_error * 100.0:.9g}",
            "roundover_excess_percent": f"{roundover_excess:.9g}",
            "morph_rate": f"{morph_rate(best.config):.9g}",
            "n": f"{profile_n(best.config):.9g}",
            "q": f"{profile_q(best.config):.9g}",
            "k_horizontal": f"{profile_k(best.config, 'horizontal'):.9g}",
            "k_vertical": f"{profile_k(best.config, 'vertical'):.9g}",
            "candidates": str(result.candidates_evaluated),
            "rejected": str(result.candidates_rejected),
            "runtime_sec": f"{elapsed:.3f}",
            "bound_notes": "; ".join(_bound_notes(best.config)),
        }
        for term in terms:
            key = term.name.replace(" ", "_")
            row[f"objective_{key}"] = f"{term.contribution:.9g}"
        rows.append(row)
    _write_rows(rows, output)
    return rows


def _write_rows(rows: list[dict[str, str]], output: Path | None) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    if output is None:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HornCAD refinement benchmark scorecards.")
    parser.add_argument("projects", nargs="+", type=Path, help="Project YAML files to benchmark.")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Optional CSV output path. Defaults to stdout.")
    parser.add_argument("--workers", default=None, help="Candidate evaluation workers. Use 1 for serial or auto for CPU count.")
    args = parser.parse_args(argv)

    try:
        run_benchmark(args.projects, output=args.output, workers=args.workers)
    except (OSError, yaml.YAMLError, ConfigError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
