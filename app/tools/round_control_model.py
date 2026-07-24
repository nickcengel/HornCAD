"""Deterministic assembly, fitting, validation, and export for round-control v1."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable

import numpy as np
import yaml

from .export_horncad import solved_s, termination_metrics
from .interactive_results import load_run
from .plan_control_decoupling_study import (
    ANGLES, MOUTHS, _solver_fingerprint, reusable_results,
)
from .surface_diagnostics import surface_diagnostics
from .throat_impedance_diagnostics import throat_impedance_diagnostics


SCHEMA_VERSION = 1
MODEL_TERMS = ("1", "L", "K", "N", "L2", "K2", "N2", "LK", "LN", "KN")
CONTROL_SCALING = {
    "length_factor": {"center": 1.0, "scale": 0.2},
    "k": {"center": 4.0, "scale": 2.0},
    "n": {"center": 8.0, "scale": 4.0},
}
DIAGNOSTICS = (
    "surface_score",
    "mean_containment",
    "profile_rms_error",
    "slice_energy_rms_departure",
    "outward_rise_violation",
    "minus_six_db_rms_error",
    "throat_impedance_score",
)
PREREGISTERED_DIAGNOSTICS = DIAGNOSTICS[:6]
IMPedance_DIAGNOSTIC = DIAGNOSTICS[-1]
NPZ_REQUIRED = (
    "frequencies_hz", "angles_deg", "horizontal_db", "vertical_db",
    "horizontal_pressure", "vertical_pressure", "impedance",
)
STUDY_ROOT = Path("examples/control-decoupling")
HISTORICAL_ROOT = Path("examples/mouth-size-coverage-grid")
PRIMARY_DIR = Path("models/round_control_primary_v1")
AUGMENTED_DIR = Path("models/round_control_augmented_v1")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash(value: Any) -> str:
    return _digest_bytes(_canonical_json(value).encode())


def _source_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", str(Path(__file__))],
            text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _normalize_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def _config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["horncad_config"]


def _coordinates(config: dict[str, Any]) -> dict[str, float]:
    global_config = config["global"]
    horizontal = config["horizontal_basis"]
    vertical = config["vertical_basis"]
    intent = config.get("operating_intent", {})
    if not (
        math.isclose(float(global_config["mouth_width"]),
                     float(global_config["mouth_height"]), abs_tol=1e-6)
        and math.isclose(float(horizontal["coverage_deg"]),
                         float(vertical["coverage_deg"]), abs_tol=1e-6)
        and math.isclose(float(horizontal["k"]), float(vertical["k"]), abs_tol=1e-6)
        and math.isclose(float(horizontal["n"]), float(vertical["n"]), abs_tol=1e-6)
        and math.isclose(float(global_config.get("conical_extension_length", 0.0)),
                         0.0, abs_tol=1e-6)
        and math.isclose(float(config.get("section_modifier", {}).get(
            "mouth_squareness", 0.0)), 0.0, abs_tol=1e-6)
    ):
        raise ValueError(
            "response is not an axisymmetric round-mouth zero-extension horn")
    coverage = float(intent.get("horizontal_coverage_deg",
                                horizontal["coverage_deg"]))
    return {
        "mouth_mm": float(global_config["mouth_width"]),
        "coverage_deg": coverage,
        "length_mm": float(global_config["length"]),
        "k": float(horizontal["k"]),
        "n": float(horizontal["n"]),
        "s": float(horizontal["solved_s"]),
        "crossover_hz": float(intent["crossover_hz"]),
        "upper_frequency_hz": float(intent["upper_frequency_hz"]),
    }


def _response_values(
    diagnostics: dict[str, Any],
    impedance: dict[str, Any],
    *,
    score_key: str = "score",
) -> dict[str, float]:
    def mean_axis(path: tuple[str, ...]) -> float:
        values = []
        for axis in ("horizontal", "vertical"):
            selected: Any = diagnostics[axis]
            for key in path:
                selected = selected[key]
            values.append(float(selected))
        return sum(values) / 2.0

    return {
        "surface_score": float(diagnostics[score_key]["overall_percent"]),
        "mean_containment": 100.0 * mean_axis(("containment", "mean_fraction")),
        "profile_rms_error": mean_axis(
            ("distribution", "rms_profile_error_db")),
        "slice_energy_rms_departure": mean_axis(
            ("slice_energy_stability", "rms_departure_db")),
        "outward_rise_violation": mean_axis(
            ("distribution", "rms_outward_rise_violation_db")),
        "minus_six_db_rms_error": mean_axis(
            ("minus_six_line", "rms_coverage_error_deg")),
        "throat_impedance_score": float(impedance["overall_percent"]),
    }


def _rescore(response: Path) -> tuple[dict[str, float], dict[str, Any], float]:
    run = load_run(response.parent)
    crossover = float(run["crossover_hz"])
    upper = float(run["frequencies"][-1])
    count = int(math.ceil(math.log2(upper / crossover) * 48)) + 1
    grid = np.geomspace(crossover, upper, count)
    radiation = surface_diagnostics(run, grid, fixed_band=True)
    if radiation.get("status") != "available":
        raise ValueError(f"surface diagnostics unavailable: {response}")
    if run.get("normalized_impedance") is None:
        raise ValueError(f"normalized impedance unavailable: {response}")
    impedance = throat_impedance_diagnostics(
        run["frequencies"], run["normalized_impedance"], crossover, upper)
    stored_path = response.with_name("surface_diagnostics.json")
    maximum_delta = 0.0
    if stored_path.is_file():
        stored_document = json.loads(stored_path.read_text(encoding="utf-8"))
        stored = next(iter(stored_document.values()))
        old = _response_values(stored, impedance)
        new = _response_values(radiation, impedance, score_key="score_v1")
        maximum_delta = max(abs(old[name] - new[name])
                            for name in PREREGISTERED_DIAGNOSTICS)
    return (
        _response_values(radiation, impedance, score_key="score_v1"),
        impedance,
        maximum_delta,
    )


def _validate_npz(path: Path) -> tuple[dict[str, Any], str]:
    with np.load(path, allow_pickle=False) as archive:
        missing = sorted(set(NPZ_REQUIRED) - set(archive.files))
        if missing:
            raise ValueError(f"{path}: missing arrays {missing}")
        arrays = {}
        for name in archive.files:
            value = np.asarray(archive[name])
            if value.dtype.kind in "fc" and not np.all(np.isfinite(value)):
                raise ValueError(f"{path}: non-finite {name}")
            arrays[name] = {"shape": list(value.shape), "dtype": str(value.dtype)}
        if archive["horizontal_db"].shape != archive["vertical_db"].shape:
            raise ValueError(f"{path}: plane response shapes differ")
        if archive["horizontal_db"].shape != (
                len(archive["frequencies_hz"]), len(archive["angles_deg"])):
            raise ValueError(f"{path}: response axes do not match")
        fingerprint = hashlib.sha256()
        for name in ("frequencies_hz", "angles_deg"):
            fingerprint.update(np.asarray(archive[name]).tobytes())
        for name in ("normalization", "radiation_model"):
            fingerprint.update(str(archive[name]).encode())
    return arrays, fingerprint.hexdigest()


def _canonical_rows(study_root: Path) -> list[dict[str, Any]]:
    manifest = json.loads((study_root / "manifest.json").read_text())
    coordinate_manifest = {row["id"]: row for row in manifest["coordinates"]}
    rows = []
    for search_yaml in sorted((study_root / "searches").glob("**/search.yaml")):
        if not search_yaml.with_name("search_state.json").is_file():
            continue
        search = yaml.safe_load(search_yaml.read_text())["bem_candidate_search"]
        declared = search["control_decoupling"]["coordinates"]
        state = json.loads(search_yaml.with_name("search_state.json").read_text())
        records = state.get("candidates", [])
        for coordinate in declared:
            matches = []
            for record in records:
                values = record.get("values", {})
                try:
                    same = (
                        math.isclose(float(values["length_mm"]),
                                     float(coordinate["length_mm"]), abs_tol=2e-5)
                        and math.isclose(float(values["k_h"]),
                                         float(coordinate["k"]), abs_tol=2e-5)
                        and math.isclose(float(values["n_h"]),
                                         float(coordinate["n"]), abs_tol=2e-5))
                except (KeyError, TypeError, ValueError):
                    same = False
                if same:
                    matches.append(record)
            if len(matches) != 1 or matches[0].get("status") != "complete":
                raise ValueError(f"{coordinate['id']}: no unique complete response")
            record = matches[0]
            response = (search_yaml.parent / "candidates" / record["id"] /
                        "bem" / "responses.npz")
            if not response.is_file():
                raise FileNotFoundError(response)
            row = dict(coordinate_manifest.get(coordinate["id"], coordinate))
            row.update(coordinate)
            row["_response"] = response
            row["_provenance"] = "canonical"
            rows.append(row)
    return rows


def _historical_rows(historical_root: Path, manifest: dict[str, Any]
                     ) -> list[dict[str, Any]]:
    reference_by_response = {
        row["reused_from"]["response"]: row
        for row in manifest["coordinates"]
        if row.get("kind") == "reference-anchor"
    }
    output = []
    for response in sorted(historical_root.glob("**/responses.npz")):
        response_path = str(response.relative_to(historical_root))
        project = response.parents[1] / "project.yaml"
        config = _config(project)
        global_config = config["global"]
        horizontal = config["horizontal_basis"]
        vertical = config["vertical_basis"]
        intent = config.get("operating_intent", {})
        coverage_h = float(intent.get("horizontal_coverage_deg",
                                      horizontal["coverage_deg"]))
        coverage_v = float(intent.get("vertical_coverage_deg",
                                      vertical["coverage_deg"]))
        compatible_geometry = (
            math.isclose(float(global_config["mouth_width"]),
                         float(global_config["mouth_height"]), abs_tol=1e-6)
            and math.isclose(coverage_h, coverage_v, abs_tol=1e-6)
            and math.isclose(float(horizontal["k"]), float(vertical["k"]),
                             abs_tol=1e-6)
            and math.isclose(float(horizontal["n"]), float(vertical["n"]),
                             abs_tol=1e-6)
            and math.isclose(float(global_config.get(
                "conical_extension_length", 0.0)), 0.0, abs_tol=1e-6)
            and math.isclose(float(config.get("section_modifier", {}).get(
                "mouth_squareness", 0.0)), 0.0, abs_tol=1e-6)
        )
        search_path = str(response.parents[3].relative_to(historical_root))
        candidate_id = response.parents[1].name
        reference = reference_by_response.get(response_path)
        output.append({
            "id": (reference["id"] if reference else
                   f"historical:{search_path}:{candidate_id}"),
            "kind": "reference-anchor" if reference else "historical",
            "stage": "reference-anchor" if reference else "historical",
            "coverage_deg": (coverage_h + coverage_v) / 2.0,
            "mouth_mm": (float(global_config["mouth_width"]) +
                         float(global_config["mouth_height"])) / 2.0,
            "length_mm": float(global_config["length"]),
            "k": (float(horizontal["k"]) + float(vertical["k"])) / 2.0,
            "n": (float(horizontal["n"]) + float(vertical["n"])) / 2.0,
            "s": (float(horizontal["solved_s"]) +
                  float(vertical["solved_s"])) / 2.0,
            "_compatible_geometry": compatible_geometry,
            "_response": response,
            "_provenance": "canonical-reference" if reference else "historical",
            "_search": search_path,
            "_candidate_id": candidate_id,
        })
    return output


def _reference_lengths(manifest: dict[str, Any]) -> dict[tuple[int, int], float]:
    return {
        (int(row["coverage_deg"]), int(row["mouth_mm"])): float(row["length_mm"])
        for row in manifest["coordinates"] if row.get("kind") == "reference-anchor"
    }


def assemble_dataset(
        study_root: Path = STUDY_ROOT,
        historical_root: Path = HISTORICAL_ROOT,
        output: Path | None = None,
) -> dict[str, Any]:
    """Audit all retained responses, rescore them, and build the role index."""
    output = output or (study_root / "model_source")
    manifest = json.loads((study_root / "manifest.json").read_text())
    runtime = json.loads((study_root / "runtime_state.json").read_text())
    if runtime.get("status") != "complete" or runtime.get("failure_count") != 0:
        raise ValueError("canonical runtime is not complete and failure-free")
    if len(runtime.get("skipped_searches", [])) != 41:
        raise ValueError("expected 41 conditionally skipped searches")
    canonical = _canonical_rows(study_root)
    historical = _historical_rows(historical_root, manifest)
    if len(canonical) != 611:
        raise ValueError(f"expected 611 canonical responses, found {len(canonical)}")
    if len(historical) != 904:
        raise ValueError(f"expected 904 compatible historical responses, found {len(historical)}")
    benchmark_document = json.loads((study_root / "benchmarks.json").read_text())
    benchmark_responses = {row["response"] for row in benchmark_document["benchmarks"]}
    reference_lengths = _reference_lengths(manifest)
    source_rows = canonical + sorted(
        historical,
        key=lambda row: (
            0 if row["_provenance"] == "canonical-reference" else 1,
            row["id"],
        ))
    index_rows = []
    response_hashes: dict[str, str] = {}
    canonical_duplicate_count = 0
    maximum_rescore_delta = 0.0
    response_fingerprints = set()
    solver_fingerprints = set()
    for source in source_rows:
        response = Path(source.pop("_response"))
        arrays, response_fingerprint = _validate_npz(response)
        response_fingerprints.add(response_fingerprint)
        values, impedance, delta = _rescore(response)
        maximum_rescore_delta = max(maximum_rescore_delta, delta)
        response_hash = _digest_file(response)
        coordinate_hash = _content_hash({
            key: source[key] for key in
            ("coverage_deg", "mouth_mm", "length_mm", "k", "n")
        })
        cell = (int(source["coverage_deg"]), int(source["mouth_mm"]))
        kind = source.get("kind")
        provenance = source.pop("_provenance")
        relative = str(response)
        historical_relative = (
            str(response.relative_to(historical_root))
            if historical_root in response.parents else None)
        if provenance == "canonical" and kind == "locked-validation":
            role = "locked_validation"
        elif provenance in {"canonical", "canonical-reference"} and kind in {
                "canonical-grid", "reference-anchor"}:
            role = "fit"
        elif (provenance == "historical"
              and source.pop("_compatible_geometry", True)
              and (int(source["coverage_deg"]), int(source["mouth_mm"]))
              in reference_lengths):
            role = "historical_challenge"
        else:
            role = "excluded"
        duplicate_of = response_hashes.get(response_hash)
        if duplicate_of:
            role = "excluded"
            if provenance == "canonical":
                canonical_duplicate_count += 1
        else:
            response_hashes[response_hash] = source["id"]
        reference_length = reference_lengths.get(cell)
        row = {
            **{key: value for key, value in source.items()
               if not key.startswith("_")},
            "length_factor": (
                float(source["length_mm"]) / reference_length
                if reference_length is not None else None),
            "reference_length_mm": reference_length,
            "derived_s": float(source["s"]),
            "source_path": relative,
            "provenance": provenance,
            "role": role,
            "benchmark": bool(historical_relative in benchmark_responses),
            "coordinate_hash": coordinate_hash,
            "response_sha256": response_hash,
            "diagnostic_sha256": _content_hash(values),
            "responses": values,
            "throat_impedance": impedance,
            "npz_arrays": arrays,
        }
        if duplicate_of:
            row["exclusion_reason"] = "exact response duplicate"
            row["duplicate_of"] = duplicate_of
        elif role == "excluded":
            row["exclusion_reason"] = (
                "historical geometry is outside the released round-control domain"
                if provenance == "historical" and cell not in reference_lengths
                else "historical geometry is not symmetric in K/N"
                if provenance == "historical"
                else "canonical boundary/conditional closure excluded from preregistered fit")
        index_rows.append(row)
        project = response.parents[1] / "project.yaml"
        search_yaml = response.parents[3] / "search.yaml"
        if search_yaml.is_file():
            search = yaml.safe_load(search_yaml.read_text())["bem_candidate_search"]
            fingerprint = _solver_fingerprint(search)
            # YAML may spell numerically identical settings as integers or floats.
            solver_fingerprints.add(_content_hash(_normalize_numbers(fingerprint)))
    if maximum_rescore_delta > 1e-9:
        raise ValueError(
            f"stored diagnostics differ from versioned recalculation by "
            f"{maximum_rescore_delta:g}")
    coordinate_hash = _content_hash([
        row["coordinate_hash"] for row in sorted(index_rows, key=lambda item: item["id"])
    ])
    diagnostic_implementation = _content_hash({
        "surface_diagnostics.py": _digest_file(Path(__file__).with_name(
            "surface_diagnostics.py")),
        "throat_impedance_diagnostics.py": _digest_file(Path(__file__).with_name(
            "throat_impedance_diagnostics.py")),
    })
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "canonical_npz_count": len(canonical),
        "historical_npz_count": len(historical),
        "searches_complete": 168,
        "conditional_closures_skipped": 41,
        "unresolved_failures": 0,
        "exact_response_duplicates_after_deduplication": sum(
            row["role"] == "excluded" and
            row.get("exclusion_reason") == "exact response duplicate"
            for row in index_rows),
        "canonical_response_duplicates": canonical_duplicate_count,
        "numcalc_work_tree_count": len(list(study_root.glob(
            "**/project-NumCalc-*"))),
        "maximum_stored_diagnostic_delta": maximum_rescore_delta,
        "coordinate_hash": coordinate_hash,
        "solver_configuration_fingerprints": sorted(solver_fingerprints),
        "response_grid_fingerprints": sorted(response_fingerprints),
        "diagnostic_implementation_sha256": diagnostic_implementation,
    }
    if audit["numcalc_work_tree_count"]:
        raise ValueError("retained NumCalc work trees found")
    if canonical_duplicate_count:
        raise ValueError("canonical study contains duplicate responses")
    if len(response_fingerprints) != 1 or len(solver_fingerprints) != 1:
        raise ValueError("solver/frequency fingerprints are not uniform")
    training_index = {
        "schema_version": SCHEMA_VERSION,
        "coordinate_hash": coordinate_hash,
        "diagnostic_implementation_sha256": diagnostic_implementation,
        "roles": dict(Counter(row["role"] for row in index_rows)),
        "rows": sorted(index_rows, key=lambda item: item["id"]),
    }
    _write_json(output / "audit.json", audit)
    _write_json(output / "training_index.json", training_index)
    return training_index


def _basis(length_factor: float, k: float, n: float) -> np.ndarray:
    l = ((length_factor - CONTROL_SCALING["length_factor"]["center"]) /
         CONTROL_SCALING["length_factor"]["scale"])
    kk = (k - CONTROL_SCALING["k"]["center"]) / CONTROL_SCALING["k"]["scale"]
    nn = (n - CONTROL_SCALING["n"]["center"]) / CONTROL_SCALING["n"]["scale"]
    return np.asarray((1.0, l, kk, nn, l*l, kk*kk, nn*nn,
                       l*kk, l*nn, kk*nn), dtype=float)


def _fit_cells(rows: list[dict[str, Any]], *, weighted: bool
               ) -> tuple[dict[str, Any], dict[str, Any]]:
    cells: dict[str, Any] = {}
    audit: dict[str, Any] = {}
    for coverage in ANGLES:
        for mouth in MOUTHS:
            selected = [
                row for row in rows
                if int(row["coverage_deg"]) == coverage
                and int(row["mouth_mm"]) == mouth
            ]
            x = np.vstack([_basis(row["length_factor"], row["k"], row["n"])
                           for row in selected])
            if np.linalg.matrix_rank(x) != 10:
                raise ValueError(f"{coverage}deg-{mouth}mm loses rank 10")
            condition = float(np.linalg.cond(x))
            if not math.isfinite(condition) or condition > 1e8:
                raise ValueError(f"{coverage}deg-{mouth}mm invalid condition {condition}")
            weights = np.ones(len(selected))
            if weighted:
                bins = Counter((
                    round((row["length_factor"] - 1.0) / 0.05),
                    round((row["k"] - 4.0) / 0.25),
                    round((row["n"] - 8.0) / 1.0),
                ) for row in selected if row["provenance"] == "historical")
                weights = np.asarray([
                    1.0 if row["provenance"] != "historical" else
                    1.0 / bins[(
                        round((row["length_factor"] - 1.0) / 0.05),
                        round((row["k"] - 4.0) / 0.25),
                        round((row["n"] - 8.0) / 1.0),
                    )]
                    for row in selected
                ])
            root_weights = np.sqrt(weights)
            xw = x * root_weights[:, None]
            coefficients = {}
            residual_std = {}
            covariance = {}
            residual_matrix = []
            for diagnostic in DIAGNOSTICS:
                y = np.asarray([row["responses"][diagnostic] for row in selected])
                beta, *_ = np.linalg.lstsq(xw, y * root_weights, rcond=None)
                residual = y - x @ beta
                dof = max(1, len(y) - 10)
                variance = float(np.sum(weights * residual**2) / dof)
                coefficients[diagnostic] = beta.tolist()
                residual_std[diagnostic] = math.sqrt(max(variance, 0.0))
                covariance[diagnostic] = (
                    np.linalg.pinv(xw.T @ xw) * variance).tolist()
                residual_matrix.append(residual)
            residual_array = np.asarray(residual_matrix)
            cell_id = f"{coverage}deg-{mouth}mm"
            cells[cell_id] = {
                "coverage_deg": coverage,
                "mouth_mm": mouth,
                "coefficients": coefficients,
                "coefficient_covariance": covariance,
                "residual_std": residual_std,
                "residual_covariance": np.cov(residual_array).tolist(),
                "support": {
                    "length_factor": [min(row["length_factor"] for row in selected),
                                      max(row["length_factor"] for row in selected)],
                    "k": [min(row["k"] for row in selected),
                          max(row["k"] for row in selected)],
                    "n": [min(row["n"] for row in selected),
                          max(row["n"] for row in selected)],
                },
                "evidence_ids": [row["id"] for row in selected],
            }
            audit[cell_id] = {
                "rows": len(selected), "rank": int(np.linalg.matrix_rank(x)),
                "condition_number": condition,
                "effective_weight": float(np.sum(weights)),
            }
    return cells, audit


def _base_model(model_id: str, cells: dict[str, Any],
                training_index: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    manifest_path = STUDY_ROOT / "manifest.json"
    execution_path = STUDY_ROOT / "execution_plan.json"
    references = {
        cell_id: cell["reference_length_mm"]
        for cell_id, cell in _reference_fields(training_index).items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "model_id": model_id,
        "model_family": "axisymmetric round-mouth zero-extension OS-SE",
        "diagnostics": list(DIAGNOSTICS),
        "preregistered_diagnostics": list(PREREGISTERED_DIAGNOSTICS),
        "experimental_diagnostics": {
            IMPedance_DIAGNOSTIC: {
                "status": "experimental preparatory output",
                "included_in_surface_score": False,
                "included_in_model_choice": False,
            },
        },
        "terms": list(MODEL_TERMS),
        "control_scaling": CONTROL_SCALING,
        "coefficient_interpolation": "bilinear",
        "mouth_grid_mm": list(MOUTHS),
        "coverage_grid_deg": list(ANGLES),
        "reference_length_mm": references,
        "geometry_policy": {
            "derived_s_bounds": [0.05, 4.0],
            "maximum_final_tenth_radial_growth_fraction": 0.52,
            "throat_radius_mm": 12.7,
            "throat_angle_deg": 6.0,
            "extension_mm": 0.0,
        },
        "cells": cells,
        "fit_audit": audit,
        "provenance": {
            "manifest_sha256": _digest_file(manifest_path),
            "execution_plan_sha256": _digest_file(execution_path),
            "diagnostic_implementation_sha256":
                training_index["diagnostic_implementation_sha256"],
            "coordinate_hash": training_index["coordinate_hash"],
            "fitting_implementation_sha256": _digest_file(Path(__file__)),
            "fitting_code_git_commit": _source_git_commit(),
        },
    }


def _loco_interpolation_audit(cells: dict[str, Any],
                              rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare bilinear coefficient fields with a nearest-cell baseline."""
    errors = {"bilinear": [], "nearest": []}
    for coverage in ANGLES:
        for mouth in MOUTHS:
            omitted = f"{coverage}deg-{mouth}mm"
            retained = [(cell_id, cell) for cell_id, cell in cells.items()
                        if cell_id != omitted]
            field_x = np.asarray([
                (1.0, (cell["mouth_mm"]-350)/100,
                 (cell["coverage_deg"]-40)/10,
                 ((cell["mouth_mm"]-350)/100) *
                 ((cell["coverage_deg"]-40)/10))
                for _, cell in retained])
            target_x = np.asarray((
                1.0, (mouth-350)/100, (coverage-40)/10,
                ((mouth-350)/100)*((coverage-40)/10)))
            nearest = min(
                retained,
                key=lambda item:
                ((item[1]["mouth_mm"]-mouth)/50)**2 +
                ((item[1]["coverage_deg"]-coverage)/5)**2)[1]
            coefficients = {"bilinear": {}, "nearest": nearest["coefficients"]}
            for diagnostic in DIAGNOSTICS:
                field_y = np.asarray([
                    cell["coefficients"][diagnostic] for _, cell in retained])
                field_beta, *_ = np.linalg.lstsq(field_x, field_y, rcond=None)
                coefficients["bilinear"][diagnostic] = (
                    target_x @ field_beta).tolist()
            omitted_rows = [
                row for row in rows if int(row["coverage_deg"]) == coverage
                and int(row["mouth_mm"]) == mouth]
            for method in errors:
                for row in omitted_rows:
                    basis = _basis(row["length_factor"], row["k"], row["n"])
                    errors[method].append({
                        name: float(np.dot(
                            coefficients[method][name], basis) -
                            row["responses"][name])
                        for name in DIAGNOSTICS
                    })
    summaries = {
        method: {
            name: {
                "mae": float(np.mean([abs(row[name]) for row in method_rows])),
                "rmse": float(np.sqrt(np.mean([
                    row[name]**2 for row in method_rows]))),
            }
            for name in DIAGNOSTICS
        }
        for method, method_rows in errors.items()
    }
    bilinear_loss = sum(
        summaries["bilinear"][name]["rmse"]
        for name in PREREGISTERED_DIAGNOSTICS)
    nearest_loss = sum(
        summaries["nearest"][name]["rmse"]
        for name in PREREGISTERED_DIAGNOSTICS)
    return {
        "method": "leave-one-mouth/coverage-cell-out coefficient fields",
        "selected": "bilinear",
        "selection_reason": (
            "simplest preregistered cross-cell interpolator; compared with "
            "nearest-cell baseline using canonical fit evidence only"),
        "bilinear_six_diagnostic_rmse_sum": bilinear_loss,
        "nearest_six_diagnostic_rmse_sum": nearest_loss,
        "bilinear_wins_baseline": bilinear_loss <= nearest_loss,
        "summary": summaries,
    }


