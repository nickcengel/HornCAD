#!/usr/bin/env python3
"""Recompute versioned throat-impedance scores and refresh retained BEM reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .interactive_results import load_run, single_report
from .run_bem_search import save_state
from .throat_impedance_diagnostics import (
    DIAGNOSTIC_VERSION,
    throat_impedance_diagnostics,
)


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_reports(
    roots: list[Path],
    *,
    force: bool = False,
) -> dict[str, Any]:
    responses = sorted({
        response.resolve()
        for root in roots
        for response in root.glob(
            "**/candidates/candidate-*/bem/responses.npz")
    })
    by_search: dict[Path, list[Path]] = {}
    for response in responses:
        by_search.setdefault(response.parents[3], []).append(response)

    refreshed = []
    up_to_date = []
    skipped = []
    for search_dir, search_responses in sorted(
            by_search.items(), key=lambda item: str(item[0])):
        state_path = search_dir / "search_state.json"
        if not state_path.is_file():
            skipped.append({
                "search": str(search_dir.relative_to(ROOT)),
                "reason": "search state absent",
            })
            continue
        state = _read_json(state_path)
        if any(record.get("status") == "running"
               for record in state.get("candidates", [])):
            skipped.append({
                "search": str(search_dir.relative_to(ROOT)),
                "reason": "search currently running",
            })
            continue
        records = {
            str(record.get("id")): record
            for record in state.get("candidates", [])
        }
        search_changed = False
        for response in search_responses:
            candidate_id = response.parents[1].name
            record = records.get(candidate_id)
            if not record or record.get("status") != "complete":
                skipped.append({
                    "response": str(response.relative_to(ROOT)),
                    "reason": "matching complete candidate absent",
                })
                continue
            existing = record.get("throat_impedance_diagnostics", {})
            report_value = record.get("report_file")
            report_path = (
                search_dir / str(report_value)
                if report_value else response.parent /
                f"{record['artifact_stem']}_Report.html"
            )
            if (not force
                    and existing.get("diagnostic_version")
                    == DIAGNOSTIC_VERSION
                    and report_path.is_file()
                    and f"diagnostic v{DIAGNOSTIC_VERSION}" in
                    report_path.read_text(encoding="utf-8")):
                up_to_date.append(str(response.relative_to(ROOT)))
                continue
            run = load_run(response.parent, record.get("artifact_stem"))
            crossover = float(
                state.get("crossover_hz", run["crossover_hz"]))
            upper = float(state.get(
                "upper_frequency_hz", run["frequencies"][-1]))
            diagnostic = throat_impedance_diagnostics(
                run["frequencies"],
                run["normalized_impedance"],
                crossover,
                upper,
            )
            count = int(math.ceil(
                math.log2(upper / crossover) * 48)) + 1
            fixed_grid = np.geomspace(crossover, upper, count)
            single_report(
                response.parent,
                report_path,
                title=f"BEM {record['artifact_stem']}",
                evaluation_frequencies=fixed_grid,
                fixed_band=True,
                name=record["artifact_stem"],
            )
            record["throat_impedance_diagnostics"] = diagnostic
            record["report_file"] = str(
                report_path.relative_to(search_dir))
            search_changed = True
            refreshed.append({
                "response": str(response.relative_to(ROOT)),
                "report": str(report_path.relative_to(ROOT)),
                "score": float(diagnostic["overall_percent"]),
                "report_sha256": _digest(report_path),
            })
        if search_changed:
            save_state(search_dir, state)
    return {
        "schema_version": 1,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "roots": [str(path.resolve().relative_to(ROOT)) for path in roots],
        "responses_found": len(responses),
        "reports_refreshed": len(refreshed),
        "reports_up_to_date": len(up_to_date),
        "skipped_count": len(skipped),
        "refreshed": refreshed,
        "up_to_date": up_to_date,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="*", type=Path, default=[Path("examples")])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    roots = [path.resolve() for path in args.root]
    result = refresh_reports(roots, force=args.force)
    if args.ledger:
        _write_json(args.ledger.resolve(), result)
    print(json.dumps({
        key: value for key, value in result.items()
        if key not in {"refreshed", "up_to_date", "skipped"}
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
