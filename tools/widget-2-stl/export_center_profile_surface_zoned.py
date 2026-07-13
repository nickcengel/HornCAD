#!/usr/bin/env python3
"""Export a symmetric square-boundary preview mesh for the center-profile surface."""

from __future__ import annotations

import math
from pathlib import Path

import export_center_profile_surface_working as base
import trimesh


OUTPUT = Path(__file__).resolve().parent / "output" / "center_profile_surface_zoned.stl"
Z_STATIONS = 44
SIDE_SAMPLES = 96


def square_boundary_samples() -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    for i in range(SIDE_SAMPLES):
        t = i / SIDE_SAMPLES
        samples.append((-1.0 + 2.0 * t, 1.0))
    for i in range(SIDE_SAMPLES):
        t = i / SIDE_SAMPLES
        samples.append((1.0, 1.0 - 2.0 * t))
    for i in range(SIDE_SAMPLES):
        t = i / SIDE_SAMPLES
        samples.append((1.0 - 2.0 * t, -1.0))
    for i in range(SIDE_SAMPLES):
        t = i / SIDE_SAMPLES
        samples.append((-1.0, -1.0 + 2.0 * t))
    return samples


def superellipse_from_square_boundary(
    h_radius: float,
    v_radius: float,
    power: float,
    sample: tuple[float, float],
) -> tuple[float, float]:
    sx, sy = sample
    n = max(power, 1e-9)
    denom = (abs(sx) ** n + abs(sy) ** n) ** (1.0 / n)
    if denom <= 1e-12:
        return 0.0, 0.0
    return h_radius * sx / denom, v_radius * sy / denom


def scaled_length_z(tau: float, mouth_x: float, mouth_h_radius: float) -> float:
    local_length = max(1e-9, base.PARAMS["length"] - base.cylindrical_mouth_setback(mouth_x, mouth_h_radius))
    return tau * local_length


def section_point_from_xy(
    h_radius: float,
    v_radius: float,
    profile_z: float,
    output_z: float,
    x: float,
    y: float,
) -> tuple[float, float, float]:
    u = min(1.0, abs(x) / max(h_radius, 1e-9))
    v = min(1.0, abs(y) / max(v_radius, 1e-9))
    h_window = u * u * base.modifier_thickness_value("h", v)
    v_window = v * v * base.modifier_thickness_value("v", u)
    mouth_fade = 1.0 - max(0.0, min(1.0, profile_z / max(base.PARAMS["length"], 1e-9))) ** 4.0
    x += (1.0 if x >= 0.0 else -1.0) * base.modifier_delta("h", profile_z, h_radius) * h_window * mouth_fade
    y += (1.0 if y >= 0.0 else -1.0) * base.modifier_delta("v", profile_z, v_radius) * v_window * mouth_fade
    return x, y, output_z


def ring_at(
    tau: float,
    h_radius: float,
    v_radius: float,
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[tuple[float, float, float]]:
    profile_z = base.PARAMS["length"] * tau
    power = base.superellipse_n(base.section_shape(max(0.0, base.PARAMS["throat_extension"]) + profile_z))
    mouth_power = base.superellipse_n(base.section_shape(max(0.0, base.PARAMS["throat_extension"]) + base.PARAMS["length"]))
    ring: list[tuple[float, float, float]] = []

    for sample in square_boundary_samples():
        x, y = superellipse_from_square_boundary(h_radius, v_radius, power, sample)
        mouth_x, _ = superellipse_from_square_boundary(mouth_h_radius, mouth_v_radius, mouth_power, sample)
        z = scaled_length_z(tau, mouth_x, mouth_h_radius)
        ring.append(section_point_from_xy(h_radius, v_radius, profile_z, z, x, y))

    return ring


def conical_extension_ring(tau: float) -> list[tuple[float, float, float]]:
    extension = max(0.0, base.PARAMS["throat_extension"])
    radius = base.PARAMS["r0"] + extension * tau * math.tan(math.radians(base.PARAMS["throat_angle"]))
    z = -extension + extension * tau
    power = base.superellipse_n(base.section_shape(extension * tau))
    ring: list[tuple[float, float, float]] = []
    for sample in square_boundary_samples():
        x, y = superellipse_from_square_boundary(radius, radius, power, sample)
        ring.append((x, y, z))
    return ring


def main() -> None:
    h_profile = base.profile("h")
    v_profile = base.profile("v")
    length = base.PARAMS["length"]
    mouth_h = h_profile(length)
    mouth_v = v_profile(length)

    rings = []
    extension = max(0.0, base.PARAMS["throat_extension"])
    if extension > 0.0:
        extension_stations = max(2, round(Z_STATIONS * extension / max(length, 1e-9)) + 1)
        for i in range(extension_stations):
            rings.append(conical_extension_ring(i / (extension_stations - 1)))

    horn_start_index = 1 if extension > 0.0 else 0
    for i in range(horn_start_index, Z_STATIONS):
        tau = i / (Z_STATIONS - 1)
        profile_z = length * tau
        rings.append(ring_at(tau, h_profile(profile_z), v_profile(profile_z), mouth_h, mouth_v))

    vertices = [point for ring in rings for point in ring]
    faces = []
    ring_size = len(rings[0])
    for i in range(len(rings) - 1):
        row = i * ring_size
        next_row = (i + 1) * ring_size
        for j in range(ring_size):
            k = (j + 1) % ring_size
            faces.append((row + j, next_row + k, next_row + j))
            faces.append((row + j, row + k, next_row + k))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    trimesh.repair.fix_normals(mesh, multibody=True)
    mesh.export(OUTPUT)
    print(OUTPUT)
    print(f"rings={len(rings)} vertices_per_ring={ring_size} triangles={len(mesh.faces)}")
    print(f"watertight={mesh.is_watertight} winding_consistent={mesh.is_winding_consistent} components={len(mesh.split(only_watertight=False))}")


if __name__ == "__main__":
    main()