def _reference_fields(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output = {}
    for row in index["rows"]:
        cell_id = f"{int(row['coverage_deg'])}deg-{int(row['mouth_mm'])}mm"
        output[cell_id] = {"reference_length_mm": row["reference_length_mm"]}
    return output


def fit_primary(training_index: dict[str, Any] | None = None,
                output: Path = PRIMARY_DIR) -> dict[str, Any]:
    training_index = training_index or json.loads(
        (STUDY_ROOT / "model_source/training_index.json").read_text())
    rows = [row for row in training_index["rows"] if row["role"] == "fit"]
    cells, audit = _fit_cells(rows, weighted=False)
    model = _base_model("round_control_primary_v1", cells, training_index, audit)
    model["leave_one_cell_out"] = _loco_interpolation_audit(cells, rows)
    model["fit_roles"] = ["fit"]
    model["model_sha256"] = _content_hash(model)
    freeze = {
        "model_id": model["model_id"],
        "model_sha256": model["model_sha256"],
        "locked_and_historical_outcomes_loaded": False,
        "fit_row_count": len(rows),
        "fit_evidence_ids_sha256": _content_hash(sorted(row["id"] for row in rows)),
    }
    _write_json(output / "model.json", model)
    _write_json(output / "primary_freeze.json", freeze)
    return model


def _bracket(grid: Iterable[float], value: float) -> tuple[float, float, float]:
    values = list(map(float, grid))
    if value <= values[0]:
        return values[0], values[0], 0.0
    if value >= values[-1]:
        return values[-1], values[-1], 0.0
    upper_index = int(np.searchsorted(values, value))
    lower, upper = values[upper_index - 1], values[upper_index]
    return lower, upper, (value - lower) / (upper - lower)


def evaluate_model(model: dict[str, Any], *, mouth_mm: float,
                   coverage_deg: float, length_mm: float, k: float,
                   n: float) -> dict[str, float]:
    references = model["reference_length_mm"]
    m0, m1, tm = _bracket(model["mouth_grid_mm"], mouth_mm)
    c0, c1, tc = _bracket(model["coverage_grid_deg"], coverage_deg)
    corners = ((c0, m0, (1-tc)*(1-tm)), (c0, m1, (1-tc)*tm),
               (c1, m0, tc*(1-tm)), (c1, m1, tc*tm))
    active = [(c, m, weight) for c, m, weight in corners if weight > 0]
    if not active:
        active = [(c0, m0, 1.0)]
    reference_length = sum(
        references[f"{int(c)}deg-{int(m)}mm"] * weight
        for c, m, weight in active)
    basis = _basis(length_mm / reference_length, k, n)
    return {
        diagnostic: float(sum(
            weight * np.dot(
                model["cells"][f"{int(c)}deg-{int(m)}mm"]["coefficients"][diagnostic],
                basis)
            for c, m, weight in active))
        for diagnostic in DIAGNOSTICS
    }


def _errors(model: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        predicted = evaluate_model(
            model, mouth_mm=row["mouth_mm"], coverage_deg=row["coverage_deg"],
            length_mm=row["length_mm"], k=row["k"], n=row["n"])
        errors = {name: predicted[name] - row["responses"][name]
                  for name in DIAGNOSTICS}
        output.append({
            "id": row["id"], "mouth_mm": row["mouth_mm"],
            "coverage_deg": row["coverage_deg"],
            "length_factor": row["length_factor"], "k": row["k"], "n": row["n"],
            "provenance": row["provenance"], "benchmark": row["benchmark"],
            "parameter_distance": float(np.linalg.norm(_basis(
                row["length_factor"], row["k"], row["n"])[1:4])),
            "observed": row["responses"], "predicted": predicted, "error": errors,
        })
    return output


def _summarize_errors(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "mae": float(np.mean([abs(row["error"][name]) for row in rows])),
            "rmse": float(np.sqrt(np.mean([
                row["error"][name] ** 2 for row in rows]))),
            "p90_absolute": float(np.percentile([
                abs(row["error"][name]) for row in rows], 90)),
            "mean_signed": float(np.mean([row["error"][name] for row in rows])),
        }
        for name in DIAGNOSTICS
    } if rows else {}


def _grouped_error_views(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distance_bins = {
        "0-1": (0.0, 1.0), "1-2": (1.0, 2.0),
        "2-3": (2.0, 3.0), "3+": (3.0, math.inf),
    }
    score_bins = {
        "below-70": (-math.inf, 70.0), "70-80": (70.0, 80.0),
        "80-90": (80.0, 90.0), "90+": (90.0, math.inf),
    }
    return {
        "by_cell": {
            f"{coverage}deg-{mouth}mm": _summarize_errors([
                row for row in rows
                if int(row["coverage_deg"]) == coverage
                and int(row["mouth_mm"]) == mouth])
            for coverage in ANGLES for mouth in MOUTHS
        },
        "by_parameter_distance": {
            label: _summarize_errors([
                row for row in rows if low <= row["parameter_distance"] < high])
            for label, (low, high) in distance_bins.items()
        },
        "by_observed_surface_score": {
            label: _summarize_errors([
                row for row in rows
                if low <= row["observed"]["surface_score"] < high])
            for label, (low, high) in score_bins.items()
        },
    }


def validate_primary(
        training_index: dict[str, Any] | None = None,
        model: dict[str, Any] | None = None,
        output: Path = PRIMARY_DIR,
) -> dict[str, Any]:
    freeze_path = output / "primary_freeze.json"
    if not freeze_path.is_file():
        raise ValueError("primary freeze hash must exist before validation outcomes load")
    training_index = training_index or json.loads(
        (STUDY_ROOT / "model_source/training_index.json").read_text())
    model = model or json.loads((output / "model.json").read_text())
    freeze = json.loads(freeze_path.read_text())
    if freeze["model_sha256"] != model["model_sha256"]:
        raise ValueError("primary model does not match freeze hash")
    locked_rows = [row for row in training_index["rows"]
                   if row["role"] == "locked_validation"]
    historical_rows = [row for row in training_index["rows"]
                       if row["role"] == "historical_challenge"]
    locked_errors = _errors(model, locked_rows)
    historical_errors = _errors(model, historical_rows)
    benchmark_rows = [row for row in training_index["rows"] if row["benchmark"]]
    benchmarks = _errors(model, benchmark_rows)
    validation = {
        "schema_version": SCHEMA_VERSION,
        "model_id": model["model_id"],
        "primary_freeze_sha256": _content_hash(freeze),
        "sequence": [
            "primary freeze", "50 locked responses", "historical challenge",
            "25 historical optimum audit",
        ],
        "locked": {
            "count": len(locked_errors),
            "summary": _summarize_errors(locked_errors),
            **_grouped_error_views(locked_errors),
            "rows": locked_errors,
        },
        "historical_challenge": {
            "count": len(historical_errors),
            "summary": _summarize_errors(historical_errors),
            **_grouped_error_views(historical_errors),
            "by_sampling_regime": {
                regime: _summarize_errors([
                    row for row in historical_errors if regime in row["id"]])
                for regime in (
                    "s-grid", "kn-grid", "domain-map", "s-boundary", "coupled")
            },
            "rows": historical_errors,
        },
        "historical_benchmarks": {
            "count": len(benchmarks), "summary": _summarize_errors(benchmarks),
            "rows": benchmarks,
        },
        "unsupported_regions": [
            "mouth or coverage outside the 250–450 mm / 30–50 degree grid",
            "non-square, asymmetric, extended, squared, sagged, or non-6-degree-throat horns",
            "off-grid mouth/coverage interpolation is uncertainty-labeled and not simulation-confirmed",
        ],
    }
    model["interval_half_width"] = {
        name: max(
            validation["locked"]["summary"][name]["p90_absolute"],
            max(cell["residual_std"][name] for cell in model["cells"].values()) * 1.645,
        )
        for name in DIAGNOSTICS
    }
    model["model_sha256"] = _content_hash({
        key: value for key, value in model.items() if key != "model_sha256"
    })
    _write_json(output / "model.json", model)
    _write_json(output / "validation.json", validation)
    return validation


def fit_augmented(
        training_index: dict[str, Any] | None = None,
        primary_validation: dict[str, Any] | None = None,
        output: Path = AUGMENTED_DIR,
) -> dict[str, Any]:
    training_index = training_index or json.loads(
        (STUDY_ROOT / "model_source/training_index.json").read_text())
    primary_validation = primary_validation or json.loads(
        (PRIMARY_DIR / "validation.json").read_text())
    if primary_validation["locked"]["count"] != 50:
        raise ValueError("augmented fit requires recorded primary locked validation")
    rows = [row for row in training_index["rows"]
            if row["role"] in {"fit", "historical_challenge"}]
    cells, audit = _fit_cells(rows, weighted=True)
    model = _base_model("round_control_augmented_v1", cells, training_index, audit)
    model["fit_roles"] = ["fit", "historical_challenge"]
    model["density_weighting"] = {
        "method": "inverse occupancy in 0.05 L-factor × 0.25 K × 1 N bins",
        "canonical_weight": 1.0,
    }
    locked_rows = [row for row in training_index["rows"]
                   if row["role"] == "locked_validation"]
    augmented_errors = _errors(model, locked_rows)
    augmented_summary = _summarize_errors(augmented_errors)
    primary_by_cell = primary_validation["locked"]["by_cell"]
    choice = {}
    for coverage in ANGLES:
        for mouth in MOUTHS:
            cell_id = f"{coverage}deg-{mouth}mm"
            local = [row for row in augmented_errors
                     if int(row["coverage_deg"]) == coverage
                     and int(row["mouth_mm"]) == mouth]
            local_summary = _summarize_errors(local)
            primary_loss = sum(primary_by_cell[cell_id][name]["mae"]
                               for name in PREREGISTERED_DIAGNOSTICS)
            augmented_loss = sum(local_summary[name]["mae"]
                                 for name in PREREGISTERED_DIAGNOSTICS)
            choice[cell_id] = {
                "normal_model": ("augmented" if augmented_loss <= primary_loss
                                 else "primary"),
                "primary_six_diagnostic_mae_sum": primary_loss,
                "augmented_six_diagnostic_mae_sum": augmented_loss,
                "throat_impedance_excluded_from_choice": True,
            }
    model["choice_by_cell"] = choice
    model["companion_model"] = "../round_control_primary_v1/model.json"
    model["interval_half_width"] = {
        name: max(
            augmented_summary[name]["p90_absolute"],
            max(cell["residual_std"][name] for cell in model["cells"].values()) * 1.645,
        )
        for name in DIAGNOSTICS
    }
    model["model_sha256"] = _content_hash(model)
    validation = {
        "schema_version": SCHEMA_VERSION,
        "model_id": model["model_id"],
        "locked": {"count": len(augmented_errors), "summary": augmented_summary,
                   "rows": augmented_errors},
        "model_choice_by_cell": choice,
        "primary_validation_sha256": _content_hash(primary_validation),
        "throat_impedance_used_in_model_choice": False,
    }
    _write_json(output / "model.json", model)
    _write_json(output / "validation.json", validation)
    return model


def export_release(
        training_index: dict[str, Any] | None = None,
        primary_dir: Path = PRIMARY_DIR,
        augmented_dir: Path = AUGMENTED_DIR,
) -> None:
    training_index = training_index or json.loads(
        (STUDY_ROOT / "model_source/training_index.json").read_text())
    for path, title in (
            (primary_dir, "Round Control Primary v1"),
            (augmented_dir, "Round Control Augmented v1")):
        model = json.loads((path / "model.json").read_text())
        validation = json.loads((path / "validation.json").read_text())
        _write_json(path / "training_index.json", training_index)
        _write_json(path / "provenance.json", {
            **model["provenance"],
            "model_sha256": model["model_sha256"],
            "training_index_sha256": _content_hash(training_index),
            "validation_sha256": _content_hash(validation),
        })
        _write_json(path / "rules.json", {
            "schema_version": SCHEMA_VERSION,
            "status": "placeholder",
            "rules": [],
            "reason": "diagnose/improve/rule extraction deferred until predict verification",
        })
        card = f"""# {title}

Portable quadratic response model for axisymmetric, round-mouth,
zero-extension OS-SE horns over 250–450 mm mouth diameters and 30–50 degree
coverage.

The six preregistered radiation diagnostics retain their original surface-score
definition. `throat_impedance_score` is an experimental seventh prediction for
future extension/throat-angle work and is not included in surface score,
benchmark ranking, or primary/augmented model choice.

Off-grid mouth/coverage values use bilinear coefficient interpolation. Those
predictions remain uncertainty-labeled until a future real design confirms them.
Non-round, asymmetric, extended, squared, sagged, or non-6-degree-throat designs
are unsupported by this release.

Validation counts: {validation.get("locked", {}).get("count", 0)} locked;
{validation.get("historical_challenge", {}).get("count", 0)} historical challenge.
"""
        (path / "model_card.md").write_text(card, encoding="utf-8")
    _write_extension_handoff(training_index)


def _write_extension_handoff(training_index: dict[str, Any]) -> None:
    """Freeze measured parents and the next study design without scheduling BEM."""
    eligible = [
        row for row in training_index["rows"]
        if row["role"] in {"fit", "historical_challenge"}
        and int(row["coverage_deg"]) in {40, 45}
        and int(row["mouth_mm"]) in {250, 300, 350}
    ]
    parents = []
    for coverage in (40, 45):
        for mouth in (250, 300, 350):
            cell = [row for row in eligible
                    if int(row["coverage_deg"]) == coverage
                    and int(row["mouth_mm"]) == mouth]
            winner = max(cell, key=lambda row: row["responses"]["surface_score"])
            parents.append({
                "id": winner["id"], "coverage_deg": coverage, "mouth_mm": mouth,
                "length_mm": winner["length_mm"], "k": winner["k"],
                "n": winner["n"], "derived_s": winner["derived_s"],
                "measured_diagnostics": winner["responses"],
                "response_sha256": winner["response_sha256"],
            })
    outer_parents = []
    for coverage, mouth in ((30, 250), (30, 450), (50, 250), (50, 450)):
        cell = [row for row in training_index["rows"]
                if row["role"] in {"fit", "historical_challenge"}
                and int(row["coverage_deg"]) == coverage
                and int(row["mouth_mm"]) == mouth]
        winner = max(cell, key=lambda row: row["responses"]["surface_score"])
        outer_parents.append({
            "id": winner["id"], "coverage_deg": coverage, "mouth_mm": mouth,
            "length_mm": winner["length_mm"], "k": winner["k"], "n": winner["n"],
            "derived_s": winner["derived_s"],
            "measured_diagnostics": winner["responses"],
            "response_sha256": winner["response_sha256"],
        })
    candidates = []
    for parent in parents:
        for extension in (0, 20, 40, 60):
            candidates.append({
                "id": f"{parent['id']}:extension-{extension}mm:throat-6deg",
                "parent_id": parent["id"], "extension_mm": extension,
                "throat_angle_deg": 6, "stratum": "core-extension",
            })
        for extension in (0, 40):
            for throat_angle in (4, 8):
                candidates.append({
                    "id": (f"{parent['id']}:extension-{extension}mm:"
                           f"throat-{throat_angle}deg"),
                    "parent_id": parent["id"], "extension_mm": extension,
                    "throat_angle_deg": throat_angle,
                    "stratum": "sparse-throat-angle",
                })
    for parent in outer_parents:
        candidates.append({
            "id": f"{parent['id']}:extension-40mm:throat-6deg",
            "parent_id": parent["id"], "extension_mm": 40,
            "throat_angle_deg": 6, "stratum": "outer-transfer-sentinel",
        })
    handoff = {
        "schema_version": SCHEMA_VERSION,
        "status": "designed-not-scheduled",
        "bem_jobs_scheduled": 0,
        "core_parents": parents,
        "outer_sentinel_parents": outer_parents,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "factors": {
            "coverage_deg": [40, 45], "mouth_mm": [250, 300, 350],
            "extension_mm": [0, 20, 40, 60],
            "throat_angle_deg": {
                "lower": 4, "current": 6, "higher": 8,
                "contrasted_at_extension_mm": [0, 40],
            },
        },
        "release_gates": {
            "round_primary_frozen_and_locked_validated": True,
            "round_augmented_exported": True,
            "throat_impedance_archive_complete": True,
            "throat_impedance_stored_diagnostic_role": (
                "independent experimental output; excluded from surface score"),
            "launch_authorized": False,
            "launch_blocker": (
                "review experimental impedance validation and preregister "
                "extension-specific acceptance thresholds before BEM"),
        },
    }
    _write_json(STUDY_ROOT / "model_source/extension_handoff.json", handoff)


def rebuild_all(study_root: Path = STUDY_ROOT,
                historical_root: Path = HISTORICAL_ROOT) -> None:
    index = assemble_dataset(study_root, historical_root)
    primary = fit_primary(index)
    validation = validate_primary(index, primary)
    fit_augmented(index, validation)
    export_release(index)
