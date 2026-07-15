#!/usr/bin/env python3
"""One-way free-field source scattering from a finite HornCAD lip solid.

The saved FEM mouth velocity defines a curved monopole source sheet. A
watertight mouth-end section of the printable body is a rigid scatterer. This
is deliberately uncoupled: the lip does not alter the saved interior FEM field.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path

import bempp_cl.api as bempp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh

try:
    from .aperture_field import (
        ApertureField,
        FREE_FIELD_MODEL,
        plane_directions,
        read_mfem_mouth_csv,
    )
    from .helmholtz_bem_3d import (
        AcousticMedium,
        _authored_mesh,
        _combined_field_solve_grid_function,
    )
except ImportError:
    from aperture_field import ApertureField, FREE_FIELD_MODEL, plane_directions, read_mfem_mouth_csv
    from helmholtz_bem_3d import AcousticMedium, _authored_mesh, _combined_field_solve_grid_function


LOCAL_LIP_MODEL = "one_way_rigid_closed_local_lip_scattering"


@dataclass(frozen=True)
class LocalLipSettings:
    retained_depth_m: float = 0.05
    elements_per_wavelength: float = 6.0
    receiver_radius_m: float = 10.0
    gmres_tolerance: float = 1e-5
    gmres_max_iterations: int = 300
    direct_solve_max_dofs: int = 2_500
    minimum_angle_deg: float = 0.01
    maximum_aspect_ratio: float = 3_000.0


@dataclass
class LocalLipMesh:
    surface: trimesh.Trimesh
    retained_depth_m: float
    maximum_edge_m: float
    target_edge_m: float
    rear_closure_z_m: float
    minimum_angle_deg: float
    maximum_aspect_ratio: float


@dataclass
class LocalLipResult:
    incident_pressure_pa: dict[str, np.ndarray]
    scattered_pressure_pa: dict[str, np.ndarray]
    total_pressure_pa: dict[str, np.ndarray]
    gmres_iterations: int
    dofs: int


def build_local_lip_mesh(yaml_path: Path, frequency_hz: float,
                         settings: LocalLipSettings) -> LocalLipMesh:
    """Clip the authored thick body to a watertight mouth-end scattering solid."""
    if frequency_hz <= 0.0 or settings.retained_depth_m <= 0.0:
        raise ValueError("frequency and retained lip depth must be positive")
    if settings.elements_per_wavelength <= 0.0:
        raise ValueError("elements per wavelength must be positive")
    target = AcousticMedium().sound_speed_m_s / (
        frequency_hz * settings.elements_per_wavelength)
    # Seed geometry independently of the final acoustic refinement.
    body, mouth_ring_mm, _ = _authored_mesh(yaml_path, side_samples=12, axial_stations=28)
    body.apply_scale(1e-3)
    # Measure retained return behind the rearmost authored mouth point. Using
    # the forward-most point can cut a strongly curved rim into disconnected
    # islands before the complete perimeter has joined behind the mouth.
    mouth_rear_z = float(np.min(mouth_ring_mm[:, 2])) * 1e-3
    rear_z = mouth_rear_z - settings.retained_depth_m
    bounds = body.bounds
    span_xy = max(float(np.ptp(bounds[:, 0])), float(np.ptp(bounds[:, 1]))) + 0.2
    upper = float(bounds[1, 2]) + 0.05
    box = trimesh.creation.box(
        extents=(span_xy, span_xy, upper - rear_z),
        transform=trimesh.transformations.translation_matrix(
            (0.0, 0.0, 0.5 * (upper + rear_z))),
    )
    clipped = trimesh.boolean.intersection((body, box), engine="manifold")
    if isinstance(clipped, list):
        clipped = trimesh.util.concatenate(clipped)
    clipped.process(validate=True)
    trimesh.repair.fix_normals(clipped, multibody=True)
    for _ in range(10):
        edges = np.linalg.norm(
            clipped.vertices[clipped.edges_unique[:, 0]]
            - clipped.vertices[clipped.edges_unique[:, 1]], axis=1)
        if float(edges.max()) <= target + 1e-12:
            break
        vertices, faces = trimesh.remesh.subdivide(clipped.vertices, clipped.faces)
        clipped = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if not clipped.is_watertight or not clipped.is_winding_consistent or len(clipped.split()) != 1:
        raise ValueError("local lip clipping did not produce one oriented watertight solid")
    edges = np.linalg.norm(
        clipped.vertices[clipped.edges_unique[:, 0]]
        - clipped.vertices[clipped.edges_unique[:, 1]], axis=1)
    if float(edges.max()) > target + 1e-12:
        raise ValueError("local lip mesh exceeds its wavelength edge limit")
    sides = np.sort(np.linalg.norm(
        clipped.triangles - np.roll(clipped.triangles, 1, axis=1), axis=2), axis=1)
    aspects = sides[:, 2] / np.maximum(sides[:, 0], 1e-15)
    cosine = np.clip(
        (sides[:, 1] ** 2 + sides[:, 2] ** 2 - sides[:, 0] ** 2)
        / np.maximum(2.0 * sides[:, 1] * sides[:, 2], 1e-30), -1.0, 1.0)
    angles = np.degrees(np.arccos(cosine))
    if float(angles.min()) < settings.minimum_angle_deg:
        raise ValueError("local lip mesh minimum angle is below its quality limit")
    if float(aspects.max()) > settings.maximum_aspect_ratio:
        raise ValueError("local lip mesh aspect ratio exceeds its quality limit")
    return LocalLipMesh(clipped, settings.retained_depth_m, float(edges.max()),
                        target, rear_z, float(angles.min()), float(aspects.max()))


def monopole_pressure_gradient(field: ApertureField, points_m: np.ndarray,
                               medium: AcousticMedium = AcousticMedium()
                               ) -> tuple[np.ndarray, np.ndarray]:
    """Return free-field source-sheet pressure and spatial gradient."""
    points = np.asarray(points_m, dtype=float)
    separation = points[:, None, :] - field.positions_m[None, :, :]
    distance = np.linalg.norm(separation, axis=2)
    if np.any(distance <= 1e-12):
        raise ValueError("source-sheet field is singular at an evaluation point")
    omega = 2.0 * math.pi * field.frequency_hz
    k = omega / medium.sound_speed_m_s
    phase = np.exp(-1j * k * distance)
    strengths = field.normal_velocity_m_s * field.area_weights_m2
    coefficient = 1j * medium.density_kg_m3 * omega / (4.0 * math.pi)
    pressure = coefficient * np.sum(phase / distance * strengths[None, :], axis=1)
    radial = phase * (-1j * k / distance ** 2 - 1.0 / distance ** 3)
    gradient = coefficient * np.sum(
        radial[:, :, None] * separation * strengths[None, :, None], axis=1)
    return pressure, gradient


def solve_local_lip(field: ApertureField, lip: LocalLipMesh,
                    angles_deg: np.ndarray, settings: LocalLipSettings,
                    medium: AcousticMedium = AcousticMedium()) -> LocalLipResult:
    """Solve rigid scattering and return finite-distance incident/scattered fields."""
    grid = bempp.Grid(lip.surface.vertices.T, lip.surface.faces.T)
    space = bempp.function_space(grid, "P", 1)
    source_positions = np.ascontiguousarray(field.positions_m)
    source_strengths = np.ascontiguousarray(
        field.normal_velocity_m_s * field.area_weights_m2)
    omega = 2.0 * math.pi * field.frequency_hz
    k = omega / medium.sound_speed_m_s
    coefficient = 1j * medium.density_kg_m3 * omega / (4.0 * math.pi)

    @bempp.complex_callable
    def rigid_neumann(x, n, _domain_index, result):
        value = 0.0j
        for index in range(source_positions.shape[0]):
            dx = x[0] - source_positions[index, 0]
            dy = x[1] - source_positions[index, 1]
            dz = x[2] - source_positions[index, 2]
            radius = math.sqrt(dx * dx + dy * dy + dz * dz)
            radial = np.exp(-1j * k * radius) * (-1j * k / (radius * radius)
                                                  - 1.0 / (radius ** 3))
            value += radial * (dx * n[0] + dy * n[1] + dz * n[2]) * source_strengths[index]
        result[0] = -coefficient * value

    neumann = bempp.GridFunction(space, fun=rigid_neumann)
    trace, iterations = _combined_field_solve_grid_function(
        space, neumann, field.frequency_hz, medium, settings.gmres_tolerance,
        settings.gmres_max_iterations, direct_solve_max_dofs=settings.direct_solve_max_dofs)
    single = bempp.operators.potential.helmholtz.single_layer
    double = bempp.operators.potential.helmholtz.double_layer
    incident, scattered, total = {}, {}, {}
    for plane in ("horizontal", "diagonal", "vertical"):
        directions = plane_directions(angles_deg, plane)
        observers = field.center_m + settings.receiver_radius_m * directions
        incident[plane], _ = monopole_pressure_gradient(field, observers, medium)
        scattered[plane] = np.asarray((
            double(space, observers.T, k).evaluate(trace)
            - single(space, observers.T, k).evaluate(neumann))).reshape(-1)
        total[plane] = incident[plane] + scattered[plane]
    return LocalLipResult(incident, scattered, total, iterations,
                          int(space.global_dof_count))


def write_result(path: Path, field: ApertureField, lip: LocalLipMesh,
                 result: LocalLipResult, angles_deg: np.ndarray,
                 settings: LocalLipSettings) -> None:
    path.mkdir(parents=True, exist_ok=True)
    lip.surface.export(path / "local_lip.stl")
    arrays = {"frequency_hz": field.frequency_hz, "angles_deg": angles_deg,
              "incident_model": FREE_FIELD_MODEL, "scattering_model": LOCAL_LIP_MODEL}
    for plane in ("horizontal", "diagonal", "vertical"):
        arrays[f"incident_{plane}_pressure_pa"] = result.incident_pressure_pa[plane]
        arrays[f"scattered_{plane}_pressure_pa"] = result.scattered_pressure_pa[plane]
        arrays[f"total_{plane}_pressure_pa"] = result.total_pressure_pa[plane]
        arrays[f"lip_difference_{plane}_pressure_pa"] = result.scattered_pressure_pa[plane]
    np.savez_compressed(path / "responses.npz", **arrays)
    manifest = {
        "status": "complete", "coupling": "one_way_prescribed_fem_mouth_velocity",
        "frequency_hz": field.frequency_hz, "retained_depth_m": lip.retained_depth_m,
        "rear_closure_z_m": lip.rear_closure_z_m,
        "triangles": len(lip.surface.faces), "dofs": result.dofs,
        "maximum_edge_m": lip.maximum_edge_m, "target_edge_m": lip.target_edge_m,
        "minimum_angle_deg": lip.minimum_angle_deg,
        "maximum_aspect_ratio": lip.maximum_aspect_ratio,
        "iterations": result.gmres_iterations,
        "linear_solver": ("dense_lu" if result.gmres_iterations == 0 else "gmres"),
        "settings": settings.__dict__, "incident_model": FREE_FIELD_MODEL,
        "scattering_model": LOCAL_LIP_MODEL,
    }
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    figure, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True, constrained_layout=True)
    for axis, plane in zip(axes, ("horizontal", "diagonal", "vertical")):
        incident = result.incident_pressure_pa[plane]
        total = result.total_pressure_pa[plane]
        inc_db = 20 * np.log10(np.maximum(np.abs(incident) / np.max(np.abs(incident)), 1e-15))
        total_db = 20 * np.log10(np.maximum(np.abs(total) / np.max(np.abs(total)), 1e-15))
        axis.plot(angles_deg, inc_db, label="source only")
        axis.plot(angles_deg, total_db, label="source + local lip")
        axis.set(title=plane.title(), xlabel="Angle (degrees)", ylim=(-40, 3))
        axis.grid(True, alpha=0.25)
    axes[0].set_ylabel("Peak-normalized level (dB)")
    axes[1].legend()
    figure.suptitle(f"One-way local-lip scattering at {field.frequency_hz:g} Hz")
    figure.savefig(path / "local_lip_comparison.png", dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("mouth_csv", type=Path)
    parser.add_argument("frequency_hz", type=float)
    parser.add_argument("--retained-depth-mm", type=float, default=50.0)
    parser.add_argument("--elements-per-wavelength", type=float, default=6.0)
    parser.add_argument("--direct-solve-max-dofs", type=int, default=2_500)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = LocalLipSettings(
        retained_depth_m=args.retained_depth_mm * 1e-3,
        elements_per_wavelength=args.elements_per_wavelength,
        direct_solve_max_dofs=args.direct_solve_max_dofs)
    field = read_mfem_mouth_csv(args.mouth_csv, args.frequency_hz)
    lip = build_local_lip_mesh(args.yaml, args.frequency_hz, settings)
    angles = np.arange(-90.0, 91.0)
    result = solve_local_lip(field, lip, angles, settings)
    write_result(args.output_dir, field, lip, result, angles, settings)
    print(args.output_dir)


if __name__ == "__main__":
    main()
