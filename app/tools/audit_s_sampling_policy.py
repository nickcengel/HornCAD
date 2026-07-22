#!/usr/bin/env python3
"""Replay sensitivity-driven S sampling against completed dense baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .s_sensitivity_sampling import SPoint, replay


S_LABEL = re.compile(r"S=([0-9.]+)")
MINIMUM_DENSE_CURVES = 4


def _score(record: dict[str, Any]) -> float | None:
    value = ((record.get("surface_diagnostics", {}).get("score") or {})
             .get("overall_percent"))
    return float(value) if isinstance(value, (int, float)) else None


def curve(state_path: Path) -> list[SPoint]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    points: dict[float, SPoint] = {}
    for record in state.get("candidates", []):
        score = _score(record)
        s_h = record.get("derived", {}).get("s_h")
        s_v = record.get("derived", {}).get("s_v")
        if (record.get("status") != "complete" or score is None or
                not isinstance(s_h, (int, float)) or
                not isinstance(s_v, (int, float)) or abs(s_h - s_v) > 0.01):
            continue
        value = round((float(s_h) + float(s_v)) / 2, 4)
        current = points.get(value)
        if current is None or score > current.score:
            points[value] = SPoint(value, score)
    return sorted(points.values(), key=lambda point: point.s)


def authored_s(search_path: Path) -> list[float]:
    search = yaml.safe_load(search_path.read_text(encoding="utf-8"))[
        "bem_candidate_search"]
    values = []
    for item in search.get("initial_pool", []):
        match = S_LABEL.search(str(item.get("label", "")))
        if match:
            values.append(float(match.group(1)))
    return sorted(set(values))


def audit(root: Path) -> dict[str, Any]:
    results = []
    excluded = []
    for state_path in sorted(root.glob("[45]0deg/*-s-grid/search_state.json")):
        points = curve(state_path)
        authored = authored_s(state_path.with_name("search.yaml"))
        missing = [value for value in authored
                   if not any(abs(point.s - value) <= 0.02 for point in points)]
        if len(points) < 7 or missing:
            excluded.append({"search": str(state_path.parent.relative_to(root)),
                             "reason": "not a dense authored curve",
                             "missing_authored_s": missing})
            continue
        result = replay(points)
        result["search"] = str(state_path.parent.relative_to(root))
        results.append(result)
    within_one = sum(float(item["score_regret"]) <= 1.0 for item in results)
    s_equivalent = sum(float(item["s_error"]) <= 0.3 or
                       float(item["score_regret"]) <= 0.05 for item in results)
    mean_saved = (sum(float(item["saved_fraction"]) for item in results) /
                  len(results) if results else 0.0)
    pass_fraction = within_one / len(results) if results else 0.0
    sufficient = len(results) >= MINIMUM_DENSE_CURVES
    passed = sufficient and all((
        pass_fraction >= 0.95,
        max(float(item["score_regret"]) for item in results) <= 2.0,
        s_equivalent == len(results),
        mean_saved >= 0.25,
    ))
    return {
        "status": "pass" if passed else "fail" if sufficient else "insufficient",
        "minimum_dense_curves": MINIMUM_DENSE_CURVES,
        "criteria": {"within_one_fraction": pass_fraction,
                     "maximum_regret": max((float(item["score_regret"])
                                             for item in results), default=0.0),
                     "s_equivalent_fraction": s_equivalent / len(results)
                     if results else 0.0,
                     "mean_saved_fraction": mean_saved},
        "results": results, "excluded": excluded,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.project_root)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
