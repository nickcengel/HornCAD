#!/usr/bin/env python3
"""Refresh the control-decoupling index from frozen and runtime state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .plan_control_decoupling_study import render_index


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_progress(root: Path, manifest: dict[str, Any],
                   plan: dict[str, Any]) -> dict[str, Any]:
    runtime = _read_json(root / "runtime_state.json")
    skipped = {item["search"] for item in runtime.get("skipped_searches", [])}
    coordinate_status: dict[str, str] = {}
    waves = []
    for wave in plan.get("wave_counts", {}):
        searches = [item for item in plan["searches"] if item["wave"] == wave]
        status_counts = {"complete": 0, "running": 0, "not-started": 0,
                         "failed": 0, "pruned": 0}
        for item in searches:
            if item["path"] in skipped:
                status = "pruned"
            else:
                state = _read_json(root / item["path"] / "search_state.json")
                status = str(state.get("status", "not-started"))
                if status not in status_counts:
                    status = "failed" if status in {
                        "error", "blocked", "geometry-rejected"} else "not-started"
            status_counts[status] += 1
            display = status.replace("not-started", "planned")
            for identifier in item["coordinate_ids"]:
                coordinate_status[identifier] = display
        waves.append({
            "wave": wave,
            "searches": plan["wave_counts"][wave]["searches"],
            "candidates": plan["wave_counts"][wave]["candidates"],
            "complete": status_counts["complete"],
            "running": status_counts["running"],
            "not_started": status_counts["not-started"],
            "failed": status_counts["failed"],
            "pruned": status_counts["pruned"],
        })
    return {
        "manifest_sha256": _digest(manifest), "runtime": runtime,
        "coordinate_status": coordinate_status, "waves": waves,
    }


def refresh_index(root: Path) -> None:
    manifest = _read_json(root / "manifest.json")
    plan = _read_json(root / "execution_plan.json")
    progress = build_progress(root, manifest, plan) if plan else None
    (root / "index.html").write_text(
        render_index(manifest, progress), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?",
                        default=Path("examples/control-decoupling"))
    args = parser.parse_args()
    refresh_index(args.root)


if __name__ == "__main__":
    main()
