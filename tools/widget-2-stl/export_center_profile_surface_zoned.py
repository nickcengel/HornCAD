#!/usr/bin/env python3
"""Export an x-sampled preview mesh for the center-profile surface.

Unlike the widget/export_center_profile_surface_working.py path, this does not
sample section rings by angle. It samples the upper and lower section halves by
x, so the cylindrical mouth setback is represented directly along the long
horizontal mouth spans without overlapping side zones.
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


def surface_z(x: float, z: float, mouth_h_radius: float) -> float:
    progress = max(0.0, min(1.0, z / max(base.PARAMS["length"], 1e-9))) ** 2.4
    return z - base.cylindrical_mouth_setback(x, mouth_h_radius) * progress


def ring_at(z: float, h_radius: float, v_radius: float, mouth_h_radius: float) -> list[tuple[float, float, float]]:
    power = base.superellipse_n(base.section_shape(z))
    ring: list[tuple[float, float, float]] = []

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        x = -h_radius + 2.0 * h_radius * t
        y = superellipse_y(h_radius, v_radius, power, x, 1.0)
        ring.append((x, y, surface_z(x, z, mouth_h_radius)))

    for i in range(HALF_SAMPLES):
        t = i / HALF_SAMPLES
        x = h_radius - 2.0 * h_radius * t
        y = superellipse_y(h_radius, v_radius, power, x, -1.0)
        ring.append((x, y, surface_z(x, z, mouth_h_radius)))

    return ring


def main() -> None:
    h_profile = base.profile("h")
    v_profile = base.profile("v")
    length = base.PARAMS["length"]
    mouth_h = h_profile(length)

    rings = []
    for i in range(Z_STATIONS):
        z = length * i / (Z_STATIONS - 1)
        rings.append(ring_at(z, h_profile(z), v_profile(z), mouth_h))

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
