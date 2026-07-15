#!/usr/bin/env python3
"""Run and compare a retained-depth sequence for one local-lip frequency."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from .aperture_field import normalized_level_db, read_mfem_mouth_csv
    from .local_lip_bem import (
        LocalLipResult,
        LocalLipSettings,
        build_local_lip_mesh,
        solve_local_lip,
        write_result,
    )
except ImportError:
    from aperture_field import normalized_level_db, read_mfem_mouth_csv
    from local_lip_bem import (
        LocalLipResult,
        LocalLipSettings,
        build_local_lip_mesh,
        solve_local_lip,
        write_result,
    )


CUTS = ("horizontal", "diagonal", "vertical")
COMPLEX_RELATIVE_L2_LIMIT = 0.05
NORMALIZED_MAX_DELTA_DB_LIMIT = 0.5
BEAMWIDTH_CHANGE_DEG_LIMIT = 1.0


def beamwidth_deg(angles_deg: np.ndarray, pressure: np.ndarray) -> float:
    """Return signed-cut -6 dB beamwidth with linear crossing interpolation."""
    level = normalized_level_db(pressure, reference="on_axis",
                                on_axis_index=int(np.argmin(np.abs(angles_deg))),
                                floor_db=-300.0)
    zero = int(np.argmin(np.abs(angles_deg)))

    def crossing(step: int) -> float:
        index = zero
        while 0 <= index + step < len(angles_deg) and level[index + step] > -6.0:
            index += step
        other = index + step
        if not 0 <= other < len(angles_deg):
            return float(angles_deg[index])
        fraction = (-6.0 - level[index]) / (level[other] - level[index])
        return float(angles_deg[index] + fraction * (angles_deg[other] - angles_deg[index]))

    return crossing(1) - crossing(-1)


def depth_metrics(depth_m: float, result: LocalLipResult,
                  angles_deg: np.ndarray) -> dict[str, float]:
    row: dict[str, float] = {"retained_depth_mm": depth_m * 1e3,
                             "dofs": float(result.dofs)}
    for cut in CUTS:
        incident = result.incident_pressure_pa[cut]
        scattered = result.scattered_pressure_pa[cut]
        total = result.total_pressure_pa[cut]
        row[f"{cut}_scattered_to_incident_l2"] = float(
            np.linalg.norm(scattered) / max(np.linalg.norm(incident), 1e-30))
        row[f"{cut}_beamwidth_deg"] = beamwidth_deg(angles_deg, total)
    return row


def adjacent_metrics(left_depth_m: float, left: LocalLipResult,
                     right_depth_m: float, right: LocalLipResult,
                     angles_deg: np.ndarray) -> dict[str, float]:
    row: dict[str, float] = {
        "coarse_depth_mm": left_depth_m * 1e3,
        "fine_depth_mm": right_depth_m * 1e3,
    }
    for cut in CUTS:
        a = left.total_pressure_pa[cut]
        b = right.total_pressure_pa[cut]
        row[f"{cut}_complex_relative_l2"] = float(
            np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-30))
        a_db = normalized_level_db(a, floor_db=-300.0)
        b_db = normalized_level_db(b, floor_db=-300.0)
        row[f"{cut}_normalized_max_delta_db"] = float(np.max(np.abs(a_db - b_db)))
        row[f"{cut}_beamwidth_change_deg"] = abs(
            beamwidth_deg(angles_deg, a) - beamwidth_deg(angles_deg, b))
    return row


def write_csv(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_study(yaml_path: Path, mouth_csv: Path, frequency_hz: float,
              depths_mm: list[float], output_dir: Path, *,
              elements_per_wavelength: float = 6.0,
              direct_solve_max_dofs: int = 2_500) -> dict[str, object]:
    if len(depths_mm) < 2 or any(depth <= 0.0 for depth in depths_mm):
        raise ValueError("provide at least two positive retained depths")
    if any(b <= a for a, b in zip(depths_mm, depths_mm[1:])):
        raise ValueError("retained depths must be strictly increasing")
    output_dir.mkdir(parents=True, exist_ok=True)
    field = read_mfem_mouth_csv(mouth_csv, frequency_hz)
    angles = np.arange(-90.0, 91.0)
    results: list[LocalLipResult] = []
    depth_rows: list[dict[str, float]] = []
    depths_m = [depth * 1e-3 for depth in depths_mm]
    for depth_mm, depth_m in zip(depths_mm, depths_m):
        settings = LocalLipSettings(
            retained_depth_m=depth_m,
            elements_per_wavelength=elements_per_wavelength,
            direct_solve_max_dofs=direct_solve_max_dofs)
        lip = build_local_lip_mesh(yaml_path, frequency_hz, settings)
        result = solve_local_lip(field, lip, angles, settings)
        write_result(output_dir / f"depth_{depth_mm:g}mm", field, lip,
                     result, angles, settings)
        results.append(result)
        depth_rows.append(depth_metrics(depth_m, result, angles))
    adjacent = [adjacent_metrics(depths_m[i - 1], results[i - 1],
                                 depths_m[i], results[i], angles)
                for i in range(1, len(results))]
    write_csv(output_dir / "depth_metrics.csv", depth_rows)
    write_csv(output_dir / "adjacent_convergence.csv", adjacent)
    last = adjacent[-1]
    accepted = all(
        last[f"{cut}_complex_relative_l2"] <= COMPLEX_RELATIVE_L2_LIMIT
        and last[f"{cut}_normalized_max_delta_db"] <= NORMALIZED_MAX_DELTA_DB_LIMIT
        and last[f"{cut}_beamwidth_change_deg"] <= BEAMWIDTH_CHANGE_DEG_LIMIT
        for cut in CUTS)
    summary = {
        "status": "complete", "accepted": accepted,
        "frequency_hz": frequency_hz, "retained_depths_mm": depths_mm,
        "elements_per_wavelength": elements_per_wavelength,
        "depth_metrics": depth_rows, "adjacent_convergence": adjacent,
        "acceptance_limits": {
            "complex_relative_l2": COMPLEX_RELATIVE_L2_LIMIT,
            "normalized_max_delta_db": NORMALIZED_MAX_DELTA_DB_LIMIT,
            "beamwidth_change_deg": BEAMWIDTH_CHANGE_DEG_LIMIT,
        },
        "acceptance_note": ("Deepest adjacent pair passes provisional retained-depth gates."
                            if accepted else
                            "Deepest adjacent pair fails provisional retained-depth gates."),
    }
    (output_dir / "study.json").write_text(json.dumps(summary, indent=2) + "\n",
                                            encoding="utf-8")
    figure, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True,
                               constrained_layout=True)
    for axis, cut in zip(axes, CUTS):
        for depth_mm, result in zip(depths_mm, results):
            axis.plot(angles, normalized_level_db(result.total_pressure_pa[cut]),
                      label=f"{depth_mm:g} mm")
        axis.set(title=cut.title(), xlabel="Angle (degrees)", ylim=(-30, 2))
        axis.grid(True, alpha=0.25)
    axes[0].set_ylabel("Peak-normalized total pressure (dB)")
    axes[-1].legend()
    figure.suptitle(f"Local-lip retained-depth study at {frequency_hz:g} Hz")
    figure.savefig(output_dir / "retained_depth_comparison.png", dpi=180)
    plt.close(figure)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("mouth_csv", type=Path)
    parser.add_argument("frequency_hz", type=float)
    parser.add_argument("--depths-mm", nargs="+", type=float,
                        default=[25.0, 50.0, 100.0])
    parser.add_argument("--elements-per-wavelength", type=float, default=6.0)
    parser.add_argument("--direct-solve-max-dofs", type=int, default=2_500)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_study(args.yaml, args.mouth_csv, args.frequency_hz, args.depths_mm,
              args.output_dir,
              elements_per_wavelength=args.elements_per_wavelength,
              direct_solve_max_dofs=args.direct_solve_max_dofs)
    print(args.output_dir)


if __name__ == "__main__":
    main()
