#!/usr/bin/env python3
"""Migrate retained BEM-search artifacts to canonical public names."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

try:
    from .interactive_results import load_run, single_report
    from .run_bem_search import candidate_artifact_stem, write_report, _read_yaml
    from .surface_diagnostics import surface_diagnostics
except ImportError:
    from interactive_results import load_run, single_report
    from run_bem_search import candidate_artifact_stem, write_report, _read_yaml
    from surface_diagnostics import surface_diagnostics


def migrate_search(search_dir: Path) -> tuple[int, int]:
    state_path = search_dir / "search_state.json"
    if not state_path.is_file():
        return 0, 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    search = state["search"]
    fixed_grid = np.geomspace(
        float(search["crossover_hz"]), float(search["upper_frequency_hz"]),
        int(math.ceil(math.log2(float(search["upper_frequency_hz"]) /
                               float(search["crossover_hz"])) * 48)) + 1)
    renamed_stls = 0
    renamed_reports = 0
    for record in state.get("candidates", []):
        candidate_dir = search_dir / "candidates" / record["id"]
        project_path = candidate_dir / "project.yaml"
        if not project_path.is_file():
            continue
        stem = candidate_artifact_stem(_read_yaml(project_path))
        record["artifact_stem"] = stem

        stl_target = candidate_dir / f"{stem}_Surface.STL"
        stl_sources = [path for path in candidate_dir.glob("*.STL")
                       if path != stl_target]
        if not stl_target.is_file() and stl_sources:
            stl_sources[0].replace(stl_target)
            renamed_stls += 1
        for obsolete_stl in candidate_dir.glob("*.STL"):
            if obsolete_stl != stl_target:
                obsolete_stl.unlink()
        if stl_target.is_file():
            record["stl_file"] = stl_target.name

        run_dir_value = record.get("run_dir")
        if not run_dir_value:
            continue
        run_dir = search_dir / run_dir_value
        report_target = candidate_dir / "bem" / f"{stem}_Report.html"
        legacy_report = run_dir / "interactive_report.html"
        report_head = (report_target.read_text(
            encoding="utf-8", errors="ignore")[:4096]
            if report_target.is_file() else "")
        report_is_current = (
            f"<title>BEM {stem}</title>" in report_head and
            "report-schema: canonical-v6" in report_head
        )
        run = None
        if (run_dir / "responses.npz").is_file():
            run = load_run(run_dir, stem)
            record["surface_diagnostics"] = surface_diagnostics(
                run, fixed_grid, fixed_band=True)
        if run is not None and not report_is_current:
            single_report(
                run_dir, report_target, title=f"BEM {stem}",
                evaluation_frequencies=fixed_grid, fixed_band=True, name=stem)
            if legacy_report.is_file() and legacy_report != report_target:
                legacy_report.unlink()
            renamed_reports += 1
        elif legacy_report.is_file() and not report_target.is_file():
            report_target.parent.mkdir(parents=True, exist_ok=True)
            legacy_report.replace(report_target)
            renamed_reports += 1
        if report_target.is_file():
            record["report_file"] = str(report_target.relative_to(search_dir))
            for obsolete_report in report_target.parent.glob("*_Report.html"):
                if obsolete_report != report_target:
                    obsolete_report.unlink()

    state.pop("finalist_comparison", None)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    write_report(search_dir, state)
    return renamed_stls, renamed_reports


def migrate(root: Path) -> tuple[int, int, int]:
    stls = reports = 0
    for state_path in sorted(root.glob("**/search_state.json")):
        migrated_stls, migrated_reports = migrate_search(state_path.parent)
        stls += migrated_stls
        reports += migrated_reports
    removed = 0
    for path in sorted(root.glob("**/finalist_comparison.html")):
        path.unlink()
        removed += 1
    for legacy_report in sorted(root.glob("**/search_report_rescored.html")):
        current_report = legacy_report.with_name("search_report.html")
        if current_report.is_file():
            legacy_report.write_text(current_report.read_text(encoding="utf-8"),
                                     encoding="utf-8")
    return stls, reports, removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    stls, reports, removed = migrate(args.root)
    print(f"renamed {stls} STLs; wrote {reports} reports; "
          f"removed {removed} finalist comparisons")


if __name__ == "__main__":
    main()
