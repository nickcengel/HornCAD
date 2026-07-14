#!/usr/bin/env python3
"""Solve coupled 3D HornCAD radiation with a Helmholtz boundary-element model."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import math

import bempp_cl.api as bempp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedFormatter, FixedLocator, NullFormatter
import numpy as np
import trimesh

try:
    from . import export_horncad as geometry
    from .webster_1d import Medium, frequency_grid, horncad_area_profile
except ImportError:
    import export_horncad as geometry
    from webster_1d import Medium, frequency_grid, horncad_area_profile


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def acoustic_body_mesh(
    yaml_path: Path,
    side_samples: int = 16,
    axial_stations: int = 18,
) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Build a closed rigid body with a marked driven throat-cap patch."""
    if side_samples < 6 or axial_stations < 8:
        raise ValueError("BEM mesh requires at least 6 side samples and 8 axial stations")
    horncad_area_profile(yaml_path, 41)
    geometry.SIDE_SAMPLES = side_samples
    geometry.Z_STATIONS = axial_stations
    h_profile = geometry.profile("h")
    v_profile = geometry.profile("v")
    length = float(geometry.PARAMS["length"])
    mouth_h = h_profile(length)
    mouth_v = v_profile(length)
    extension = max(0.0, float(geometry.PARAMS["throat_extension"]))
    rings: list[list[tuple[float, float, float]]] = []

    if extension > 0.0:
        extension_stations = max(
            2,
            round(axial_stations * extension / max(length, 1e-9)) + 1,
        )
        for index in range(extension_stations):
            rings.append(geometry.conical_extension_ring(index / (extension_stations - 1)))
    horn_samples = geometry.adaptive_profile_z_samples(
        axial_stations, length, h_profile, v_profile
    )
    if extension > 0.0:
        horn_samples = horn_samples[1:]
    for profile_z in horn_samples:
        rings.append(
            geometry.ring_at(
                profile_z / length,
                h_profile(profile_z),
                v_profile(profile_z),
                mouth_h,
                mouth_v,
            )
        )
    mouth_index = len(rings) - 1
    if geometry.PARAMS["mouth_rear_offset"] > 0.0:
        rings.append(geometry.mouth_rear_ring(rings, mouth_h, mouth_v))
    vertices, faces = geometry.build_body_mesh(
        rings, mouth_index, mouth_h, mouth_v
    )
    body = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    throat_radius = float(geometry.PARAMS["r0"])
    throat_z = -extension
    overlap_mm = 0.3
    cap_depth_mm = 2.0
    cap_top_z = throat_z + overlap_mm
    cap_bottom_z = throat_z - cap_depth_mm
    cap = trimesh.creation.cylinder(
        radius=throat_radius + overlap_mm,
        height=cap_top_z - cap_bottom_z,
        sections=max(32, side_samples * 4),
        transform=trimesh.transformations.translation_matrix(
            (0.0, 0.0, (cap_top_z + cap_bottom_z) / 2.0)
        ),
    )
    combined = trimesh.boolean.union((body, cap), engine="manifold")
    if isinstance(combined, list):
        combined = trimesh.util.concatenate(combined)
    combined.process(validate=True)
    trimesh.repair.fix_normals(combined, multibody=True)
    if not combined.is_watertight or not combined.is_winding_consistent:
        raise ValueError("BEM acoustic boundary is not a valid closed oriented mesh")

    centers = combined.triangles_center
    normals = combined.face_normals
    radial = np.hypot(centers[:, 0], centers[:, 1])
    source_faces = (
        (normals[:, 2] > 0.8)
        & (centers[:, 2] > cap_top_z - 0.4)
        & (radial < throat_radius * 0.98)
    )
    if not np.any(source_faces):
        raise ValueError("failed to identify the driven throat patch")
    domain_indices = source_faces.astype(np.uint32)
    combined.apply_scale(1e-3)
    return combined, domain_indices


def receiver_directions(
    angles_deg: np.ndarray,
    azimuth_deg: float,
) -> np.ndarray:
    polar = np.radians(angles_deg)
    azimuth = math.radians(azimuth_deg)
    return np.vstack(
        (
            np.sin(polar) * math.cos(azimuth),
            np.sin(polar) * math.sin(azimuth),
            np.cos(polar),
        )
    )


