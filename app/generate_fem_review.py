"""Generate standard review artifacts from a HornCAD MFEM field sweep."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np

try:
    from .aperture_field import (
        ApertureField,
        RADIATION_MODEL,
        TIME_CONVENTION,
        read_mfem_mouth_csv,
        rayleigh_baffle_plane_level,
    )
except ImportError:
    from aperture_field import (
        ApertureField,
        RADIATION_MODEL,
        TIME_CONVENTION,
        read_mfem_mouth_csv,
        rayleigh_baffle_plane_level,
    )


ANGLES = np.arange(-90.0, 91.0)
SOUND_SPEED = 343.21


def log_axis(axis: plt.Axes) -> None:
    axis.set_xscale("log")
    axis.set_xticks([500, 1000, 2000, 5000])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.grid(True, which="both", alpha=0.2)


def coverage(mouth: np.ndarray, frequency: float, plane: str) -> np.ndarray:
    """Compatibility wrapper for callers that already loaded a structured CSV."""
    field = ApertureField(
        frequency_hz=frequency,
        positions_m=np.column_stack([mouth[name] for name in ("x_m", "y_m", "z_m")]),
        area_weights_m2=mouth["area_weight_m2"],
        pressure_pa=mouth["pressure_real_pa"] + 1j * mouth["pressure_imag_pa"],
        normal_velocity_m_s=(mouth["normal_velocity_real_m_s"]
                             + 1j * mouth["normal_velocity_imag_m_s"]),
    )
    return rayleigh_baffle_plane_level(field, ANGLES, plane, sound_speed_m_s=SOUND_SPEED)


def positive_crossing(level: np.ndarray) -> float:
    zero = int(np.argmin(np.abs(ANGLES)))
    for index in range(zero, len(ANGLES) - 1):
        if level[index] >= -6.0 and level[index + 1] < -6.0:
            fraction = (-6.0 - level[index]) / (level[index + 1] - level[index])
            return float(ANGLES[index] + fraction * (ANGLES[index + 1] - ANGLES[index]))
    return 90.0


def generate_review(fields: Path, output_dir: Path, title: str) -> None:
    figures = output_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    frequencies, impedance, horizontal, vertical, rows = [], [], [], [], []
    summary_paths = sorted(fields.glob("d*_summary.csv"))
    if not summary_paths:
        raise ValueError(f"no d*_summary.csv files found in {fields}")
    for summary_path in summary_paths:
        stem = summary_path.name.removesuffix("_summary.csv")
        summary = np.genfromtxt(summary_path, delimiter=",", names=True)
        mouth_path = fields / f"{stem}_mouth.csv"
        if not mouth_path.is_file():
            raise FileNotFoundError(mouth_path)
        frequency = float(summary["frequency_hz"])
        mouth = read_mfem_mouth_csv(mouth_path, frequency)
        value = complex(float(summary["input_impedance_real_pa_s_m3"]),
                        float(summary["input_impedance_imag_pa_s_m3"]))
        h_level = rayleigh_baffle_plane_level(mouth, ANGLES, "horizontal",
                                              sound_speed_m_s=SOUND_SPEED)
        v_level = rayleigh_baffle_plane_level(mouth, ANGLES, "vertical",
                                              sound_speed_m_s=SOUND_SPEED)
        frequencies.append(frequency)
        impedance.append(value)
        horizontal.append(h_level)
        vertical.append(v_level)
        rows.append({
            "frequency_hz": frequency,
            "impedance_magnitude_pa_s_m3": abs(value),
            "horizontal_6db_half_angle_deg": positive_crossing(h_level),
            "vertical_6db_half_angle_deg": positive_crossing(v_level),
            "radiated_power_w": float(summary["radiated_power_w"]),
            "gmres_iterations": int(summary["gmres_iterations"]),
            "solve_seconds": float(summary["solve_seconds"]),
            "relative_residual": float(summary["relative_residual"]),
        })
    frequencies = np.asarray(frequencies)
    impedance = np.asarray(impedance)
    horizontal = np.asarray(horizontal)
    vertical = np.asarray(vertical)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_dir / "responses.npz", frequencies_hz=frequencies,
                        angles_deg=ANGLES, horizontal_db=horizontal,
                        vertical_db=vertical, impedance=impedance,
                        radiation_model=RADIATION_MODEL,
                        time_convention=TIME_CONVENTION,
                        receiver_radius_m=10.0,
                        normalization="peak_per_frequency")
    with (output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    figure, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True, constrained_layout=True)
    image = None
    for axis, values, plane_title in zip(axes, (horizontal, vertical), ("Horizontal", "Vertical")):
        image = axis.pcolormesh(frequencies, ANGLES, values.T, shading="nearest",
                                vmin=-30.0, vmax=0.0, cmap="turbo")
        axis.contour(frequencies, ANGLES, values.T, levels=[-6.0],
                     colors="white", linewidths=1.5)
        axis.set_title(plane_title)
        axis.set_xlabel("Frequency (Hz, log scale)")
        axis.set_yticks(np.arange(-90, 91, 15))
        log_axis(axis)
    axes[0].set_ylabel("Off-axis angle (degrees)")
    figure.colorbar(image, ax=axes, label="Relative level (dB)")
    figure.suptitle(f"{title} — Rayleigh infinite-planar-baffle reference")
    figure.savefig(figures / "coverage_heatmaps.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 5), constrained_layout=True)
    axis.plot(frequencies, np.abs(impedance), linewidth=1.8)
    axis.set(xlabel="Frequency (Hz, log scale)", ylabel="Magnitude (Pa·s/m³)",
             title="Throat acoustic impedance magnitude")
    log_axis(axis)
    figure.savefig(figures / "throat_impedance_magnitude.png", dpi=180)
    plt.close(figure)

    figure, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True, constrained_layout=True)
    axes[0].plot(frequencies, [row["gmres_iterations"] for row in rows])
    axes[0].set_ylabel("GMRES iterations")
    axes[1].plot(frequencies, [row["solve_seconds"] for row in rows])
    axes[1].set(xlabel="Frequency (Hz, log scale)", ylabel="Solve time (seconds)")
    for axis in axes:
        log_axis(axis)
    figure.suptitle("FEM solver performance")
    figure.savefig(figures / "solver_performance.png", dpi=180)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fields", type=Path, help="Directory containing dNNN field CSV files")
    parser.add_argument("--output-dir", type=Path,
                        help="Review output directory; defaults to the field directory parent")
    parser.add_argument("--title", default="Interior FEM",
                        help="Title prefix used on the coverage figure")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or args.fields.parent
    generate_review(args.fields, output_dir, args.title)


if __name__ == "__main__":
    main()
