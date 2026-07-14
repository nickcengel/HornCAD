"""Compare matching MFEM mesh-resolution results and generate convergence plots."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np


ROOT = Path(__file__).resolve().parent
FIELDS = ROOT / "quadrant_fields"
FIGURES = ROOT / "figures"
ANGLES = np.arange(-90.0, 91.0)
FLOOR_DB = -30.0


def log_axis(axis: plt.Axes) -> None:
    axis.set_xscale("log")
    axis.set_xticks([500, 1000, 2000, 5000])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.grid(True, which="both", alpha=0.22)


def load(label: str, frequency: float) -> tuple[np.void, np.ndarray]:
    prefix = FIELDS / f"{label}_f{frequency:04.0f}"
    summary = np.genfromtxt(f"{prefix}_summary.csv", delimiter=",", names=True)
    mouth = np.genfromtxt(f"{prefix}_mouth.csv", delimiter=",", names=True)
    return summary, mouth


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
    distance = np.linalg.norm(center + 10.0 * directions[:, None, :] - points[None, :, :],
                              axis=2)
    velocity = mouth["normal_velocity_real_m_s"] + 1j * mouth["normal_velocity_imag_m_s"]
    pressure = np.sum(velocity[None, :] * weights[None, :]
                      * np.exp(-1j * 2.0 * np.pi * frequency / 343.21 * distance)
                      / distance, axis=1)
    level = 20.0 * np.log10(np.maximum(np.abs(pressure) / np.max(np.abs(pressure)), 1e-9))
    return np.maximum(level, FLOOR_DB)


def crossing(angle: np.ndarray, level: np.ndarray, start: int, step: int) -> float:
    index = start
    while 0 <= index + step < len(angle) and level[index + step] >= -6.0:
        index += step
    other = index + step
    if not 0 <= other < len(angle):
        return float(angle[index])
    return float(angle[index] + (-6.0 - level[index])
                 * (angle[other] - angle[index]) / (level[other] - level[index]))


def beam_metrics(level: np.ndarray) -> tuple[float, float, float]:
    zero = int(np.argmin(np.abs(ANGLES)))
    width = crossing(ANGLES, level, zero, 1) - crossing(ANGLES, level, zero, -1)
    positive = level[zero:]
    minima = np.flatnonzero((positive[1:-1] < positive[:-2])
                            & (positive[1:-1] <= positive[2:])) + 1
    if not len(minima):
        return width, float("nan"), float("nan")
    first_null = int(minima[0])
    sidelobe = float(np.max(positive[first_null + 1:])) if first_null + 1 < len(positive) else np.nan
    return width, float(ANGLES[zero + first_null]), sidelobe


def field_metrics(mouth: np.ndarray) -> tuple[float, float, float, float]:
    weights = mouth["area_weight_m2"]
    pressure = mouth["pressure_real_pa"] + 1j * mouth["pressure_imag_pa"]
    velocity = mouth["normal_velocity_real_m_s"] + 1j * mouth["normal_velocity_imag_m_s"]
    area = np.sum(weights)
    pressure_rms = np.sqrt(np.sum(weights * np.abs(pressure) ** 2) / area)
    velocity_rms = np.sqrt(np.sum(weights * np.abs(velocity) ** 2) / area)
    pressure_coherence = abs(np.sum(weights * pressure)) / np.sum(weights * np.abs(pressure))
    velocity_coherence = abs(np.sum(weights * velocity)) / np.sum(weights * np.abs(velocity))
    return pressure_rms, velocity_rms, pressure_coherence, velocity_coherence


def main() -> None:
    labels = ("6ppw", "8ppw", "10ppw")
    frequencies = []
    for path in sorted(FIELDS.glob("10ppw_f*_summary.csv")):
        frequency = float(np.genfromtxt(path, delimiter=",", names=True)["frequency_hz"])
        if all((FIELDS / f"{label}_f{frequency:04.0f}_summary.csv").exists()
               for label in labels):
            frequencies.append(frequency)
    if not frequencies:
        raise ValueError("no matching 6ppw/8ppw frequencies found")
    rows = []
    coverage_by_label = {label: {"horizontal": [], "vertical": []} for label in labels}
    for frequency in frequencies:
        for label in labels:
            summary, mouth = load(label, frequency)
            impedance = complex(float(summary["input_impedance_real_pa_s_m3"]),
                                float(summary["input_impedance_imag_pa_s_m3"]))
            horizontal = coverage(mouth, frequency, "horizontal")
            vertical = coverage(mouth, frequency, "vertical")
            coverage_by_label[label]["horizontal"].append(horizontal)
            coverage_by_label[label]["vertical"].append(vertical)
            h_width, h_null, h_side = beam_metrics(horizontal)
            v_width, v_null, v_side = beam_metrics(vertical)
            p_rms, velocity_rms, p_coh, velocity_coh = field_metrics(mouth)
            rows.append({
                "mesh": label, "frequency_hz": frequency,
                "impedance_magnitude_pa_s_m3": abs(impedance),
                "radiated_power_w": float(summary["radiated_power_w"]),
                "mouth_pressure_rms_pa": p_rms, "mouth_velocity_rms_m_s": velocity_rms,
                "mouth_pressure_coherence": p_coh, "mouth_velocity_coherence": velocity_coh,
                "horizontal_6db_beamwidth_deg": h_width,
                "vertical_6db_beamwidth_deg": v_width,
                "horizontal_first_null_deg": h_null, "vertical_first_null_deg": v_null,
                "horizontal_peak_sidelobe_db": h_side, "vertical_peak_sidelobe_db": v_side,
                "gmres_iterations": int(summary["gmres_iterations"]),
                "solve_seconds": float(summary["solve_seconds"]),
                "relative_residual": float(summary["relative_residual"]),
            })
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    FIGURES.mkdir(exist_ok=True)
    figure, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True, constrained_layout=True)
    for label in labels:
        selected = [row for row in rows if row["mesh"] == label]
        x = np.array([row["frequency_hz"] for row in selected])
        axes[0].plot(x, [row["impedance_magnitude_pa_s_m3"] for row in selected],
                     "o-", label=label)
        axes[1].plot(x, [row["radiated_power_w"] for row in selected], "o-", label=label)
        axes[2].plot(x, [row["horizontal_6db_beamwidth_deg"] for row in selected],
                     "o-", label=f"{label} H")
        axes[2].plot(x, [row["vertical_6db_beamwidth_deg"] for row in selected],
                     "s--", label=f"{label} V")
    axes[0].set_ylabel("Impedance magnitude (Pa·s/m³)")
    axes[1].set_ylabel("Radiated power (W)")
    axes[2].set_ylabel("−6 dB beamwidth (degrees)")
    axes[2].set_xlabel("Frequency (Hz, log scale)")
    for axis in axes:
        log_axis(axis)
        axis.legend()
    figure.suptitle("Interior FEM mesh-convergence comparison")
    figure.savefig(FIGURES / "response_convergence.png", dpi=180)
    plt.close(figure)

    if len(frequencies) > 1:
        figure, axes = plt.subplots(2, 2, figsize=(13, 11), sharex=True, sharey=True,
                                    constrained_layout=True)
        comparisons = (("8ppw", "6ppw", "8 EPW − 6 EPW"),
                       ("10ppw", "8ppw", "10 EPW − 8 EPW"))
        image = None
        for row, (high, low, comparison) in enumerate(comparisons):
            for column, (plane, plane_title) in enumerate(
                    (("horizontal", "Horizontal"), ("vertical", "Vertical"))):
                axis = axes[row, column]
                difference = (np.asarray(coverage_by_label[high][plane])
                              - np.asarray(coverage_by_label[low][plane])).T
                image = axis.pcolormesh(frequencies, ANGLES, difference, shading="nearest",
                                        cmap="coolwarm", vmin=-3, vmax=3)
                axis.set_title(f"{plane_title}: {comparison}")
                axis.set_xlabel("Frequency (Hz, log scale)")
                axis.set_yticks(np.arange(-90, 91, 15))
                log_axis(axis)
        axes[0, 0].set_ylabel("Off-axis angle (degrees)")
        axes[1, 0].set_ylabel("Off-axis angle (degrees)")
        figure.colorbar(image, ax=axes, label="Coverage level difference (dB)")
        figure.savefig(FIGURES / "coverage_difference.png", dpi=180)
        plt.close(figure)


if __name__ == "__main__":
    main()
