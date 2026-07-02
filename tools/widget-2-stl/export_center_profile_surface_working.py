#!/usr/bin/env python3
"""Export the current Center Profile Surface Explorer defaults as an STL."""

from __future__ import annotations

import math
from pathlib import Path
import struct


PARAMS = {
    "length": 321.0,
    "r0": 12.7,
    "mouth_width": 583.0,
    "mouth_height": 280.0,
    "h_coverage": 32.4,
    "h_k": 1.0,
    "h_n": 2.0,
    "v_coverage": 14.6,
    "v_k": 3.0,
    "v_n": 5.5,
    "mouth_sag": 63.0,
    "section_shape_1": 0.72,
    "shape_end": 0.65,
    "side_bow": 0.0,
    "top_bottom_bow": 0.0,
    "bow_end": 0.53,
    "density": 40,
}


def smoothstep(t: float) -> float:
    x = max(0.0, min(1.0, t))
    return x * x * (3.0 - 2.0 * x)


def osse_base_radius(z: float, length: float, r0: float, coverage: float, k: float) -> float:
    alpha = math.tan(math.radians(coverage))
    return math.sqrt(k * k * r0 * r0 + z * z * alpha * alpha) + r0 * (1.0 - k)


def termination_unit(z: float, length: float, q: float, n: float) -> float:
    inner = max(1.0 - (q * z / length) ** n, 0.0)
    return (length / q) * (1.0 - inner ** (1.0 / n))


def solved_s(length: float, r0: float, coverage: float, k: float, n: float, end_radius: float) -> float:
    base = osse_base_radius(length, length, r0, coverage, k)
    unit = termination_unit(length, length, 0.995, n)
    return 0.0 if abs(unit) < 1e-9 else (end_radius - base) / unit


def osse_radius(z: float, length: float, r0: float, coverage: float, k: float, n: float, s: float) -> float:
    return osse_base_radius(z, length, r0, coverage, k) + s * termination_unit(z, length, 0.995, n)


def profile(axis: str):
    p = PARAMS
    coverage = p[f"{axis}_coverage"]
    k = p[f"{axis}_k"]
    n = p[f"{axis}_n"]
    end_radius = p["mouth_width"] / 2.0 if axis == "h" else p["mouth_height"] / 2.0
    s = solved_s(p["length"], p["r0"], coverage, k, n, end_radius)
    return lambda z: osse_radius(z, p["length"], p["r0"], coverage, k, n, s)


def section_shape(z: float) -> float:
    return smoothstep(z / max(PARAMS["length"] * PARAMS["shape_end"], 1e-9)) * PARAMS["section_shape_1"]


def superellipse_n(shape: float) -> float:
    return 2.0 + 298.0 * max(0.0, min(1.0, shape)) ** 1.7


def superellipse_point(a: float, b: float, n: float, theta: float) -> tuple[float, float]:
    exponent = 2.0 / max(n, 1e-9)
    c = math.cos(theta)
    s = math.sin(theta)
    return (
        a * (1.0 if c >= 0.0 else -1.0) * abs(c) ** exponent,
        b * (1.0 if s >= 0.0 else -1.0) * abs(s) ** exponent,
    )


def theta_from_x(n: float, fraction: float) -> float:
    return math.acos(max(0.0, min(1.0, fraction)) ** (max(n, 1e-9) / 2.0))


def theta_from_y(n: float, fraction: float) -> float:
    return math.asin(max(0.0, min(1.0, fraction)) ** (max(n, 1e-9) / 2.0))


def quadrant_angles(n: float, samples: int) -> list[float]:
    angles = {0.0, math.pi / 2.0}
    count = max(18, samples)
    for i in range(1, count):
        f = i / count
        angles.add((math.pi / 2.0) * f)
        angles.add(theta_from_x(n, f))
        angles.add(theta_from_y(n, f))
    return sorted(angles)


def point_line_distance(point, a, b) -> float:
    ax, ay, az = a
    bx, by, bz = b
    px, py, pz = point
    ab = (bx - ax, by - ay, bz - az)
    ap = (px - ax, py - ay, pz - az)
    cross = (
        ap[1] * ab[2] - ap[2] * ab[1],
        ap[2] * ab[0] - ap[0] * ab[2],
        ap[0] * ab[1] - ap[1] * ab[0],
    )
    length = math.sqrt(ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2])
    if length <= 1e-12:
        return math.sqrt(ap[0] * ap[0] + ap[1] * ap[1] + ap[2] * ap[2])
    return math.sqrt(cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]) / length


def refine_angles_for_mouth(
    angles: list[float],
    h_radius: float,
    v_radius: float,
    mouth_h_radius: float,
    shape_n: float,
) -> list[float]:
    refined = sorted(angles)
    error_limit = 0.12
    chord_limit = max(3.0, mouth_h_radius / 96.0)
    max_angles = 384

    for _ in range(10):
        if len(refined) >= max_angles:
            break
        changed = False
        next_angles = [refined[0]]
        for i in range(len(refined) - 1):
            a_theta = refined[i]
            b_theta = refined[i + 1]
            mid_theta = (a_theta + b_theta) / 2.0
            a = section_point(h_radius, v_radius, PARAMS["length"], a_theta, mouth_h_radius, shape_n)
            b = section_point(h_radius, v_radius, PARAMS["length"], b_theta, mouth_h_radius, shape_n)
            mid = section_point(h_radius, v_radius, PARAMS["length"], mid_theta, mouth_h_radius, shape_n)
            chord = math.dist(a, b)
            error = point_line_distance(mid, a, b)
            if (error > error_limit or chord > chord_limit) and len(next_angles) < max_angles:
                next_angles.append(mid_theta)
                changed = True
            next_angles.append(b_theta)
        refined = next_angles
        if not changed:
            break

    return refined


