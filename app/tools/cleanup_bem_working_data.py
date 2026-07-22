#!/usr/bin/env python3
"""Condense BEM candidates and remove disposable NumCalc working data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np


RAW_PREFIX = "project-NumCalc-"
REDUNDANT_DIAGNOSTICS = (
    "coverage_diagnostics.json", "surface_diagnostics.json",
)


def _valid_npz(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with np.load(path, allow_pickle=False) as archive:
            if not archive.files:
                return False
            for key in archive.files:
                np.asarray(archive[key])
    except (OSError, ValueError, EOFError):
        return False
    return True


def _copy_archive(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(source, temporary)
    if not _valid_npz(temporary):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"raw response archive is invalid: {source}")
    temporary.replace(target)


def cleanup(root: Path, apply: bool = False) -> dict[str, Any]:
    raw_dirs = sorted(
        (path for path in root.glob(f"**/{RAW_PREFIX}*") if path.is_dir()),
        key=lambda path: len(path.parts), reverse=True)
    copied = removed = incomplete = 0
    for raw in raw_dirs:
        stable = raw.parent / "responses.npz"
        source = raw / "responses.npz"
        if not _valid_npz(stable) and _valid_npz(source):
            if apply:
                _copy_archive(source, stable)
            copied += 1
        elif not _valid_npz(stable):
            # An interrupted/failed work tree has no reusable response surface.
            incomplete += 1
        if apply:
            shutil.rmtree(raw)
        removed += 1
    redundant = []
    for name in REDUNDANT_DIAGNOSTICS:
        redundant.extend(root.glob(f"**/candidates/candidate-*/bem/{name}"))
    if apply:
        for path in redundant:
            path.unlink(missing_ok=True)
    return {
        "mode": "apply" if apply else "dry-run",
        "raw_directories": removed,
        "archives_recovered": copied,
        "incomplete_raw_directories": incomplete,
        "redundant_diagnostic_json": len(redundant),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("examples"))
    parser.add_argument("--apply", action="store_true",
                        help="Perform deletion; default is an inventory only")
    args = parser.parse_args()
    print(json.dumps(cleanup(args.root, args.apply), indent=2))


if __name__ == "__main__":
    main()
