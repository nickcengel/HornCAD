"""Consolidate the dense MFEM sweep and compare it with simpler HornCAD models."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
from aperture_directivity import mouth_aperture_samples, normalized_plane_directivity
from webster_1d import Medium, horncad_area_profile, solve_sweep

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "figures"
SOURCE_YAML = ROOT / "test_project" / "HornCAD-Body-400x260x250.YAML"
FLOOR_DB = -30.0


def set_frequency_axis(axis: plt.Axes) -> None:
    axis.set_xscale("log")
    axis.set_xlim(500.0, 5000.0)
    axis.set_xticks([500.0, 1000.0, 2000.0, 5000.0])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.grid(True, which="both", alpha=0.22)


def load_dense(source: Path) -> dict[str, np.ndarray]:
    summaries = []
    pressures, velocities = [], []
    points = weights = None
    for summary_path in sorted(source.glob("d???_summary.csv")):
        prefix = summary_path.name.removesuffix("_summary.csv")
        summary = np.genfromtxt(summary_path, delimiter=",", names=True)
        mouth = np.genfromtxt(source / f"{prefix}_mouth.csv", delimiter=",", names=True)
        if points is None:
            points = np.column_stack((mouth["x_m"], mouth["y_m"], mouth["z_m"]))
            weights = np.asarray(mouth["area_weight_m2"])
        elif not np.allclose(points, np.column_stack((mouth["x_m"], mouth["y_m"],
                                                      mouth["z_m"])), atol=1e-13):
            raise ValueError(f"mouth point ordering changed in {prefix}")
        pressures.append(mouth["pressure_real_pa"] + 1j * mouth["pressure_imag_pa"])
        velocities.append(mouth["normal_velocity_real_m_s"]
                          + 1j * mouth["normal_velocity_imag_m_s"])
        summaries.append(summary)
    if len(summaries) != 81:
        raise ValueError(f"expected 81 dense results, found {len(summaries)}")
    fields = {
        "frequency_hz": np.array([float(row["frequency_hz"]) for row in summaries]),
        "input_impedance_pa_s_m3": np.array([
            complex(float(row["input_impedance_real_pa_s_m3"]),
                    float(row["input_impedance_imag_pa_s_m3"])) for row in summaries]),
        "radiated_power_w": np.array([float(row["radiated_power_w"]) for row in summaries]),
        "gmres_iterations": np.array([int(row["gmres_iterations"]) for row in summaries]),
        "solve_seconds": np.array([float(row["solve_seconds"]) for row in summaries]),
        "relative_residual": np.array([float(row["relative_residual"]) for row in summaries]),
        "mouth_points_m": points,
        "mouth_area_weight_m2": weights,
        "mouth_pressure_pa": np.asarray(pressures),
        "mouth_normal_velocity_m_s": np.asarray(velocities),
    }
    if not np.all(np.diff(fields["frequency_hz"]) > 0.0):
        raise ValueError("dense frequencies are not strictly increasing")
    return fields


def coverage(points: np.ndarray, weights: np.ndarray, velocity: np.ndarray,
             frequencies: np.ndarray, angles: np.ndarray, plane: str) -> np.ndarray:
    center = np.average(points, axis=0, weights=weights)
    radians = np.radians(angles)
    if plane == "horizontal":
        directions = np.column_stack((np.sin(radians), np.zeros_like(radians),
                                      np.cos(radians)))
    else:
        directions = np.column_stack((np.zeros_like(radians), np.sin(radians),
                                      np.cos(radians)))
    observers = center + 10.0 * directions
    distance = np.linalg.norm(observers[:, None, :] - points[None, :, :], axis=2)
    result = np.empty((len(angles), len(frequencies)))
    for column, frequency in enumerate(frequencies):
        wave_number = 2.0 * np.pi * frequency / Medium.sound_speed_m_s
        pressure = np.sum(velocity[column][None, :] * weights[None, :]
                          * np.exp(-1j * wave_number * distance) / distance, axis=1)
        db = 20.0 * np.log10(np.maximum(np.abs(pressure) / np.max(np.abs(pressure)), 1e-9))
        result[:, column] = np.maximum(db, FLOOR_DB)
    return result


def symmetric_baseline(values: np.ndarray) -> np.ndarray:
    """Mirror a 0..90 matrix into -90..90 without duplicating zero."""
    return np.vstack((values[:0:-1], values))


def crossing(angle: np.ndarray, level: np.ndarray, start: int, step: int) -> float:
    index = start
    while 0 <= index + step < len(angle) and level[index + step] >= -6.0:
        index += step
    other = index + step
    if other < 0 or other >= len(angle):
        return float(angle[index])
    x0, x1 = float(angle[index]), float(angle[other])
    y0, y1 = float(level[index]), float(level[other])
    if y0 == y1:
        return x0
    return x0 + (-6.0 - y0) * (x1 - x0) / (y1 - y0)


def beamwidth(angles: np.ndarray, values: np.ndarray) -> np.ndarray:
    zero = int(np.argmin(np.abs(angles)))
    return np.array([crossing(angles, values[:, column], zero, 1)
                     - crossing(angles, values[:, column], zero, -1)
                     for column in range(values.shape[1])])


def write_summary(path: Path, dense: dict[str, np.ndarray], webster: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("frequency_hz", "fem_resistance_pa_s_m3", "fem_reactance_pa_s_m3",
                         "fem_magnitude_pa_s_m3", "webster_resistance_pa_s_m3",
                         "webster_reactance_pa_s_m3", "webster_magnitude_pa_s_m3",
                         "fem_radiated_power_w", "webster_radiated_power_w",
                         "gmres_iterations", "solve_seconds", "relative_residual"))
        for index, result in enumerate(webster):
            fem_z = dense["input_impedance_pa_s_m3"][index]
            webster_z = result.input_impedance_pa_s_m3
            writer.writerow((dense["frequency_hz"][index], fem_z.real, fem_z.imag, abs(fem_z),
                             webster_z.real, webster_z.imag, abs(webster_z),
                             dense["radiated_power_w"][index],
                             result.radiated_power_w_per_m3_s_sq,
                             dense["gmres_iterations"][index], dense["solve_seconds"][index],
                             dense["relative_residual"][index]))


def coverage_plot(frequencies: np.ndarray, angles: np.ndarray, matrices: list[np.ndarray],
                  path: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 10), sharex=True, sharey=True,
                                constrained_layout=True)
    titles = ("3D FEM mouth field — horizontal", "Uniform aperture — horizontal",
              "3D FEM mouth field — vertical", "Uniform aperture — vertical")
    image = None
    for axis, values, title in zip(axes.flat, matrices, titles):
        image = axis.pcolormesh(frequencies, angles, values, shading="nearest",
                                vmin=FLOOR_DB, vmax=0.0, cmap="turbo")
        contour = axis.contour(frequencies, angles, values, levels=[-6.0],
                               colors="white", linewidths=1.3)
        axis.clabel(contour, fmt={-6.0: "−6 dB"}, fontsize=8)
        set_frequency_axis(axis)
        axis.set_yticks(np.arange(-90, 91, 15))
        axis.set_title(title)
    axes[1, 0].set_xlabel("Frequency (Hz, log scale)")
    axes[1, 1].set_xlabel("Frequency (Hz, log scale)")
    axes[0, 0].set_ylabel("Off-axis angle (degrees)")
    axes[1, 0].set_ylabel("Off-axis angle (degrees)")
    figure.colorbar(image, ax=axes, label="Level relative to peak at each frequency (dB)")
    figure.suptitle("Dense 500 Hz–5 kHz coverage comparison (ideal-baffle radiation)")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def impedance_plot(frequencies: np.ndarray, fem_z: np.ndarray, webster_z: np.ndarray,
                   fem_z0: float, webster_z0: float, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    for impedance, z0, label, style in ((fem_z, fem_z0, "3D FEM + nonlocal aperture", "-"),
                                        (webster_z, webster_z0, "Webster 1D + piston load", "--")):
        normalized = impedance / z0
        axis.plot(frequencies, np.abs(normalized), style, linewidth=2.0, label=label)
    axis.set_ylabel("Impedance magnitude |Z/Z₀|")
    axis.set_xlabel("Frequency (Hz, log scale)")
    set_frequency_axis(axis)
    axis.legend()
    axis.set_title("Throat acoustic input impedance magnitude")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def metrics_plot(frequencies: np.ndarray, dense: dict[str, np.ndarray], coherence: np.ndarray,
                 widths: tuple[np.ndarray, ...], path: Path) -> None:
    fem_h, base_h, fem_v, base_v = widths
    figure, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True, constrained_layout=True)
    axes[0].plot(frequencies, fem_h, label="3D H")
    axes[0].plot(frequencies, base_h, "--", label="uniform aperture H")
    axes[0].plot(frequencies, fem_v, label="3D V")
    axes[0].plot(frequencies, base_v, "--", label="uniform aperture V")
    axes[0].set_ylabel("−6 dB beamwidth (degrees)")
    axes[0].set_ylim(0, 180)
    axes[0].legend(ncol=2)
    axes[1].plot(frequencies, coherence)
    axes[1].set_ylabel("Mouth velocity coherence")
    axes[1].set_ylim(0, 1.05)
    axes[2].plot(frequencies, dense["gmres_iterations"], label="iterations")
    time_axis = axes[2].twinx()
    time_axis.plot(frequencies, dense["solve_seconds"], color="tab:orange", label="solve time")
    axes[2].set_ylabel("GMRES iterations")
    time_axis.set_ylabel("Solve time (seconds)", color="tab:orange")
    axes[2].set_xlabel("Frequency (Hz, log scale)")
    for axis in axes:
        set_frequency_axis(axis)
    figure.suptitle("Coverage, mouth-field, and solver metrics")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_comparison.py DENSE_FIELD_DIRECTORY")
    dense = load_dense(Path(sys.argv[1]))
    frequencies = dense["frequency_hz"]
    angles = np.arange(-90.0, 91.0, 1.0)
    angles_positive = np.arange(0.0, 91.0, 1.0)

    profile = horncad_area_profile(SOURCE_YAML, 401)
    webster = solve_sweep(profile, frequencies, Medium(), "baffled_piston")
    x_m, y_m, z_m = mouth_aperture_samples(SOURCE_YAML)
    baseline_h = symmetric_baseline(normalized_plane_directivity(
        x_m, z_m, frequencies, angles_positive, Medium.sound_speed_m_s, FLOOR_DB))
    baseline_v = symmetric_baseline(normalized_plane_directivity(
        y_m, z_m, frequencies, angles_positive, Medium.sound_speed_m_s, FLOOR_DB))
    fem_h = coverage(dense["mouth_points_m"], dense["mouth_area_weight_m2"],
                     dense["mouth_normal_velocity_m_s"], frequencies, angles, "horizontal")
    fem_v = coverage(dense["mouth_points_m"], dense["mouth_area_weight_m2"],
                     dense["mouth_normal_velocity_m_s"], frequencies, angles, "vertical")
    weights = dense["mouth_area_weight_m2"]
    velocity = dense["mouth_normal_velocity_m_s"]
    coherence = np.abs(np.sum(velocity * weights[None, :], axis=1)) / np.sum(
        np.abs(velocity) * weights[None, :], axis=1)
    widths = (beamwidth(angles, fem_h), beamwidth(angles, baseline_h),
              beamwidth(angles, fem_v), beamwidth(angles, baseline_v))

    FIGURES.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(HERE / "dense_fields.npz", **dense)
    np.savez_compressed(HERE / "coverage_data.npz", frequency_hz=frequencies,
                        angle_deg=angles, fem_horizontal_db=fem_h, fem_vertical_db=fem_v,
                        uniform_horizontal_db=baseline_h, uniform_vertical_db=baseline_v,
                        fem_horizontal_beamwidth_deg=widths[0],
                        uniform_horizontal_beamwidth_deg=widths[1],
                        fem_vertical_beamwidth_deg=widths[2],
                        uniform_vertical_beamwidth_deg=widths[3],
                        mouth_velocity_coherence=coherence)
    write_summary(HERE / "response_comparison.csv", dense, webster)
    webster_z = np.array([result.input_impedance_pa_s_m3 for result in webster])
    fem_z0 = Medium.density_kg_m3 * Medium.sound_speed_m_s / 0.000500634
    webster_z0 = Medium.density_kg_m3 * Medium.sound_speed_m_s / profile.areas_m2[0]
    impedance_plot(frequencies, dense["input_impedance_pa_s_m3"], webster_z,
                   fem_z0, webster_z0, FIGURES / "impedance_comparison.png")
    coverage_plot(frequencies, angles, [fem_h, baseline_h, fem_v, baseline_v],
                  FIGURES / "coverage_comparison.png")
    metrics_plot(frequencies, dense, coherence, widths, FIGURES / "metrics.png")
    manifest = {
        "status": "dense_comparison_not_mesh_convergence_certified",
        "frequency_range_hz": [float(frequencies[0]), float(frequencies[-1])],
        "frequency_count": len(frequencies),
        "spacing": "logarithmic",
        "models": {
            "primary": "3D interior FEM with nonlocal infinite-baffle aperture operator",
            "impedance_baseline": "lossless Webster 1D with baffled-piston mouth load",
            "coverage_baseline": "uniform-velocity curved aperture in an ideal baffle",
        },
        "limitations": [
            "The 3D result uses only the accepted 6-elements-per-wavelength mesh.",
            "Coverage propagation is ideal-baffle radiation and excludes lip diffraction.",
            "The baseline models intentionally omit the solved nonuniform mouth field.",
        ],
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                         encoding="utf-8")


if __name__ == "__main__":
    main()