def radius_from_sag(half_span: float, sag: float) -> float:
    if sag <= 0.0:
        return math.inf
    return (half_span * half_span + sag * sag) / (2.0 * sag)


def setback_from_radius(distance: float, radius: float) -> float:
    if not math.isfinite(radius) or radius <= 0.0:
        return 0.0
    return radius - math.sqrt(max(radius * radius - distance * distance, 0.0))


def cylindrical_mouth_setback(x: float, max_x: float) -> float:
    sag = max(0.0, PARAMS["mouth_sag"])
    if sag <= 0.0 or max_x <= 0.0:
        return 0.0
    return setback_from_radius(abs(x), radius_from_sag(max_x, sag))


def bow_progress(z: float) -> float:
    return smoothstep(z / max(PARAMS["length"] * PARAMS["bow_end"], 1e-9))


def section_point(h_radius: float, v_radius: float, z: float, theta: float, mouth_h_radius: float, shape_n: float) -> tuple[float, float, float]:
    x, y = superellipse_point(h_radius, v_radius, shape_n, theta)
    u = min(1.0, abs(x) / max(h_radius, 1e-9))
    v = min(1.0, abs(y) / max(v_radius, 1e-9))
    progress = bow_progress(z)
    side_window = u * u * (1.0 - v * v)
    top_bottom_window = v * v * (1.0 - u * u)
    mouth_fade = 1.0 - max(0.0, min(1.0, z / max(PARAMS["length"], 1e-9))) ** 4.0
    x += (1.0 if (x or math.cos(theta)) >= 0.0 else -1.0) * PARAMS["side_bow"] * progress * side_window * mouth_fade
    y += (1.0 if (y or math.sin(theta)) >= 0.0 else -1.0) * PARAMS["top_bottom_bow"] * progress * top_bottom_window * mouth_fade
    mouth_progress = max(0.0, min(1.0, z / max(PARAMS["length"], 1e-9))) ** 2.4
    return x, y, z - cylindrical_mouth_setback(x, mouth_h_radius) * mouth_progress


def mirrored_ring(h_radius: float, v_radius: float, z: float, angles: list[float], mouth_h_radius: float) -> list[tuple[float, float, float]]:
    shape_n = superellipse_n(section_shape(z))
    base = []
    for theta in angles:
        x, y, z_out = section_point(h_radius, v_radius, z, theta, mouth_h_radius, shape_n)
        base.append((abs(x), abs(y), z_out))

    ring = []
    last = len(base) - 1
    ring.extend(base)
    ring.extend((-base[i][0], base[i][1], base[i][2]) for i in range(last - 1, -1, -1))
    ring.extend((-base[i][0], -base[i][1], base[i][2]) for i in range(1, last + 1))
    ring.extend((base[i][0], -base[i][1], base[i][2]) for i in range(last - 1, 0, -1))
    return ring


def normal(a, b, c) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def write_stl(path: Path, triangles: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]) -> None:
    header = b"center_profile_surface_working preview".ljust(80, b" ")
    with path.open("wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            nx, ny, nz = normal(*tri)
            values = [nx, ny, nz]
            for vertex in tri:
                values.extend(vertex)
            f.write(struct.pack("<12fH", *values, 0))


def main() -> None:
    h_profile = profile("h")
    v_profile = profile("v")
    mouth_h = h_profile(PARAMS["length"])
    mouth_v = v_profile(PARAMS["length"])
    mouth_n = superellipse_n(section_shape(PARAMS["length"]))
    angles = refine_angles_for_mouth(
        quadrant_angles(superellipse_n(PARAMS["section_shape_1"]), PARAMS["density"] * 4),
        mouth_h,
        mouth_v,
        mouth_h,
        mouth_n,
    )

    rings = []
    for i in range(PARAMS["density"]):
        z = PARAMS["length"] * i / (PARAMS["density"] - 1)
        rings.append(mirrored_ring(h_profile(z), v_profile(z), z, angles, mouth_h))

    triangles = []
    for i in range(len(rings) - 1):
        a = rings[i]
        b = rings[i + 1]
        count = len(a)
        for j in range(count):
            j_next = (j + 1) % count
            triangles.append((a[j], b[j], b[j_next]))
            triangles.append((a[j], b[j_next], a[j_next]))

    output = Path(__file__).resolve().parent / "output" / "center_profile_surface_working.stl"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_stl(output, triangles)
    print(output)
    print(f"rings={len(rings)} vertices_per_ring={len(rings[0])} triangles={len(triangles)}")


if __name__ == "__main__":
    main()
