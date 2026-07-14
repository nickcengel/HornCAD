"""Regenerate the review figures from the committed mesh and CSV."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import meshio
import numpy as np


ROOT = Path(__file__).resolve().parent
FIELD_ROOT = ROOT / "fields"


def response_figure() -> None:
    data = np.genfromtxt(ROOT / "sweep.csv", delimiter=",", names=True)
    figure, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    axes[0].plot(data["frequency_hz"], data["radiated_power_w"] / 1000, "o-")
    axes[0].set_ylabel("Radiated power (kW)\nfor 1 m³/s source")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(data["frequency_hz"], data["gmres_iterations"], "o-", label="iterations")
    axes[1].axhline(1000, color="tab:red", linestyle="--", label="iteration limit")
    axes[1].set(xlabel="Frequency (Hz)", ylabel="GMRES iterations")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    figure.suptitle("Resolved 3D interior/aperture proof — not convergence certified")
    figure.tight_layout()
    figure.savefig(ROOT / "figures" / "resolved_sweep.png", dpi=180)
    plt.close(figure)


def mesh_figure() -> None:
    mesh = meshio.read(ROOT / "artifacts" / "interior_5khz_6ppw.msh")
    triangles = next(block.data for block in mesh.cells if block.type == "triangle")
    tags = next(values for block, values in zip(mesh.cells, mesh.cell_data["gmsh:physical"])
                if block.type == "triangle")
    stride = max(1, len(triangles) // 12000)
    triangles, tags = triangles[::stride], tags[::stride]
    colors = np.array([[0.72, 0.74, 0.78, 0.28], [0.85, 0.20, 0.15, 0.9],
                       [0.15, 0.45, 0.85, 0.8]])
    collection = Poly3DCollection(mesh.points[triangles], facecolors=colors[tags - 1],
                                  edgecolors=(0.15, 0.15, 0.15, 0.08), linewidths=0.15)
    figure = plt.figure(figsize=(9, 6))
    axis = figure.add_subplot(111, projection="3d")
    axis.add_collection3d(collection)
    low, high = mesh.points.min(axis=0), mesh.points.max(axis=0)
    axis.set(xlim=(low[0], high[0]), ylim=(low[1], high[1]), zlim=(low[2], high[2]),
             xlabel="x (m)", ylabel="y (m)", zlabel="z (m)")
    axis.set_box_aspect(high - low)
    axis.view_init(elev=22, azim=-55)
    axis.set_title("Acoustic boundary: wall (gray), throat (red), mouth (blue)")
    figure.tight_layout()
    figure.savefig(ROOT / "figures" / "acoustic_mesh.png", dpi=180)
    plt.close(figure)


def _field_runs() -> list[tuple[float, np.ndarray, np.ndarray]]:
    runs = []
    for summary_path in sorted(FIELD_ROOT.glob("f*_summary.csv")):
        summary = np.genfromtxt(summary_path, delimiter=",", names=True)
        frequency = float(summary["frequency_hz"])
        prefix = summary_path.name.removesuffix("_summary.csv")
        mouth = np.genfromtxt(FIELD_ROOT / f"{prefix}_mouth.csv", delimiter=",", names=True)
        throat = np.genfromtxt(FIELD_ROOT / f"{prefix}_throat.csv", delimiter=",", names=True)
        runs.append((frequency, mouth, throat))
    return runs


def impedance_figure(runs: list[tuple[float, np.ndarray, np.ndarray]]) -> None:
    summaries = [np.genfromtxt(FIELD_ROOT / f"f{frequency:04.0f}_summary.csv",
                               delimiter=",", names=True) for frequency, _, _ in runs]
    frequencies = np.array([float(row["frequency_hz"]) for row in summaries])
    impedance = np.array([complex(float(row["input_impedance_real_pa_s_m3"]),
                                  float(row["input_impedance_imag_pa_s_m3"]))
                          for row in summaries])
    np.savetxt(ROOT / "impedance.csv",
               np.column_stack((frequencies, impedance.real, impedance.imag,
                                np.abs(impedance), np.angle(impedance, deg=True))),
               delimiter=",", header=("frequency_hz,resistance_pa_s_m3,reactance_pa_s_m3,"
                                       "magnitude_pa_s_m3,phase_deg"), comments="")
    figure, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    axes[0].plot(frequencies, impedance.real, "o-", label="resistance")
    axes[0].plot(frequencies, impedance.imag, "o-", label="reactance")
    axes[0].set_ylabel("Acoustic impedance (Pa·s/m³)")
    axes[0].legend()
    axes[1].plot(frequencies, np.abs(impedance), "o-", label="magnitude")
    phase_axis = axes[1].twinx()
    phase_axis.plot(frequencies, np.angle(impedance, deg=True), "s--", color="tab:orange")
    axes[1].set(xlabel="Frequency (Hz)", ylabel="Magnitude (Pa·s/m³)")
    phase_axis.set_ylabel("Phase (degrees)", color="tab:orange")
    for axis in axes:
        axis.grid(True, alpha=0.3)
    figure.suptitle("Acoustic throat input impedance for Q = 1 m³/s")
    figure.tight_layout()
    figure.savefig(ROOT / "figures" / "throat_impedance.png", dpi=180)
    plt.close(figure)


def mouth_field_figure(runs: list[tuple[float, np.ndarray, np.ndarray]]) -> None:
    selected = [runs[0], runs[len(runs) // 2], runs[-1]]
    figure, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    for column, (frequency, mouth, _) in enumerate(selected):
        pressure = mouth["pressure_real_pa"] + 1j * mouth["pressure_imag_pa"]
        velocity = (mouth["normal_velocity_real_m_s"]
                    + 1j * mouth["normal_velocity_imag_m_s"])
        pressure_plot = axes[0, column].scatter(mouth["x_m"], mouth["y_m"],
                                                c=20 * np.log10(np.maximum(
                                                    np.abs(pressure) / np.abs(pressure).max(),
                                                    1e-6)), s=5, vmin=-30, vmax=0)
        velocity_plot = axes[1, column].scatter(mouth["x_m"], mouth["y_m"],
                                                c=np.angle(velocity, deg=True), s=5,
                                                vmin=-180, vmax=180, cmap="twilight")
        axes[0, column].set_title(f"{frequency:.0f} Hz")
        for axis in axes[:, column]:
            axis.set_aspect("equal")
            axis.set(xlabel="x (m)", ylabel="y (m)")
    figure.colorbar(pressure_plot, ax=axes[0, :], label="Pressure magnitude (dB re local max)")
    figure.colorbar(velocity_plot, ax=axes[1, :], label="Normal-velocity phase (degrees)")
    figure.suptitle("Solved complex field over the curved computational mouth")
    figure.savefig(ROOT / "figures" / "mouth_fields.png", dpi=180)
    plt.close(figure)


def _ideal_coverage(mouth: np.ndarray, frequency: float, plane: str,
                    angles_deg: np.ndarray) -> np.ndarray:
    center = np.array([np.average(mouth[name], weights=mouth["area_weight_m2"])
                       for name in ("x_m", "y_m", "z_m")])
    angles = np.deg2rad(angles_deg)
    if plane == "horizontal":
        directions = np.column_stack((np.sin(angles), np.zeros_like(angles),
                                      np.cos(angles)))
    else:
        directions = np.column_stack((np.zeros_like(angles), np.sin(angles),
                                      np.cos(angles)))
    observers = center + 10.0 * directions
    sources = np.column_stack((mouth["x_m"], mouth["y_m"], mouth["z_m"]))
    velocity = (mouth["normal_velocity_real_m_s"]
                + 1j * mouth["normal_velocity_imag_m_s"])
    distance = np.linalg.norm(observers[:, None, :] - sources[None, :, :], axis=2)
    wave_number = 2.0 * np.pi * frequency / 343.21
    pressure = np.sum(velocity[None, :] * mouth["area_weight_m2"][None, :]
                      * np.exp(-1j * wave_number * distance) / distance, axis=1)
    level = 20.0 * np.log10(np.maximum(np.abs(pressure) / np.abs(pressure).max(), 1e-6))
    return np.maximum(level, -30.0)


def coverage_figure(runs: list[tuple[float, np.ndarray, np.ndarray]]) -> None:
    angles = np.linspace(-90.0, 90.0, 181)
    frequencies = np.array([frequency for frequency, _, _ in runs])
    horizontal = np.vstack([_ideal_coverage(mouth, frequency, "horizontal", angles)
                            for frequency, mouth, _ in runs])
    vertical = np.vstack([_ideal_coverage(mouth, frequency, "vertical", angles)
                          for frequency, mouth, _ in runs])
    figure, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, constrained_layout=True)
    for axis, values, title in zip(axes, (horizontal, vertical),
                                   ("Horizontal", "Vertical")):
        image = axis.pcolormesh(angles, frequencies, values, shading="nearest",
                                vmin=-30, vmax=0, cmap="turbo")
        axis.set(ylabel="Frequency (Hz)", title=title)
    axes[-1].set_xlabel("Off-axis angle (degrees)")
    figure.colorbar(image, ax=axes, label="Relative level (dB; normalized per frequency)")
    figure.suptitle("Preliminary ideal-aperture coverage — excludes lip diffraction")
    figure.savefig(ROOT / "figures" / "ideal_coverage_heatmaps.png", dpi=180)
    plt.close(figure)


if __name__ == "__main__":
    response_figure()
    mesh_figure()
    runs = _field_runs()
    if runs:
        impedance_figure(runs)
        mouth_field_figure(runs)
        coverage_figure(runs)
