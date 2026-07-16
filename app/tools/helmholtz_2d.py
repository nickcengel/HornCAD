#!/usr/bin/env python3
"""Solve normalized H/V HornCAD directivity with two-dimensional Helmholtz FEM."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import math

import gmsh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.sparse.linalg import spsolve
from skfem import Basis, BilinearForm, ElementTriP1, FacetBasis, LinearForm, MeshTri, asm
from skfem.helpers import dot, grad

try:
    from . import export_horncad as geometry
    from .webster_1d import Medium, frequency_grid, horncad_area_profile
except ImportError:
    import export_horncad as geometry
    from webster_1d import Medium, frequency_grid, horncad_area_profile


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


@dataclass(frozen=True)
class PlaneGeometry:
    axis: str
    wall_axial_m: np.ndarray
    wall_transverse_m: np.ndarray
    mouth_axial_m: float
    mouth_half_span_m: float


@dataclass(frozen=True)
class MeshDomain:
    mesh: MeshTri
    mouth_axial_m: float
    outer_axial_m: float
    outer_transverse_m: float


def horncad_plane_geometry(
    yaml_path: Path,
    axis: str,
    wall_samples: int = 121,
) -> PlaneGeometry:
    if axis not in ("h", "v"):
        raise ValueError("axis must be 'h' or 'v'")
    if wall_samples < 21:
        raise ValueError("wall_samples must be at least 21")

    horncad_area_profile(yaml_path, 41)
    extension_mm = max(0.0, float(geometry.PARAMS["throat_extension"]))
    profile_length_mm = float(geometry.PARAMS["length"])
    throat_angle_rad = math.radians(float(geometry.PARAMS["throat_angle"]))
    r0_mm = float(geometry.PARAMS["r0"])
    profile = geometry.profile(axis)
    half_width = float(geometry.PARAMS["mouth_width"]) / 2.0
    half_height = float(geometry.PARAMS["mouth_height"]) / 2.0
    if axis == "h":
        edge_x, edge_y = half_width, 0.0
        half_span_mm = half_width
    else:
        edge_x, edge_y = 0.0, half_height
        half_span_mm = half_height
    local_profile_length_mm = profile_length_mm - geometry.mouth_setback(
        edge_x, edge_y, half_width, half_height
    )
    if local_profile_length_mm <= 0.0:
        raise ValueError(f"{axis}-plane mouth setback consumes the profile length")

    extension_count = 0
    if extension_mm > 0.0:
        extension_count = max(3, round(wall_samples * extension_mm / (extension_mm + profile_length_mm)))
    profile_count = max(3, wall_samples - extension_count + 1)
    axial_mm: list[float] = []
    transverse_mm: list[float] = []
    if extension_count:
        for value in np.linspace(0.0, extension_mm, extension_count, endpoint=False):
            axial_mm.append(float(value))
            transverse_mm.append(r0_mm + float(value) * math.tan(throat_angle_rad))
    for profile_z in np.linspace(0.0, profile_length_mm, profile_count):
        tau = float(profile_z) / profile_length_mm
        axial_mm.append(extension_mm + tau * local_profile_length_mm)
        transverse_mm.append(float(profile(float(profile_z))))

    return PlaneGeometry(
        axis=axis,
        wall_axial_m=np.asarray(axial_mm) * 1e-3,
        wall_transverse_m=np.asarray(transverse_mm) * 1e-3,
        mouth_axial_m=(extension_mm + local_profile_length_mm) * 1e-3,
        mouth_half_span_m=half_span_mm * 1e-3,
    )


def gmsh_half_domain(
    plane: PlaneGeometry,
    max_element_m: float,
    exterior_extent_m: float,
) -> MeshDomain:
    if max_element_m <= 0.0 or exterior_extent_m <= plane.mouth_half_span_m:
        raise ValueError("mesh size and exterior extent must be positive and contain the mouth")
    outer_axial = plane.mouth_axial_m + exterior_extent_m
    outer_transverse = exterior_extent_m

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"horncad_{plane.axis}_plane")
        center = gmsh.model.geo.addPoint(0.0, 0.0, 0.0, max_element_m)
        wall_points = [
            gmsh.model.geo.addPoint(float(x), float(y), 0.0, max_element_m)
            for x, y in zip(plane.wall_axial_m, plane.wall_transverse_m)
        ]
        baffle_top = gmsh.model.geo.addPoint(
            plane.mouth_axial_m, outer_transverse, 0.0, max_element_m
        )
        outer_top = gmsh.model.geo.addPoint(
            outer_axial, outer_transverse, 0.0, max_element_m
        )
        outer_axis = gmsh.model.geo.addPoint(outer_axial, 0.0, 0.0, max_element_m)

        throat = gmsh.model.geo.addLine(center, wall_points[0])
        wall = gmsh.model.geo.addSpline(wall_points)
        baffle = gmsh.model.geo.addLine(wall_points[-1], baffle_top)
        top = gmsh.model.geo.addLine(baffle_top, outer_top)
        outgoing = gmsh.model.geo.addLine(outer_top, outer_axis)
        symmetry = gmsh.model.geo.addLine(outer_axis, center)
        loop = gmsh.model.geo.addCurveLoop((throat, wall, baffle, top, outgoing, symmetry))
        gmsh.model.geo.addPlaneSurface((loop,))
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMin", max_element_m * 0.65)
        gmsh.option.setNumber("Mesh.MeshSizeMax", max_element_m)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.mesh.generate(2)

        node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
        points = np.asarray(coordinates).reshape(-1, 3)[:, :2]
        node_index = {int(tag): index for index, tag in enumerate(node_tags)}
        element_types, _, element_nodes = gmsh.model.mesh.getElements(2)
        triangles = None
        for element_type, nodes in zip(element_types, element_nodes):
            _, dimension, order, node_count, _, _ = gmsh.model.mesh.getElementProperties(element_type)
            if dimension == 2 and order == 1 and node_count == 3:
                tags = np.asarray(nodes).reshape(-1, 3)
                triangles = np.vectorize(node_index.__getitem__)(tags)
                break
        if triangles is None:
            raise RuntimeError("Gmsh did not produce linear triangular elements")
    finally:
        gmsh.finalize()

    mesh = MeshTri(points.T, triangles.T).remove_unused_nodes().with_boundaries(
        {
            "throat": lambda x: np.isclose(x[0], 0.0, atol=max_element_m * 0.1)
            & (x[1] <= plane.wall_transverse_m[0] + max_element_m * 0.1),
            "outer_top": lambda x: np.isclose(
                x[1], outer_transverse, atol=max_element_m * 0.1
            ),
            "outer_right": lambda x: np.isclose(
                x[0], outer_axial, atol=max_element_m * 0.1
            ),
        }
    )
    return MeshDomain(mesh, plane.mouth_axial_m, outer_axial, outer_transverse)


@BilinearForm
def stiffness(u, v, _):
    return dot(grad(u), grad(v))


@BilinearForm
def mass(u, v, _):
    return u * v


@BilinearForm
def boundary_mass(u, v, _):
    return u * v


@LinearForm
def throat_source(v, _):
    return v


def solve_plane_sweep(
    domain: MeshDomain,
    frequencies_hz: np.ndarray,
    angles_deg: np.ndarray,
    receiver_radius_m: float,
    medium: Medium,
    floor_db: float,
) -> np.ndarray:
    mesh = domain.mesh
    basis = Basis(mesh, ElementTriP1())
    throat_basis = FacetBasis(mesh, ElementTriP1(), facets=mesh.boundaries["throat"])
    outgoing_facets = np.concatenate(
        (mesh.boundaries["outer_top"], mesh.boundaries["outer_right"])
    )
    outgoing_basis = FacetBasis(mesh, ElementTriP1(), facets=outgoing_facets)
    stiffness_matrix = asm(stiffness, basis).astype(complex)
    mass_matrix = asm(mass, basis).astype(complex)
    outgoing_matrix = asm(boundary_mass, outgoing_basis).astype(complex)
    source = asm(throat_source, throat_basis).astype(complex)

    angles_rad = np.radians(angles_deg)
    receiver_points = np.vstack(
        (
            domain.mouth_axial_m + receiver_radius_m * np.cos(angles_rad),
            receiver_radius_m * np.sin(angles_rad),
        )
    )
    if np.any(receiver_points[0] >= domain.outer_axial_m) or np.any(
        receiver_points[1] >= domain.outer_transverse_m
    ):
        raise ValueError("receiver arc must lie inside the exterior domain")
    interpolate = basis.probes(receiver_points)
    directivity_db = np.empty((len(angles_deg), len(frequencies_hz)), dtype=float)

    for index, frequency_hz in enumerate(frequencies_hz):
        wave_number = 2.0 * math.pi * float(frequency_hz) / medium.sound_speed_m_s
        system = (
            stiffness_matrix
            - wave_number * wave_number * mass_matrix
            - 1j * wave_number * outgoing_matrix
        )
        # The source scale cancels during directivity normalization.
        pressure = spsolve(system.tocsc(), source)
        receivers = interpolate @ pressure
        reference = max(abs(receivers[0]), 1e-15)
        values = 20.0 * np.log10(np.maximum(np.abs(receivers) / reference, 1e-15))
        directivity_db[:, index] = np.maximum(values, floor_db)
    return directivity_db


def write_matrix_csv(
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
    mesh_plot = None
    for axis, values, title in (
        (axes[0], horizontal_db, "Horizontal plane"),
        (axes[1], vertical_db, "Vertical plane"),
    ):
        mesh_plot = axis.pcolormesh(
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
        axis.set_ylim(float(angles_deg[0]), float(angles_deg[-1]))
        axis.set_xlabel("Frequency (Hz)")
        axis.set_title(title)
    axes[0].set_ylabel("Off-axis angle (degrees)")
    figure.suptitle("HornCAD 2D Helmholtz FEM Directivity — On-axis Normalized")
    colorbar = figure.colorbar(mesh_plot, ax=axes, pad=0.02)
    colorbar.set_label("Level relative to on-axis (dB)")
    figure.savefig(path, dpi=180, facecolor="white")
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--start-hz", type=float, default=250.0)
    parser.add_argument("--stop-hz", type=float, default=10_000.0)
    parser.add_argument("--frequencies", type=int, default=61)
    parser.add_argument("--angles", type=int, default=91)
    parser.add_argument("--floor-db", type=float, default=-40.0)
    parser.add_argument("--elements-per-wavelength", type=float, default=6.0)
    parser.add_argument("--exterior-extent", type=float, default=0.4)
    parser.add_argument("--receiver-radius", type=float, default=0.28)
    parser.add_argument("--sound-speed", type=float, default=Medium.sound_speed_m_s)
    parser.add_argument("--density", type=float, default=Medium.density_kg_m3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.elements_per_wavelength < 4.0:
        raise ValueError("elements_per_wavelength must be at least 4")
    frequencies_hz = frequency_grid(args.start_hz, args.stop_hz, args.frequencies, "log")
    angles_deg = np.linspace(0.0, 90.0, args.angles)
    medium = Medium(args.density, args.sound_speed)
    max_element_m = medium.sound_speed_m_s / (
        args.stop_hz * args.elements_per_wavelength
    )
    results = {}
    node_counts = {}
    for axis in ("h", "v"):
        plane = horncad_plane_geometry(args.yaml, axis)
        domain = gmsh_half_domain(plane, max_element_m, args.exterior_extent)
        results[axis] = solve_plane_sweep(
            domain,
            frequencies_hz,
            angles_deg,
            args.receiver_radius,
            medium,
            args.floor_db,
        )
        node_counts[axis] = domain.mesh.nvertices

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.yaml.stem}-Helmholtz2D-Directivity"
    plot_path = args.output_dir / f"{stem}.png"
    horizontal_path = args.output_dir / f"{stem}-Horizontal.csv"
    vertical_path = args.output_dir / f"{stem}-Vertical.csv"
    plot_directivity(
        plot_path,
        frequencies_hz,
        angles_deg,
        results["h"],
        results["v"],
        args.floor_db,
    )
    write_matrix_csv(horizontal_path, angles_deg, frequencies_hz, results["h"])
    write_matrix_csv(vertical_path, angles_deg, frequencies_hz, results["v"])
    print(plot_path)
    print(horizontal_path)
    print(vertical_path)
    print(
        f"nodes_h={node_counts['h']} nodes_v={node_counts['v']} "
        f"frequencies={len(frequencies_hz)} angles={len(angles_deg)}"
    )


if __name__ == "__main__":
    main()
