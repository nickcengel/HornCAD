#!/usr/bin/env python3
"""Estimate normalized H/V far-field directivity from a HornCAD mouth aperture."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from . import export_horncad as geometry
    from .webster_1d import Medium, frequency_grid, horncad_area_profile
except ImportError:
    import export_horncad as geometry
    from webster_1d import Medium, frequency_grid, horncad_area_profile


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def mouth_aperture_samples(
    yaml_path: Path,
    x_samples: int = 161,
    y_samples: int = 105,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return equal-area sample coordinates inside the projected mouth aperture."""
    if x_samples < 21 or y_samples < 21:
        raise ValueError("aperture sampling requires at least 21 points on each axis")

    # Loads and validates the design, and resets shared geometry defaults first.
    horncad_area_profile(yaml_path, 41)
    half_width = float(geometry.PARAMS["mouth_width"]) / 2.0
    half_height = float(geometry.PARAMS["mouth_height"]) / 2.0
    total_z = max(0.0, float(geometry.PARAMS["throat_extension"])) + float(
        geometry.PARAMS["length"]
    )
    power = geometry.superellipse_n(geometry.section_shape(total_z))

    x_axis = np.linspace(-half_width, half_width, x_samples)
    y_axis = np.linspace(-half_height, half_height, y_samples)
    x_grid, y_grid = np.meshgrid(x_axis, y_axis)
    inside = (
        np.abs(x_grid / max(half_width, 1e-12)) ** power
        + np.abs(y_grid / max(half_height, 1e-12)) ** power
        <= 1.0
    )
    x_mm = x_grid[inside]
    y_mm = y_grid[inside]
    mouth_h = half_width
    mouth_v = half_height
    z_mm = np.array(
        [
            geometry.PARAMS["length"]
            - geometry.mouth_setback(float(x), float(y), mouth_h, mouth_v)
            for x, y in zip(x_mm, y_mm)
        ],
        dtype=float,
    )
    return x_mm * 1e-3, y_mm * 1e-3, z_mm * 1e-3


def normalized_plane_directivity(
    transverse_m: np.ndarray,
    axial_m: np.ndarray,
    frequencies_hz: np.ndarray,
    angles_deg: np.ndarray,
    sound_speed_m_s: float,
    floor_db: float = -40.0,
) -> np.ndarray:
    """Integrate a uniform-velocity curved aperture and normalize each frequency on-axis."""
    if len(transverse_m) == 0 or len(transverse_m) != len(axial_m):
        raise ValueError("aperture coordinates must be nonempty and have matching lengths")
    if sound_speed_m_s <= 0.0:
        raise ValueError("sound speed must be positive")

    angles_rad = np.radians(angles_deg)
    direction_transverse = np.sin(angles_rad)
    direction_axial = np.cos(angles_rad)
    result = np.empty((len(angles_deg), len(frequencies_hz)), dtype=float)

    for frequency_index, frequency_hz in enumerate(frequencies_hz):
        wave_number = 2.0 * math.pi * float(frequency_hz) / sound_speed_m_s
        phase_distance = (
            direction_transverse[:, None] * transverse_m[None, :]
            + direction_axial[:, None] * axial_m[None, :]
        )
        pressure = np.mean(np.exp(-1j * wave_number * phase_distance), axis=1)
        reference = max(abs(pressure[0]), 1e-15)
        db = 20.0 * np.log10(np.maximum(np.abs(pressure) / reference, 1e-15))
        result[:, frequency_index] = np.maximum(db, floor_db)
    return result


def write_matrix_csv(
    path: Path,
    angles_deg: np.ndarray,
    frequencies_hz: np.ndarray,
    attenuation_db: np.ndarray,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("angle_deg", *[float(value) for value in frequencies_hz]))
        for angle, row in zip(angles_deg, attenuation_db):
            writer.writerow((float(angle), *[float(value) for value in row]))


