"""Create, mesh, solve, and plot the eight OSSE FEM intuition candidates."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np
import yaml
from scipy.signal import savgol_filter


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
APP = REPO / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from acoustic_domain import build_quadrant_acoustic_domain, write_tetwild_volume_mesh


BASE_CONFIG = REPO / "test_project" / "HornCAD-Body-400x260x250.YAML"
BINARY = Path("/private/tmp/horncad-mfem-build/horncad_mfem_interior")
SOUND_SPEED = 343.21
MAX_FREQUENCY = 5000.0
ELEMENTS_PER_WAVELENGTH = 8.0
MAXIMUM_EDGE_M = SOUND_SPEED / MAX_FREQUENCY / ELEMENTS_PER_WAVELENGTH
TETWILD_EDGE_FACTOR = 0.46
FREQUENCIES = np.geomspace(500.0, 5000.0, 64)
ANGLES = np.arange(-90.0, 91.0)

CANDIDATES = (
    {"id": 1, "coverage": 45.0, "k": 17.0, "n": 2.0, "length": 300.0, "extension": 0.0},
    {"id": 2, "coverage": 45.0, "k": 25.0, "n": 2.0, "length": 300.0, "extension": 0.0},
    {"id": 3, "coverage": 45.0, "k": 25.0, "n": 25.0, "length": 300.0, "extension": 0.0},
    {"id": 4, "coverage": 45.0, "k": 6.0, "n": 2.0, "length": 240.0, "extension": 60.0},
    {"id": 5, "coverage": 45.0, "k": 25.0, "n": 2.0, "length": 240.0, "extension": 60.0},
    {"id": 6, "coverage": 45.0, "k": 25.0, "n": 25.0, "length": 240.0, "extension": 60.0},
    {"id": 7, "coverage": 24.0, "k": 1.0, "n": 2.0, "length": 300.0, "extension": 0.0},
    {"id": 8, "coverage": 24.0, "k": 1.0, "n": 25.0, "length": 300.0, "extension": 0.0},
)


def candidate_dir(candidate: dict) -> Path:
    return ROOT / f"candidate_{candidate['id']}"


def candidate_label(candidate: dict) -> str:
    extension = f", E={candidate['extension']:g}" if candidate["extension"] else ""
    return f"{candidate['id']}: K={candidate['k']:g}, N={candidate['n']:g}{extension}"


def config_path(candidate: dict) -> Path:
    return candidate_dir(candidate) / "horn.yaml"


def mesh_path(candidate: dict) -> Path:
    return candidate_dir(candidate) / "mesh" / "interior_quadrant_5khz_8ppw.msh"


def make_config(candidate: dict) -> dict:
    source = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
    config = copy.deepcopy(source["horncad_config"])
    global_config = config["global"]
    global_config.update({
        "length": candidate["length"],
        "throat_radius": 12.7,
        "throat_angle_deg": 6.0,
        "conical_extension_length": candidate["extension"],
        "effective_throat_radius": 12.7 + candidate["extension"] * math.tan(math.radians(6.0)),
        "measured_total_length": candidate["length"] + candidate["extension"],
        "mouth_width": 400.0,
        "mouth_height": 400.0,
        "mouth_sag": 60.0,
        "mouth_sag_h_enabled": True,
        "mouth_sag_v_enabled": True,
    })
    for key in ("horizontal_basis", "vertical_basis"):
        config[key].update({
            "coverage_deg": candidate["coverage"],
            "k": candidate["k"],
            "n": candidate["n"],
        })
        config[key].pop("solved_s", None)
    config["body"]["stl_export_mode"] = "surface"
    return {"horncad_config": config}


def setup() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for candidate in CANDIDATES:
        directory = candidate_dir(candidate)
        (directory / "mesh").mkdir(parents=True, exist_ok=True)
        (directory / "fields").mkdir(exist_ok=True)
        (directory / "figures").mkdir(exist_ok=True)
        config_path(candidate).write_text(
            yaml.safe_dump(make_config(candidate), sort_keys=False), encoding="utf-8")
    np.savetxt(ROOT / "frequencies.csv", FREQUENCIES, delimiter=",",
               header="frequency_hz", comments="")


def mesh_one(candidate: dict) -> dict:
    path = mesh_path(candidate)
    if path.exists():
        return {"candidate": candidate["id"], "status": "already complete"}
    started = time.monotonic()
    domain = build_quadrant_acoustic_domain(config_path(candidate), 32, 44)
    diagonal = float(np.linalg.norm(np.ptp(domain.surface.bounds, axis=0)))
    report = write_tetwild_volume_mesh(
        domain, path, MAXIMUM_EDGE_M, threads=20,
        edge_length_ratio=TETWILD_EDGE_FACTOR * MAXIMUM_EDGE_M / diagonal)
    result = {
        "candidate": candidate["id"],
        "status": "complete",
        "seconds": time.monotonic() - started,
        "nodes": report.nodes,
        "tetrahedra": report.tetrahedra,
        "maximum_edge_m": report.maximum_tetrahedron_edge_m,
        "maximum_surface_deviation_m": report.maximum_label_match_error_m,
    }
    (candidate_dir(candidate) / "mesh" / "report.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def mesh_all(workers: int) -> None:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {executor.submit(mesh_one, candidate): candidate for candidate in CANDIDATES}
        for future in as_completed(jobs):
            print(json.dumps(future.result()), flush=True)


def solve_one(candidate: dict, index: int, frequency: float) -> str:
    prefix = candidate_dir(candidate) / "fields" / f"d{index:03d}"
    summary = Path(f"{prefix}_summary.csv")
    if summary.exists():
        return "already complete"
    command = [str(BINARY), str(mesh_path(candidate)), f"{frequency:.17g}",
               "--output-prefix", str(prefix), "--quadrant-symmetry"]
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.stdout.strip().splitlines()[-1]


def solve_all(workers: int) -> None:
    if not BINARY.is_file():
        raise FileNotFoundError(BINARY)
    missing_mesh = [str(mesh_path(candidate)) for candidate in CANDIDATES
                    if not mesh_path(candidate).is_file()]
    if missing_mesh:
        raise FileNotFoundError(f"missing meshes: {missing_mesh}")
    jobs = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for candidate in CANDIDATES:
            for index, frequency in enumerate(FREQUENCIES):
                jobs.append((candidate, index, frequency,
                             executor.submit(solve_one, candidate, index, float(frequency))))
        for done, (candidate, index, frequency, future) in enumerate(jobs, start=1):
            print(f"[{done}/{len(jobs)}] candidate {candidate['id']} "
                  f"{frequency:.2f} Hz: {future.result()}", flush=True)


def load_run(candidate: dict, index: int) -> tuple[float, np.void, np.ndarray]:
    prefix = candidate_dir(candidate) / "fields" / f"d{index:03d}"
    summary = np.genfromtxt(f"{prefix}_summary.csv", delimiter=",", names=True)
    mouth = np.genfromtxt(f"{prefix}_mouth.csv", delimiter=",", names=True)
    return float(summary["frequency_hz"]), summary, mouth


def coverage(mouth: np.ndarray, frequency: float, plane: str) -> np.ndarray:
    weights = mouth["area_weight_m2"]
    points = np.column_stack([mouth[name] for name in ("x_m", "y_m", "z_m")])
    center = np.average(points, axis=0, weights=weights)
    radians = np.radians(ANGLES)
    if plane == "horizontal":
        directions = np.column_stack((np.sin(radians), np.zeros_like(radians),
                                      np.cos(radians)))
    else:
        directions = np.column_stack((np.zeros_like(radians), np.sin(radians),
                                      np.cos(radians)))
    observers = center + 10.0 * directions
    distance = np.linalg.norm(observers[:, None, :] - points[None, :, :], axis=2)
    velocity = mouth["normal_velocity_real_m_s"] + 1j * mouth["normal_velocity_imag_m_s"]
    pressure = np.sum(velocity[None, :] * weights[None, :]
                      * np.exp(-1j * 2.0 * np.pi * frequency / SOUND_SPEED * distance)
                      / distance, axis=1)
    level = 20.0 * np.log10(np.maximum(np.abs(pressure) / np.max(np.abs(pressure)), 1e-9))
    return np.maximum(level, -30.0)


def positive_crossing(level: np.ndarray) -> float:
    center = int(np.argmin(np.abs(ANGLES)))
    for index in range(center, len(ANGLES) - 1):
        if level[index] >= -6.0 and level[index + 1] < -6.0:
            fraction = (-6.0 - level[index]) / (level[index + 1] - level[index])
            return float(ANGLES[index] + fraction * (ANGLES[index + 1] - ANGLES[index]))
    return 90.0


def log_axis(axis: plt.Axes) -> None:
    axis.set_xscale("log")
    axis.set_xticks([500, 1000, 2000, 5000])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.grid(True, which="both", alpha=0.2)


def plot_candidate(candidate: dict, horizontal: np.ndarray, vertical: np.ndarray,
                   impedance: np.ndarray) -> None:
    figures = candidate_dir(candidate) / "figures"
    figure, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True, constrained_layout=True)
    image = None
    for axis, values, title in zip(axes, (horizontal, vertical), ("Horizontal", "Vertical")):
        image = axis.pcolormesh(FREQUENCIES, ANGLES, values.T, shading="nearest",
                                vmin=-30.0, vmax=0.0, cmap="turbo")
        axis.contour(FREQUENCIES, ANGLES, values.T, levels=[-6.0],
                     colors="white", linewidths=1.5)
        axis.set_title(title)
        axis.set_xlabel("Frequency (Hz, log scale)")
        axis.set_yticks(np.arange(-90, 91, 15))
        log_axis(axis)
    axes[0].set_ylabel("Off-axis angle (degrees)")
    figure.colorbar(image, ax=axes, label="Relative level (dB)")
    figure.suptitle(f"Candidate {candidate['id']} ideal-baffle FEM coverage")
    figure.savefig(figures / "coverage_heatmaps.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 5), constrained_layout=True)
    axis.plot(FREQUENCIES, np.abs(impedance), linewidth=1.8)
    axis.set(xlabel="Frequency (Hz, log scale)", ylabel="Magnitude (Pa·s/m³)",
             title=f"Candidate {candidate['id']} throat acoustic impedance")
    log_axis(axis)
    figure.savefig(figures / "throat_impedance_magnitude.png", dpi=180)
    plt.close(figure)


def plot_group(candidates: tuple[dict, ...], stem: str, results: dict) -> None:
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    for candidate in candidates:
        half_angle = np.array([positive_crossing(row) for row in results[candidate["id"]]["h"]])
        axis.plot(FREQUENCIES, half_angle, linewidth=1.7, label=candidate_label(candidate))
    axis.set(xlabel="Frequency (Hz, log scale)", ylabel="−6 dB off-axis angle (degrees)",
             title=f"Candidates {candidates[0]['id']}–{candidates[-1]['id']} coverage comparison")
    axis.set_yticks(np.arange(0, 91, 15))
    axis.set_ylim(0, 90)
    log_axis(axis)
    axis.legend(ncol=2)
    figure.savefig(ROOT / f"{stem}_coverage_comparison.png", dpi=180)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    for candidate in candidates:
        axis.plot(FREQUENCIES, np.abs(results[candidate["id"]]["z"]),
                  linewidth=1.7, label=candidate_label(candidate))
    axis.set(xlabel="Frequency (Hz, log scale)", ylabel="Magnitude (Pa·s/m³)",
             title=f"Candidates {candidates[0]['id']}–{candidates[-1]['id']} throat impedance")
    log_axis(axis)
    axis.legend(ncol=2)
    figure.savefig(ROOT / f"{stem}_impedance_comparison.png", dpi=180)
    plt.close(figure)


def plot_smoothed_coverage_comparison(candidates: tuple[dict, ...], results: dict) -> None:
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    for candidate in candidates:
        half_angle = np.array([positive_crossing(row) for row in results[candidate["id"]]["h"]])
        smoothed = savgol_filter(half_angle, window_length=7, polyorder=2, mode="interp")
        axis.plot(FREQUENCIES, smoothed, linewidth=2.1, label=candidate_label(candidate))
    axis.set(xlabel="Frequency (Hz, log scale)", ylabel="−6 dB off-axis angle (degrees)",
             title="Candidates 2, 3, and 5 coverage trends (light smoothing)")
    axis.set_yticks(np.arange(0, 91, 15))
    axis.set_ylim(0, 90)
    log_axis(axis)
    axis.legend()
    figure.savefig(ROOT / "candidates_2_3_5_coverage_smoothed.png", dpi=180)
    plt.close(figure)


def plot_all() -> None:
    results = {}
    metric_rows = []
    for candidate in CANDIDATES:
        horizontal, vertical, impedance = [], [], []
        for index in range(len(FREQUENCIES)):
            frequency, summary, mouth = load_run(candidate, index)
            horizontal.append(coverage(mouth, frequency, "horizontal"))
            vertical.append(coverage(mouth, frequency, "vertical"))
            value = complex(float(summary["input_impedance_real_pa_s_m3"]),
                            float(summary["input_impedance_imag_pa_s_m3"]))
            impedance.append(value)
            metric_rows.append({
                "candidate": candidate["id"], "frequency_hz": frequency,
                "impedance_magnitude_pa_s_m3": abs(value),
                "horizontal_6db_half_angle_deg": positive_crossing(horizontal[-1]),
                "vertical_6db_half_angle_deg": positive_crossing(vertical[-1]),
                "gmres_iterations": int(summary["gmres_iterations"]),
                "solve_seconds": float(summary["solve_seconds"]),
                "relative_residual": float(summary["relative_residual"]),
            })
        result = {"h": np.asarray(horizontal), "v": np.asarray(vertical),
                  "z": np.asarray(impedance)}
        results[candidate["id"]] = result
        np.savez_compressed(candidate_dir(candidate) / "responses.npz",
                            frequencies_hz=FREQUENCIES, angles_deg=ANGLES,
                            horizontal_db=result["h"], vertical_db=result["v"],
                            impedance=result["z"])
        plot_candidate(candidate, result["h"], result["v"], result["z"])

    with (ROOT / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metric_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(metric_rows)
    plot_group(CANDIDATES[:6], "candidates_1_6", results)
    plot_group(CANDIDATES[6:], "candidates_7_8", results)
    plot_smoothed_coverage_comparison(
        (CANDIDATES[1], CANDIDATES[2], CANDIDATES[4]), results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("setup", "mesh", "solve", "plot", "all"))
    parser.add_argument("--mesh-workers", type=int, default=1)
    parser.add_argument("--solve-workers", type=int, default=10)
    args = parser.parse_args()
    if args.stage in ("setup", "all"):
        setup()
    if args.stage in ("mesh", "all"):
        mesh_all(args.mesh_workers)
    if args.stage in ("solve", "all"):
        solve_all(args.solve_workers)
    if args.stage in ("plot", "all"):
        plot_all()


if __name__ == "__main__":
    main()
