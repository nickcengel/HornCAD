#!/usr/bin/env python3
"""Generate standard HornCAD review artifacts from a completed NumCalc sweep."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re

import numpy as np

try:
    from .helmholtz_bem_3d import CUT_AZIMUTHS, write_cut_csv
    from .interactive_results import single_report
    from .numcalc_bem_backend import read_evaluation_pressure
except ImportError:
    from helmholtz_bem_3d import CUT_AZIMUTHS, write_cut_csv
    from interactive_results import single_report
    from numcalc_bem_backend import read_evaluation_pressure


def _normalized_db(values: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(
        np.abs(values) / np.maximum(np.abs(values[0:1]), 1e-30), 1e-15))


def _half_angle(angles: np.ndarray, level: np.ndarray) -> float:
    for index in range(len(angles) - 1):
        if level[index] >= -6.0 and level[index + 1] < -6.0:
            fraction = (-6.0 - level[index]) / (level[index + 1] - level[index])
            return float(angles[index] + fraction * (angles[index + 1] - angles[index]))
    return 90.0


def _throat_impedance(case_root: Path) -> complex:
    """Return throat impedance in the HornCAD FEM harmonic convention."""
    metadata = json.loads((case_root / "horncad-numcalc.json").read_text())
    boundary = [line for line in
                (case_root / "NumCalc/source_1/NC.inp").read_text().splitlines()
                if " VELO " in line and "VELO 0.0 " not in line][-1]
    match = re.search(r"ELEM (\d+) TO (\d+)", boundary)
    if match is None:
        raise ValueError(f"cannot identify driven throat in {case_root}")
    first, last = map(int, match.groups())
    nodes = np.loadtxt(case_root / "ObjectMeshes/Reference/Nodes.txt",
                       skiprows=1)[:, 1:4]
    triangles = np.loadtxt(case_root / "ObjectMeshes/Reference/Elements.txt",
                           skiprows=1, dtype=int)[:, 1:4]
    areas = .5 * np.linalg.norm(np.cross(
        nodes[triangles[:, 1]] - nodes[triangles[:, 0]],
        nodes[triangles[:, 2]] - nodes[triangles[:, 0]]), axis=1)
    values = np.loadtxt(
        case_root / "NumCalc/source_1/be.out/be.1/pBoundary", skiprows=3)
    pressure = values[:, 1] + 1j * values[:, 2]
    average_pressure = np.sum(pressure[first:last + 1] * areas[first:last + 1]) \
        / np.sum(areas[first:last + 1])
    volume_velocity = metadata["velocity_m_s"] * metadata["source_area_m2"]
    return np.conj(average_pressure / volume_velocity)


def generate_review(run_dir: Path, title: str = "All-BEM free-air exterior",
                    *, write_report: bool = True) -> Path:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "complete":
        raise ValueError(f"NumCalc sweep is not complete: {manifest_path}")
    frequencies = np.asarray(manifest["frequencies_hz"], dtype=float)
    positive_angles = np.linspace(0.0, 90.0, int(manifest["angles"]))
    pressures = {name: [] for name in CUT_AZIMUTHS}
    impedance = []
    rows = []
    for result in manifest["results"]:
        case_root = run_dir / result["case"]
        pressure = read_evaluation_pressure(case_root).reshape(3, len(positive_angles))
        impedance.append(_throat_impedance(case_root))
        run = result["run"]
        levels = {}
        for index, name in enumerate(CUT_AZIMUTHS):
            pressures[name].append(pressure[index])
            levels[name] = _normalized_db(pressure[index])
        rows.append({
            "frequency_hz": result["frequency_hz"],
            "horizontal_6db_half_angle_deg": _half_angle(positive_angles, levels["horizontal"]),
            "diagonal_6db_half_angle_deg": _half_angle(positive_angles, levels["diagonal"]),
            "vertical_6db_half_angle_deg": _half_angle(positive_angles, levels["vertical"]),
            "impedance_magnitude_pa_s_m3": abs(impedance[-1]),
            "iterations": run["iterations"],
            "solve_seconds": run["wall_time_s"],
            "relative_residual": run["relative_error"],
            "peak_rss_gib": run["peak_rss_gib"],
        })

    complex_cuts = {name: np.column_stack(pressures[name]) for name in CUT_AZIMUTHS}
    db = {name: _normalized_db(values) for name, values in complex_cuts.items()}
    for name in CUT_AZIMUTHS:
        write_cut_csv(run_dir / f"numcalc-{name}.csv", positive_angles, frequencies, db[name])

    full_angles = np.concatenate((-positive_angles[:0:-1], positive_angles))
    impedance = np.asarray(impedance)
    full_db = {name: np.vstack((values[:0:-1], values)) for name, values in db.items()}
    np.savez_compressed(
        run_dir / "responses.npz", frequencies_hz=frequencies,
        angles_deg=full_angles, positive_angles_deg=positive_angles,
        horizontal_db=full_db["horizontal"].T,
        diagonal_db=full_db["diagonal"].T,
        vertical_db=full_db["vertical"].T,
        horizontal_pressure=complex_cuts["horizontal"].T,
        diagonal_pressure=complex_cuts["diagonal"].T,
        vertical_pressure=complex_cuts["vertical"].T,
        impedance=impedance,
        normalization="on_axis_per_frequency", radiation_model="NumCalc exterior BEM")
    with (run_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    if write_report:
        single_report(run_dir, run_dir / "interactive_report.html", title)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="directory containing manifest.json")
    args = parser.parse_args()
    print(generate_review(args.run_dir))


if __name__ == "__main__":
    main()