def solve_frequency(
    grid: bempp.Grid,
    frequency_hz: float,
    angles_deg: np.ndarray,
    sound_speed_m_s: float,
    gmres_tolerance: float,
    gmres_max_iterations: int,
) -> tuple[dict[str, np.ndarray], int, float]:
    wave_number = 2.0 * math.pi * frequency_hz / sound_speed_m_s
    space = bempp.function_space(grid, "P", 1)
    identity = bempp.operators.boundary.sparse.identity(space, space, space)
    adjoint = bempp.operators.boundary.helmholtz.adjoint_double_layer(
        space, space, space, wave_number
    )
    operator = -0.5 * identity + adjoint

    @bempp.complex_callable
    def prescribed_neumann(_x, _n, domain_index, result):
        result[0] = 1.0 if domain_index == 1 else 0.0

    rhs = bempp.GridFunction(space, fun=prescribed_neumann)
    density, info, iterations = bempp.linalg.gmres(
        operator,
        rhs,
        tol=gmres_tolerance,
        maxiter=gmres_max_iterations,
        use_strong_form=True,
        return_iteration_count=True,
    )
    if info != 0:
        raise RuntimeError(
            f"BEM GMRES failed at {frequency_hz:g} Hz: info={info}, iterations={iterations}"
        )

    cuts: dict[str, np.ndarray] = {}
    for name, azimuth in (("horizontal", 0.0), ("diagonal", 45.0), ("vertical", 90.0)):
        directions = receiver_directions(angles_deg, azimuth)
        single_far = bempp.operators.far_field.helmholtz.single_layer(
            space, directions, wave_number
        )
        pressure = np.asarray(single_far.evaluate(density)).reshape(-1)
        reference = max(abs(pressure[0]), 1e-15)
        cuts[name] = 20.0 * np.log10(np.maximum(np.abs(pressure) / reference, 1e-15))
    return cuts, iterations, float(space.global_dof_count)


def write_cut_csv(
    path: Path,
    angles_deg: np.ndarray,
    frequencies_hz: np.ndarray,
    values_db: np.ndarray,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("angle_deg", *[float(value) for value in frequencies_hz]))
        for angle, row in zip(angles_deg, values_db):
            writer.writerow((float(angle), *[float(value) for value in row]))