def plot_directivity(
    path: Path,
    frequencies_hz: np.ndarray,
    angles_deg: np.ndarray,
    horizontal_db: np.ndarray,
    vertical_db: np.ndarray,
    floor_db: float,
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(15.5, 6.8), sharey=True, constrained_layout=True)
    figure.patch.set_facecolor("white")
    peak_db = max(float(np.max(horizontal_db)), float(np.max(vertical_db)), 0.0)
    ceiling_db = max(0.0, math.ceil(peak_db))
    mesh = None
    for axis, values, title in (
        (axes[0], horizontal_db, "Horizontal plane"),
        (axes[1], vertical_db, "Vertical plane"),
    ):
        mesh = axis.pcolormesh(
            frequencies_hz,
            angles_deg,
            values,
            shading="auto",
            cmap="turbo",
            vmin=floor_db,
            vmax=ceiling_db,
        )
        axis.contour(
            frequencies_hz,
            angles_deg,
            values,
            levels=(-12.0, -6.0, -3.0, 0.0),
            colors="white",
            linewidths=0.65,
            alpha=0.8,
        )
        axis.set_xscale("log")
        axis.set_xlim(float(frequencies_hz[0]), float(frequencies_hz[-1]))
        ticks = [250.0, 500.0, 1000.0, 2000.0, 5000.0, 10_000.0]
        axis.set_xticks([tick for tick in ticks if frequencies_hz[0] <= tick <= frequencies_hz[-1]])
        axis.set_xticklabels(
            [f"{tick / 1000:g}k" if tick >= 1000.0 else f"{tick:g}" for tick in ticks if frequencies_hz[0] <= tick <= frequencies_hz[-1]]
        )
        axis.set_ylim(float(angles_deg[0]), float(angles_deg[-1]))
        axis.set_xlabel("Frequency (Hz)")
        axis.set_title(title)
    axes[0].set_ylabel("Off-axis angle (degrees)")
    figure.suptitle("HornCAD Uniform-Aperture Directivity Estimate — On-axis Normalized")
    colorbar = figure.colorbar(mesh, ax=axes, pad=0.02)
    colorbar.set_label("Level relative to on-axis (dB)")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path, help="HornCAD YAML exported by the browser app.")
    parser.add_argument("--start-hz", type=float, default=250.0)
    parser.add_argument("--stop-hz", type=float, default=10_000.0)
    parser.add_argument("--frequencies", type=int, default=121)
    parser.add_argument("--angles", type=int, default=91)
    parser.add_argument("--floor-db", type=float, default=-40.0)
    parser.add_argument("--x-samples", type=int, default=161)
    parser.add_argument("--y-samples", type=int, default=105)
    parser.add_argument("--sound-speed", type=float, default=Medium.sound_speed_m_s)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frequencies_hz = frequency_grid(args.start_hz, args.stop_hz, args.frequencies, "log")
    if args.angles < 2:
        raise ValueError("angle count must be at least 2")
    if args.floor_db >= 0.0:
        raise ValueError("floor_db must be negative")
    angles_deg = np.linspace(0.0, 90.0, args.angles)
    x_m, y_m, z_m = mouth_aperture_samples(args.yaml, args.x_samples, args.y_samples)
    horizontal_db = normalized_plane_directivity(
        x_m, z_m, frequencies_hz, angles_deg, args.sound_speed, args.floor_db
    )
    vertical_db = normalized_plane_directivity(
        y_m, z_m, frequencies_hz, angles_deg, args.sound_speed, args.floor_db
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.yaml.stem}-Aperture-Directivity"
    plot_path = args.output_dir / f"{stem}.png"
    horizontal_path = args.output_dir / f"{stem}-Horizontal.csv"
    vertical_path = args.output_dir / f"{stem}-Vertical.csv"
    plot_directivity(
        plot_path,
        frequencies_hz,
        angles_deg,
        horizontal_db,
        vertical_db,
        args.floor_db,
    )
    write_matrix_csv(horizontal_path, angles_deg, frequencies_hz, horizontal_db)
    write_matrix_csv(vertical_path, angles_deg, frequencies_hz, vertical_db)
    print(plot_path)
    print(horizontal_path)
    print(vertical_path)
    print(
        f"aperture_samples={len(x_m)} frequencies={len(frequencies_hz)} "
        f"angles={len(angles_deg)}"
    )


if __name__ == "__main__":
    main()
