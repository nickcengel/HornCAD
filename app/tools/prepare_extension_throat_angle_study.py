#!/usr/bin/env python3
"""Build the frozen design manifest for the extension/throat-angle study.

This module contains no solver or geometry-materialization calls. Its write
command is deliberately gated on completed ridge closure so importing or
testing the design cannot interfere with that running study.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RIDGE_RUNTIME = ROOT / "examples/round-control-ridge-closure/runtime_state.json"
RIDGE_RESULTS = ROOT / "examples/round-control-ridge-closure/results.json"
ROUND_HEURISTICS = ROOT / "models/round_control_heuristics_v1/heuristics.json"
DEFAULT_OUTPUT = (
    ROOT / "examples/extension-throat-angle-heuristics/study_design.json"
)

COVERAGES = (30, 35, 40, 45, 50)
MOUTHS = (250, 300, 350, 400, 450)
PRIMARY_ANGLES_EXTENSIONS = (
    (6, 20), (6, 40), (6, 60),
    (0, 0), (12, 0),
    (0, 40), (12, 40),
)
SECONDARY_CELLS = ((30, 250), (40, 350), (50, 450))
SECONDARY_ANGLES_EXTENSIONS = (
    (0, 0), (12, 0),
    (0, 40), (6, 40), (12, 40),
)
LOCKED_CELLS = (
    (30, 250), (30, 450), (40, 350), (50, 250), (50, 450),
)
CONDITIONAL_CELLS = ((30, 350), (40, 250), (40, 450), (50, 350))
ENDPOINT_ANGLES_EXTENSIONS = ((0, 20), (0, 60), (12, 20), (12, 60))

EXPECTED_COUNTS = {
    "primary-development": 175,
    "secondary-transfer": 15,
    "locked-validation": 20,
    "conditional-validation": 16,
}
INITIAL_CANDIDATES = 210
MAX_CANDIDATES = 226

RADIATION_ERROR_LIMITS = {
    "surface_score": 1.0,
    "mean_containment": 1.0,
    "profile_rms_error": 0.25,
    "slice_energy_rms_departure": 0.25,
    "outward_rise_violation": 0.5,
    "minus_six_db_rms_error": 1.0,
}


def _candidate(
    stage: str,
    coverage: int,
    mouth: int,
    throat_angle: int,
    extension: int,
    parent_role: str,
) -> dict[str, Any]:
    parent_suffix = "primary" if parent_role == "primary" else "secondary"
    candidate_id = (
        f"ext-angle-{stage}-{coverage}deg-{mouth}mm-"
        f"{parent_suffix}-A{throat_angle}-E{extension}"
    )
    return {
        "id": candidate_id,
        "stage": stage,
        "coverage_deg": coverage,
        "round_mouth_diameter_mm": mouth,
        "parent_role": parent_role,
        "throat_angle_deg": throat_angle,
        "extension_mm": extension,
        "outcome_access": (
            "development"
            if stage in ("primary-development", "secondary-transfer")
            else "locked-until-heuristic-freeze"
        ),
    }


def candidate_design() -> list[dict[str, Any]]:
    """Return the deterministic 226-case maximum design."""
    rows: list[dict[str, Any]] = []
    for coverage in COVERAGES:
        for mouth in MOUTHS:
            rows.extend(
                _candidate(
                    "primary-development", coverage, mouth, angle, extension,
                    "primary",
                )
                for angle, extension in PRIMARY_ANGLES_EXTENSIONS
            )
    for coverage, mouth in SECONDARY_CELLS:
        rows.extend(
            _candidate(
                "secondary-transfer", coverage, mouth, angle, extension,
                "secondary",
            )
            for angle, extension in SECONDARY_ANGLES_EXTENSIONS
        )
    for stage, cells in (
        ("locked-validation", LOCKED_CELLS),
        ("conditional-validation", CONDITIONAL_CELLS),
    ):
        for coverage, mouth in cells:
            rows.extend(
                _candidate(
                    stage, coverage, mouth, angle, extension, "primary",
                )
                for angle, extension in ENDPOINT_ANGLES_EXTENSIONS
            )
    return rows


def validate_design(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        stage: sum(row["stage"] == stage for row in rows)
        for stage in EXPECTED_COUNTS
    }
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"candidate allocation changed: {counts}")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate identifiers")
    if len(rows) != MAX_CANDIDATES:
        raise ValueError(f"expected {MAX_CANDIDATES} candidates, got {len(rows)}")
    if any(
        row["throat_angle_deg"] == 6 and row["extension_mm"] == 0
        for row in rows
    ):
        raise ValueError("the retained 6-degree/zero-extension response was added")
    return counts


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def assert_ridge_complete() -> tuple[dict[str, Any], str]:
    """Refuse manifest writes until ridge closure is complete and analyzed."""
    if not RIDGE_RUNTIME.exists():
        raise RuntimeError(f"ridge runtime state is absent: {RIDGE_RUNTIME}")
    runtime = _read_object(RIDGE_RUNTIME)
    if runtime.get("status") != "complete":
        raise RuntimeError(
            "ridge closure is not complete; no extension study files were written"
        )
    if not RIDGE_RESULTS.exists():
        raise RuntimeError(
            "ridge results are not published; no extension study files were written"
        )
    results_bytes = RIDGE_RESULTS.read_bytes()
    ridge_results_sha256 = hashlib.sha256(results_bytes).hexdigest()
    if not ROUND_HEURISTICS.exists():
        raise RuntimeError(
            "round heuristics are absent; no extension study files were written"
        )
    heuristics = _read_object(ROUND_HEURISTICS)
    recorded_hash = heuristics.get("provenance", {}).get(
        "ridge_results_sha256"
    )
    if recorded_hash != ridge_results_sha256:
        raise RuntimeError(
            "round heuristics have not been rebuilt from the final ridge "
            "results; no extension study files were written"
        )
    return runtime, ridge_results_sha256


def build_manifest() -> dict[str, Any]:
    runtime, ridge_results_sha256 = assert_ridge_complete()
    rows = candidate_design()
    counts = validate_design(rows)
    coordinate_payload = [
        {
            key: row[key]
            for key in (
                "id", "stage", "coverage_deg", "round_mouth_diameter_mm",
                "parent_role", "throat_angle_deg", "extension_mm",
            )
        }
        for row in rows
    ]
    coordinate_sha256 = hashlib.sha256(
        json.dumps(
            coordinate_payload, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "status": "design-only-no-bem-scheduled",
        "purpose": "deterministic extension/throat-angle paired heuristic",
        "ridge_manifest_freeze_sha256": runtime.get("manifest_freeze_sha256"),
        "ridge_results_sha256": ridge_results_sha256,
        "counts": {
            **counts,
            "initial": INITIAL_CANDIDATES,
            "maximum": MAX_CANDIDATES,
        },
        "coordinate_sha256": coordinate_sha256,
        "retained_baseline": {
            "throat_angle_deg": 6,
            "extension_mm": 0,
            "rerun": False,
        },
        "conditional_rule": (
            "run all 16 conditional-validation cases if any locked radiation "
            "error exceeds its registered limit"
        ),
        "radiation_absolute_error_limits": RADIATION_ERROR_LIMITS,
        "throat_impedance": {
            "record": True,
            "included_in_surface_score": False,
            "included_in_ranking": False,
            "included_in_expansion_gate": False,
        },
        "parent_selection": {
            "status": "must-be-frozen-after-ridge-heuristic-rebuild",
            "primary": "final best measured zero-extension parent in every cell",
            "secondary_cells": [
                {"coverage_deg": coverage, "mouth_diameter_mm": mouth}
                for coverage, mouth in SECONDARY_CELLS
            ],
        },
        "candidates": rows,
        "materialized_projects": 0,
        "scheduled_bem_evaluations": 0,
    }


def write_manifest(output: Path = DEFAULT_OUTPUT) -> None:
    """Write only the abstract design; never create geometry or solver inputs."""
    manifest = build_manifest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("check", "write"),
        help="'check' validates in memory; 'write' writes the gated design JSON",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.command == "check":
        validate_design(candidate_design())
        return 0
    write_manifest(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
