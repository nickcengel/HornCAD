#!/usr/bin/env python3
"""Apply the validated 30-degree sensitivity policy to not-started searches."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .audit_s_sampling_policy import audit
from .s_sensitivity_sampling import space_filling_order


S_LABEL = re.compile(r"S=([0-9.]+)")
MANDATORY_S = (0.7, 1.3, 1.9, 2.5, 3.0)


def configure(document: dict[str, Any]) -> dict[str, Any]:
    """Return a configured search document with skeleton-first pool ordering."""
    output = json.loads(json.dumps(document))
    search = output["bem_candidate_search"]
    pool = search["initial_pool"]
    indexed = {}
    for item in pool:
        match = S_LABEL.search(str(item.get("label", "")))
        if match:
            indexed[round(float(match.group(1)), 6)] = item
    missing = [value for value in MANDATORY_S if round(value, 6) not in indexed]
    if missing:
        raise ValueError(f"search lacks mandatory S coordinates: {missing}")
    mandatory_order = space_filling_order(MANDATORY_S)
    ordered = []
    for value in mandatory_order:
        item = indexed.pop(round(value, 6))
        item["required"] = True
        ordered.append(item)
    ordered.extend(indexed[value] for value in sorted(indexed))
    search["initial_pool"] = ordered
    search["initial_candidates"] = len(ordered)
    search["s_sensitivity_sampling"] = {
        "enabled": True,
        "mandatory_s": list(MANDATORY_S),
        "maximum_skeleton_spacing": 0.6,
        "variation_points": 0.75,
        "winner_resolution": 0.3,
    }
    return output


def apply(root: Path) -> list[str]:
    replay = audit(root)
    if replay["status"] != "pass":
        raise RuntimeError(
            f"S sensitivity replay gate is {replay['status']}; no searches changed")
    changed = []
    for search_path in sorted(root.glob("30deg/*-s-grid/search.yaml")):
        state_path = search_path.with_name("search_state.json")
        if state_path.is_file():
            status = json.loads(state_path.read_text(encoding="utf-8")).get("status")
            if status != "not started":
                continue
        document = yaml.safe_load(search_path.read_text(encoding="utf-8"))
        configured = configure(document)
        search_path.write_text(yaml.safe_dump(configured, sort_keys=False),
                               encoding="utf-8")
        changed.append(str(search_path.relative_to(root)))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    for path in apply(args.project_root):
        print(path)


if __name__ == "__main__":
    main()