def plot_cuts(
    path: Path,
    angles_deg: np.ndarray,
    frequencies_hz: np.ndarray,
    cuts: dict[str, np.ndarray],
    floor_db: float,
) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(17.0, 5.8), sharey=True, constrained_layout=True)
    figure.patch.set_facecolor("white")
    colors = plt.cm.viridis(np.linspace(0.0, 1.0, len(frequencies_hz)))
    for axis, name in zip(axes, ("horizontal", "diagonal", "vertical")):
        for index, frequency_hz in enumerate(frequencies_hz):
            axis.plot(
                angles_deg,
                np.maximum(cuts[name][:, index], floor_db),
                color=colors[index],
                label=f"{frequency_hz:g} Hz",
                linewidth=1.4,
            )
        axis.axhline(-6.0, color="black", alpha=0.3, linestyle="--", linewidth=0.8)
        axis.set_xlim(0.0, 90.0)
        axis.set_ylim(floor_db, max(3.0, math.ceil(float(np.max(cuts[name])))))
        axis.grid(True, alpha=0.25)
        axis.set_xlabel("Off-axis angle (degrees)")
        axis.set_title(f"{name.capitalize()} plane")
    axes[0].set_ylabel("Level relative to on-axis (dB)")
    axes[-1].legend(loc="lower left", fontsize=8)
    figure.suptitle("HornCAD Coupled 3D Helmholtz BEM — Normalized Far Field")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def plot_heatmaps(
    path: Path,
    angles_deg: np.ndarray,
    frequencies_hz: np.ndarray,
    cuts: dict[str, np.ndarray],
    floor_db: float,
) -> None:
    """Plot discrete BEM samples without interpolating between frequency columns."""
    figure, axes = plt.subplots(
        1, 3, figsize=(17.0, 6.0), sharey=True, constrained_layout=True
    )
    figure.patch.set_facecolor("white")
    peak_db = max(float(np.max(values)) for values in cuts.values())
    ceiling_db = max(0.0, math.ceil(peak_db))
    image = None
    for axis, name in zip(axes, ("horizontal", "diagonal", "vertical")):
        image = axis.pcolormesh(
            frequencies_hz,
            angles_deg,
            np.maximum(cuts[name], floor_db),
            shading="nearest",
            cmap="turbo",
            vmin=floor_db,
            vmax=ceiling_db,
        )
        minus_six = axis.contour(
            frequencies_hz,
            angles_deg,
            cuts[name],
            levels=[-6.0],
            colors="black",
            linewidths=1.4,
        )
        axis.clabel(minus_six, fmt={-6.0: "−6 dB"}, fontsize=8, inline=True)
        axis.set_xscale("log")
        axis.set_xlim(float(frequencies_hz[0]), float(frequencies_hz[-1]))
        ticks = [500.0, 700.0, 1000.0, 2000.0, 3000.0, 5000.0]
        visible_ticks = [
            tick for tick in ticks if frequencies_hz[0] <= tick <= frequencies_hz[-1]
        ]
        axis.xaxis.set_major_locator(FixedLocator(visible_ticks))
        axis.xaxis.set_major_formatter(
            FixedFormatter(
                [
                    f"{tick / 1000:g}k" if tick >= 1000.0 else f"{tick:g}"
                    for tick in visible_ticks
                ]
            )
        )
        axis.xaxis.set_minor_formatter(NullFormatter())
        axis.xaxis.get_offset_text().set_visible(False)
        axis.set_xlabel("Frequency (Hz, logarithmic)")
        axis.set_title(f"{name.capitalize()} plane")
    axes[0].set_ylabel("Off-axis angle (degrees)")
    figure.suptitle(
        "HornCAD Coupled 3D Helmholtz BEM — Discrete Normalized Directivity"
    )
    colorbar = figure.colorbar(image, ax=axes, pad=0.02)
    colorbar.set_label("Level relative to on-axis (dB)")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--start-hz", type=float, default=500.0)
    parser.add_argument("--stop-hz", type=float, default=5_000.0)
    parser.add_argument("--frequencies", type=int, default=8)
    parser.add_argument("--angles", type=int, default=91)
    parser.add_argument("--floor-db", type=float, default=-40.0)
    parser.add_argument("--side-samples", type=int, default=16)
    parser.add_argument("--stations", type=int, default=18)
    parser.add_argument("--sound-speed", type=float, default=Medium.sound_speed_m_s)
    parser.add_argument("--gmres-tolerance", type=float, default=1e-5)
    parser.add_argument("--gmres-max-iterations", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frequencies_hz = frequency_grid(
        args.start_hz, args.stop_hz, args.frequencies, "log"
    )
    angles_deg = np.linspace(0.0, 90.0, args.angles)
    body, domain_indices = acoustic_body_mesh(
        args.yaml, args.side_samples, args.stations
    )
    grid = bempp.Grid(
        body.vertices.T,
        body.faces.T,
        domain_indices=domain_indices,
    )
    cuts = {
        name: np.empty((len(angles_deg), len(frequencies_hz)), dtype=float)
        for name in ("horizontal", "diagonal", "vertical")
    }
    for index, frequency_hz in enumerate(frequencies_hz):
        result, iterations, dofs = solve_frequency(
            grid,
            float(frequency_hz),
            angles_deg,
            args.sound_speed,
            args.gmres_tolerance,
            args.gmres_max_iterations,
        )
        for name in cuts:
            cuts[name][:, index] = result[name]
        print(
            f"frequency_hz={frequency_hz:.6g} dofs={int(dofs)} "
            f"gmres_iterations={iterations}",
            flush=True,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.yaml.stem}-HelmholtzBEM3D-Directivity"
    plot_path = args.output_dir / f"{stem}.png"
    heatmap_path = args.output_dir / f"{stem}-Heatmap.png"
    plot_cuts(plot_path, angles_deg, frequencies_hz, cuts, args.floor_db)
    plot_heatmaps(
        heatmap_path, angles_deg, frequencies_hz, cuts, args.floor_db
    )
    print(plot_path)
    print(heatmap_path)
    for name in cuts:
        csv_path = args.output_dir / f"{stem}-{name.capitalize()}.csv"
        write_cut_csv(csv_path, angles_deg, frequencies_hz, cuts[name])
        print(csv_path)


if __name__ == "__main__":
    main()
