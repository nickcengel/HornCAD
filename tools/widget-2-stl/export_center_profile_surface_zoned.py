#!/usr/bin/env python3
"""Export an x-sampled preview mesh for the center-profile surface.

Unlike the widget/export_center_profile_surface_working.py path, this samples
the upper and lower section halves by x. The cylindrical mouth setback is
handled as a local-length scale per x-line instead of as a post-profile z warp.
"""

from __future__ import annotations

import math
from pathlib import Path

import export_center_profile_surface_working as base
import trimesh


OUTPUT = Path(__file__).resolve().parent / "output" / "center_profile_surface_zoned.stl"
Z_STATIONS = 44
HALF_SAMPLES = 192


def superellipse_y(a: float, b: float, power: float, x: float, sign: float) -> float:
    if a <= 0.0 or b <= 0.0:
        return 0.0
    u = min(1.0, abs(x) / a)
    return sign * b * max(0.0, 1.0 - u**power) ** (1.0 / power)


def superellipse_x(a: float, b: float, power: float, y: float, sign: float) -> float:
    if a <= 0.0 or b <= 0.0:
        return 0.0
    v = min(1.0, abs(y) / b)
    return sign * a * max(0.0, 1.0 - v**power) ** (1.0 / power)


def scaled_length_z(tau: float, mouth_x: float, mouth_h_radius: float) -> float:
    local_length = max(1e-9, base.PARAMS["length"] - base.cylindrical_mouth_setback(mouth_x, mouth_h_radius))
    return tau * local_length


def ring_at(tau: float, h_radius: float, v_radius: float, mouth_h_radius: float) -> list[tuple[float, float, float]]:
    profile_z = base.PARAMS["length"] * tau
    power = base.superellipse_n(base.section_shape(max(0.0, base.PARAMS["throat_extension"]) + profile_z))
    ring: list[tuple[float, float, float]] = []

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        mouth_x = -mouth_h_radius + 2.0 * mouth_h_radius * t
        z = scaled_length_z(tau, mouth_x, mouth_h_radius)
        x = -h_radius + 2.0 * h_radius * t
        y = superellipse_y(h_radius, v_radius, power, x, 1.0)
        ring.append((x, y, z))

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        mouth_t = 1.0 - t
        mouth_x = -mouth_h_radius + 2.0 * mouth_h_radius * mouth_t
        z = scaled_length_z(tau, mouth_x, mouth_h_radius)
        x = h_radius - 2.0 * h_radius * t
        y = superellipse_y(h_radius, v_radius, power, x, -1.0)
        ring.append((x, y, z))

    return ring


def conical_extension_ring(tau: float) -> list[tuple[float, float, float]]:
    extension = max(0.0, base.PARAMS["throat_extension"])
    radius = base.PARAMS["r0"] + extension * tau * math.tan(math.radians(base.PARAMS["throat_angle"]))
    z = -extension + extension * tau
    power = base.superellipse_n(base.section_shape(extension * tau))
    ring: list[tuple[float, float, float]] = []

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        x = -radius + 2.0 * radius * t
        y = superellipse_y(radius, radius, power, x, 1.0)
        ring.append((x, y, z))

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        x = radius - 2.0 * radius * t
        y = superellipse_y(radius, radius, power, x, -1.0)
        ring.append((x, y, z))

    return ring


def main() -> None:
    h_profile = base.profile("h")
    v_profile = base.profile("v")
    length = base.PARAMS["length"]
    mouth_h = h_profile(length)

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
        rings.append(ring_at(tau, h_profile(profile_z), v_profile(profile_z), mouth_h))

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
