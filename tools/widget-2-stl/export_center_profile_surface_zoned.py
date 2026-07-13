#!/usr/bin/env python3
"""Export a symmetric square-boundary preview mesh for the center-profile surface."""

from __future__ import annotations

import math
from pathlib import Path

import trimesh


OUTPUT = Path(__file__).resolve().parent / "output" / "center_profile_surface_zoned.stl"
Z_STATIONS = 44
SIDE_SAMPLES = 96

PARAMS = {
    "length": 200.0,
    "r0": 12.7,
    "throat_angle": 0.0,
    "throat_extension": 0.0,
    "mouth_width": 380.0,
    "mouth_height": 250.0,
    "h_coverage": 45.0,
    "h_k": 4.0,
    "h_n": 10.0,
    "v_coverage": 30.0,
    "v_k": 4.0,
    "v_n": 10.0,
    "mouth_sag": 60.0,
    "mouth_sag_h_enabled": True,
    "mouth_sag_v_enabled": True,
    "mouth_rear_offset": 6.0,
    "mount_diameter": 120.0,
    "mount_flange_thickness": 12.0,
    "throat_start_wall": 6.0,
    "minimum_wall": 6.0,
    "stl_export_mode": "body",
    "h_modifier_enabled": False,
    "v_modifier_enabled": False,
    "section_shape_1": 0.72,
    "squareness_morph_spline": [
        {"x": 0.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
        {"x": 1.0, "y": 1.0, "angle": 0.0, "tension": 0.35},
    ],
    "h_modifier_thickness_spline": [
        {"x": 0.0, "y": 1.0, "angle": 0.0, "tension": 0.35},
        {"x": 1.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
    ],
    "h_modifier_profile_spline": [
        {"x": 0.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
        {"x": 1.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
    ],
    "v_modifier_thickness_spline": [
        {"x": 0.0, "y": 1.0, "angle": 0.0, "tension": 0.35},
        {"x": 1.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
    ],
    "v_modifier_profile_spline": [
        {"x": 0.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
        {"x": 1.0, "y": 0.0, "angle": 0.0, "tension": 0.35},
    ],
}


def osse_base_radius(z: float, length: float, r0: float, coverage: float, k: float, throat_angle: float = 0.0) -> float:
    alpha = math.tan(math.radians(coverage))
    return r0 + z * math.tan(math.radians(throat_angle)) + math.sqrt(k * k * r0 * r0 + z * z * alpha * alpha) - k * r0


def termination_unit(z: float, length: float, q: float, n: float) -> float:
    inner = max(1.0 - (q * z / length) ** n, 0.0)
    return (length / q) * (1.0 - inner ** (1.0 / n))


def solved_s(length: float, r0: float, coverage: float, k: float, n: float, end_radius: float, throat_angle: float = 0.0) -> float:
    base = osse_base_radius(length, length, r0, coverage, k, throat_angle)
    unit = termination_unit(length, length, 0.995, n)
    return 0.0 if abs(unit) < 1e-9 else (end_radius - base) / unit


def osse_radius(z: float, length: float, r0: float, coverage: float, k: float, n: float, s: float, throat_angle: float = 0.0) -> float:
    return osse_base_radius(z, length, r0, coverage, k, throat_angle) + s * termination_unit(z, length, 0.995, n)


def effective_throat_radius() -> float:
    return PARAMS["r0"] + max(0.0, PARAMS["throat_extension"]) * math.tan(math.radians(PARAMS["throat_angle"]))


def measured_length() -> float:
    return PARAMS["length"] + max(0.0, PARAMS["throat_extension"])


def profile(axis: str):
    coverage = PARAMS[f"{axis}_coverage"]
    k = PARAMS[f"{axis}_k"]
    n = PARAMS[f"{axis}_n"]
    end_radius = PARAMS["mouth_width"] / 2.0 if axis == "h" else PARAMS["mouth_height"] / 2.0
    r0 = effective_throat_radius()
    s = solved_s(PARAMS["length"], r0, coverage, k, n, end_radius, PARAMS["throat_angle"])
    return lambda z: osse_radius(z, PARAMS["length"], r0, coverage, k, n, s, PARAMS["throat_angle"])


def adaptive_profile_z_samples(
    count: int,
    length: float,
    h_profile,
    v_profile,
) -> list[float]:
    if count <= 1:
        return [0.0]
    dense_count = max(count * 24, 1024)
    dense_z = [length * i / (dense_count - 1) for i in range(dense_count)]
    cumulative = [0.0]
    throat_span = min(length * 0.16, max(length * 0.035, effective_throat_radius() * 4.0))
    throat_weight = (
        2.0
        * max(abs(h_profile(length) - h_profile(0.0)), abs(v_profile(length) - v_profile(0.0)))
        / max(length, 1e-9)
    )
    for i in range(1, dense_count):
        prev_z = dense_z[i - 1]
        z = dense_z[i]
        profile_delta = max(
            abs(h_profile(z) - h_profile(prev_z)),
            abs(v_profile(z) - v_profile(prev_z)),
        )
        mid_z = (prev_z + z) / 2.0
        throat_t = max(0.0, min(1.0, mid_z / max(throat_span, 1e-9)))
        throat_fade = (1.0 - throat_t * throat_t) ** 2
        delta = profile_delta + throat_weight * throat_fade * (z - prev_z)
        cumulative.append(cumulative[-1] + delta)

    total = cumulative[-1]
    if total <= 1e-9:
        return [length * i / (count - 1) for i in range(count)]

    samples = []
    cursor = 0
    for i in range(count):
        target = total * i / (count - 1)
        while cursor < dense_count - 2 and cumulative[cursor + 1] < target:
            cursor += 1
        span = max(1e-12, cumulative[cursor + 1] - cumulative[cursor])
        t = max(0.0, min(1.0, (target - cumulative[cursor]) / span))
        samples.append(dense_z[cursor] + (dense_z[cursor + 1] - dense_z[cursor]) * t)
    samples[0] = 0.0
    samples[-1] = length
    return samples


def cubic_bezier_point(a: dict[str, float], b: dict[str, float], t: float) -> tuple[float, float]:
    dx = max(1e-9, b["x"] - a["x"])
    a_length = max(0.0, a["tension"]) * dx
    b_length = max(0.0, b["tension"]) * dx
    p0 = (a["x"], a["y"])
    p1 = (a["x"] + math.cos(a["angle"]) * a_length, a["y"] + math.sin(a["angle"]) * a_length)
    p2 = (b["x"] - math.cos(b["angle"]) * b_length, b["y"] - math.sin(b["angle"]) * b_length)
    p3 = (b["x"], b["y"])
    u = 1.0 - t
    x = u**3 * p0[0] + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t**3 * p3[1]
    return x, y


def spline_value(u: float, anchors: list[dict[str, float]], clamp_y: bool = True) -> float:
    x = max(0.0, min(1.0, u))
    for index, anchor in enumerate(anchors[:-1]):
        next_anchor = anchors[index + 1]
        if x <= next_anchor["x"] or index == len(anchors) - 2:
            lo = 0.0
            hi = 1.0
            for _ in range(18):
                mid = (lo + hi) / 2.0
                point_x, _ = cubic_bezier_point(anchor, next_anchor, mid)
                if point_x < x:
                    lo = mid
                else:
                    hi = mid
            _, y = cubic_bezier_point(anchor, next_anchor, (lo + hi) / 2.0)
            return max(0.0, min(1.0, y)) if clamp_y else y
    return anchors[-1]["y"]


def section_shape(z: float) -> float:
    return spline_value(z / max(measured_length(), 1e-9), PARAMS["squareness_morph_spline"]) * PARAMS["section_shape_1"]


def modifier_thickness_value(axis: str, u: float) -> float:
    return spline_value(u, PARAMS[f"{axis}_modifier_thickness_spline"])


def modifier_delta(axis: str, z: float, basis_radius: float) -> float:
    if not PARAMS.get(f"{axis}_modifier_enabled", False):
        return 0.0
    return spline_value(z / max(PARAMS["length"], 1e-9), PARAMS[f"{axis}_modifier_profile_spline"], False)


def superellipse_n(shape: float) -> float:
    return 2.0 + 298.0 * max(0.0, min(1.0, shape)) ** 1.7


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


def radius_from_sag(half_span: float, sag: float) -> float:
    if sag <= 0.0 or half_span <= 0.0:
        return math.inf
    return (half_span * half_span + sag * sag) / (2.0 * sag)


def mouth_sag_reference_distance(mouth_h_radius: float, mouth_v_radius: float) -> float:
    x = mouth_h_radius if PARAMS.get("mouth_sag_h_enabled", True) else 0.0
    y = mouth_v_radius if PARAMS.get("mouth_sag_v_enabled", True) else 0.0
    return math.hypot(x, y)


def mouth_radius(mouth_h_radius: float, mouth_v_radius: float) -> float:
    return radius_from_sag(mouth_sag_reference_distance(mouth_h_radius, mouth_v_radius), max(0.0, PARAMS["mouth_sag"]))


def mouth_setback(x: float, y: float, mouth_h_radius: float, mouth_v_radius: float) -> float:
    radius = mouth_radius(mouth_h_radius, mouth_v_radius)
    if not math.isfinite(radius) or radius <= 0.0:
        return 0.0
    dx = x if PARAMS.get("mouth_sag_h_enabled", True) else 0.0
    dy = y if PARAMS.get("mouth_sag_v_enabled", True) else 0.0
    distance = math.hypot(dx, dy)
    return radius - math.sqrt(max(radius * radius - distance * distance, 0.0))


def scaled_length_z(tau: float, mouth_x: float, mouth_y: float, mouth_h_radius: float, mouth_v_radius: float) -> float:
    local_length = max(1e-9, PARAMS["length"] - mouth_setback(mouth_x, mouth_y, mouth_h_radius, mouth_v_radius))
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
    h_window = u * u * modifier_thickness_value("h", v)
    v_window = v * v * modifier_thickness_value("v", u)
    mouth_fade = 1.0 - max(0.0, min(1.0, profile_z / max(PARAMS["length"], 1e-9))) ** 4.0
    x += (1.0 if x >= 0.0 else -1.0) * modifier_delta("h", profile_z, h_radius) * h_window * mouth_fade
    y += (1.0 if y >= 0.0 else -1.0) * modifier_delta("v", profile_z, v_radius) * v_window * mouth_fade
    return x, y, output_z


def ring_at(
    tau: float,
    h_radius: float,
    v_radius: float,
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[tuple[float, float, float]]:
    profile_z = PARAMS["length"] * tau
    power = superellipse_n(section_shape(max(0.0, PARAMS["throat_extension"]) + profile_z))
    mouth_power = superellipse_n(section_shape(max(0.0, PARAMS["throat_extension"]) + PARAMS["length"]))
    ring: list[tuple[float, float, float]] = []

    for sample in square_boundary_samples():
        x, y = superellipse_from_square_boundary(h_radius, v_radius, power, sample)
        mouth_x, mouth_y = superellipse_from_square_boundary(mouth_h_radius, mouth_v_radius, mouth_power, sample)
        z = scaled_length_z(tau, mouth_x, mouth_y, mouth_h_radius, mouth_v_radius)
        ring.append(section_point_from_xy(h_radius, v_radius, profile_z, z, x, y))

    return ring


def conical_extension_ring(tau: float) -> list[tuple[float, float, float]]:
    extension = max(0.0, PARAMS["throat_extension"])
    radius = PARAMS["r0"] + extension * tau * math.tan(math.radians(PARAMS["throat_angle"]))
    z = -extension + extension * tau
    power = superellipse_n(section_shape(extension * tau))
    ring: list[tuple[float, float, float]] = []
    for sample in square_boundary_samples():
        x, y = superellipse_from_square_boundary(radius, radius, power, sample)
        ring.append((x, y, z))
    return ring


def concentric_rear_mouth_point(
    point: tuple[float, float, float],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> tuple[float, float, float]:
    offset = max(0.0, PARAMS["mouth_rear_offset"])
    radius = mouth_radius(mouth_h_radius, mouth_v_radius)
    x, y, z = point
    if offset <= 0.0:
        return point
    if not math.isfinite(radius) or radius <= 0.0:
        return x, y, PARAMS["length"] - offset

    center_z = PARAMS["length"] - radius
    vector = (
        x if PARAMS.get("mouth_sag_h_enabled", True) else 0.0,
        y if PARAMS.get("mouth_sag_v_enabled", True) else 0.0,
        z - center_z,
    )
    length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])
    if length <= 1e-12:
        return x, y, z
    scale = max(1e-6, radius - offset) / length
    return (
        vector[0] * scale if PARAMS.get("mouth_sag_h_enabled", True) else x,
        vector[1] * scale if PARAMS.get("mouth_sag_v_enabled", True) else y,
        center_z + vector[2] * scale,
    )


def mouth_rear_ring(
    rings: list[list[tuple[float, float, float]]],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[tuple[float, float, float]]:
    if len(rings) < 2:
        return []
    mouth = rings[-1]
    return [concentric_rear_mouth_point(point, mouth_h_radius, mouth_v_radius) for point in mouth]


def normalize_vector(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 1e-12:
        return 0.0, 0.0, 1.0
    return v[0] / length, v[1] / length, v[2] / length


def normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return normalize_vector((uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx))


def expected_outward_normal(
    segment_index: int,
    center: tuple[float, float, float],
    mouth_index: int,
    mouth_center_z: float,
) -> tuple[float, float, float]:
    if segment_index == mouth_index:
        return normalize_vector((
            center[0] if PARAMS.get("mouth_sag_h_enabled", True) else 0.0,
            center[1] if PARAMS.get("mouth_sag_v_enabled", True) else 0.0,
            center[2] - mouth_center_z,
        ))
    return normalize_vector((center[0], center[1], 0.0))


def dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def radial_distance(point: tuple[float, float, float]) -> float:
    return math.hypot(point[0], point[1])


def radial_offset_point(point: tuple[float, float, float], thickness: float) -> tuple[float, float, float]:
    radius = radial_distance(point)
    if radius <= 1e-12:
        return point[0] + thickness, point[1], point[2]
    return (
        point[0] + point[0] / radius * thickness,
        point[1] + point[1] / radius * thickness,
        point[2],
    )


def vector_subtract(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def vector_cross(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def smooth_cyclic_values(values: list[float], passes: int = 2) -> list[float]:
    smoothed = values[:]
    count = len(smoothed)
    for _ in range(passes):
        smoothed = [
            0.25 * smoothed[(index - 1) % count]
            + 0.5 * smoothed[index]
            + 0.25 * smoothed[(index + 1) % count]
            for index in range(count)
        ]
    return smoothed


def station_scalar_offset_outer_rings(
    rings: list[list[tuple[float, float, float]]],
    mouth_index: int,
    mouth_h: float,
    mouth_v: float,
) -> list[list[tuple[float, float, float]]]:
    horn_rings = rings[: mouth_index + 1]
    ring_count = len(horn_rings)
    ring_size = len(horn_rings[0])
    radius = mouth_radius(mouth_h, mouth_v)
    mouth_center_z = PARAMS["length"] - radius if math.isfinite(radius) else PARAMS["length"]
    scalar_rings = []

    for i, ring in enumerate(horn_rings):
        if i == 0:
            longitudinal = [
                vector_subtract(horn_rings[1][j], ring[j]) if ring_count > 1 else (0.0, 0.0, 1.0)
                for j in range(ring_size)
            ]
        elif i == ring_count - 1:
            longitudinal = [vector_subtract(ring[j], horn_rings[i - 1][j]) for j in range(ring_size)]
        else:
            longitudinal = [vector_subtract(horn_rings[i + 1][j], horn_rings[i - 1][j]) for j in range(ring_size)]

        thickness = wall_thickness_at_ring(i, len(rings))
        scalars = []
        for j, point in enumerate(ring):
            circumferential = vector_subtract(ring[(j + 1) % ring_size], ring[(j - 1) % ring_size])
            candidate = normalize_vector(vector_cross(circumferential, longitudinal[j]))
            expected = expected_outward_normal(i, point, mouth_index, mouth_center_z)
            if dot(candidate, expected) < 0.0:
                candidate = (-candidate[0], -candidate[1], -candidate[2])
            xy = math.hypot(candidate[0], candidate[1])
            slope_factor = 1.0 / max(xy, 1e-6)
            scalars.append(max(thickness, min(thickness * 1.5, thickness * slope_factor)))

        scalar_rings.append(smooth_cyclic_values(scalars, 8))

    for _ in range(3):
        scalar_rings = [
            [
                0.25 * scalar_rings[max(0, i - 1)][j]
                + 0.5 * scalar_rings[i][j]
                + 0.25 * scalar_rings[min(ring_count - 1, i + 1)][j]
                for j in range(ring_size)
            ]
            for i in range(ring_count)
        ]

    return [
        [
            radial_offset_point(point, scalars[j])
            for j, point in enumerate(ring)
        ]
        for ring, scalars in zip(horn_rings, scalar_rings)
    ]


def project_point_to_mouth_radius(
    point: tuple[float, float, float],
    mouth_h_radius: float,
    mouth_v_radius: float,
    target_radius: float,
) -> tuple[float, float, float]:
    radius = mouth_radius(mouth_h_radius, mouth_v_radius)
    x, y, z = point
    if not math.isfinite(radius) or radius <= 0.0:
        return x, y, PARAMS["length"] - max(0.0, PARAMS["mouth_rear_offset"])
    center_z = PARAMS["length"] - radius
    vector = (
        x if PARAMS.get("mouth_sag_h_enabled", True) else 0.0,
        y if PARAMS.get("mouth_sag_v_enabled", True) else 0.0,
        z - center_z,
    )
    length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])
    if length <= 1e-12:
        return x, y, z
    scale = max(1e-6, target_radius) / length
    return (
        vector[0] * scale if PARAMS.get("mouth_sag_h_enabled", True) else x,
        vector[1] * scale if PARAMS.get("mouth_sag_v_enabled", True) else y,
        center_z + vector[2] * scale,
    )


def mouth_return_projected_ring(
    ring: list[tuple[float, float, float]],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[tuple[float, float, float]]:
    return [
        project_point_to_mouth_radius(point, mouth_h_radius, mouth_v_radius, mouth_outer_return_target_radius(mouth_h_radius, mouth_v_radius))
        for point in ring
    ]


def mouth_outer_return_target_radius(mouth_h_radius: float, mouth_v_radius: float) -> float:
    radius = mouth_radius(mouth_h_radius, mouth_v_radius)
    if not math.isfinite(radius):
        return math.inf
    return max(
        1e-6,
        radius - max(0.0, PARAMS["mouth_rear_offset"]) - max(0.0, PARAMS["minimum_wall"]),
    )


def mouth_surface_vector(point: tuple[float, float, float], mouth_h_radius: float, mouth_v_radius: float) -> tuple[float, float, float]:
    radius = mouth_radius(mouth_h_radius, mouth_v_radius)
    center_z = PARAMS["length"] - radius if math.isfinite(radius) else PARAMS["length"]
    return (
        point[0] if PARAMS.get("mouth_sag_h_enabled", True) else 0.0,
        point[1] if PARAMS.get("mouth_sag_v_enabled", True) else 0.0,
        point[2] - center_z,
    )


def mouth_surface_distance(point: tuple[float, float, float], mouth_h_radius: float, mouth_v_radius: float) -> float:
    vector = mouth_surface_vector(point, mouth_h_radius, mouth_v_radius)
    return math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])


def interpolate_point(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    t: float,
) -> tuple[float, float, float]:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def mouth_intersection_path(
    outer_rings: list[list[tuple[float, float, float]]],
    column: int,
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[tuple[float, float, float]]:
    target_radius = mouth_outer_return_target_radius(mouth_h_radius, mouth_v_radius)
    path = [outer_rings[0][column]]
    if not math.isfinite(target_radius):
        return [ring[column] for ring in outer_rings]

    for i in range(len(outer_rings) - 1):
        a = outer_rings[i][column]
        b = outer_rings[i + 1][column]
        da = mouth_surface_distance(a, mouth_h_radius, mouth_v_radius)
        db = mouth_surface_distance(b, mouth_h_radius, mouth_v_radius)
        if da < target_radius:
            path[-1] = a
        if (da - target_radius) * (db - target_radius) <= 0.0 and abs(db - da) > 1e-12:
            t = max(0.0, min(1.0, (target_radius - da) / (db - da)))
            path.append(interpolate_point(a, b, t))
            return path
        if db < target_radius:
            path.append(b)
    path.append(project_point_to_mouth_radius(outer_rings[-1][column], mouth_h_radius, mouth_v_radius, target_radius))
    return path


def path_lengths(path: list[tuple[float, float, float]]) -> list[float]:
    lengths = [0.0]
    for i in range(1, len(path)):
        lengths.append(lengths[-1] + math.dist(path[i - 1], path[i]))
    return lengths


def point_on_path(
    path: list[tuple[float, float, float]],
    lengths: list[float],
    distance: float,
) -> tuple[float, float, float]:
    if distance <= 0.0 or len(path) == 1:
        return path[0]
    total = lengths[-1]
    if distance >= total:
        return path[-1]
    for i in range(len(lengths) - 1):
        if distance <= lengths[i + 1]:
            span = max(1e-12, lengths[i + 1] - lengths[i])
            return interpolate_point(path[i], path[i + 1], (distance - lengths[i]) / span)
    return path[-1]


def trimmed_outer_rings(
    outer_base_rings: list[list[tuple[float, float, float]]],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[list[tuple[float, float, float]]]:
    ring_count = len(outer_base_rings)
    column_count = len(outer_base_rings[0])
    columns = []
    for column in range(column_count):
        path = mouth_intersection_path(outer_base_rings, column, mouth_h_radius, mouth_v_radius)
        columns.append((path, path_lengths(path)))
    rings = []
    for i in range(ring_count):
        t = i / max(1, ring_count - 1)
        ring = []
        for path, lengths in columns:
            ring.append(point_on_path(path, lengths, lengths[-1] * t))
        rings.append(ring)
    return rings


def wall_thickness_at_ring(index: int, ring_count: int) -> float:
    denominator = max(1, ring_count - 1)
    t = index / denominator
    start = max(0.0, PARAMS["throat_start_wall"])
    minimum = max(0.0, PARAMS["minimum_wall"])
    return max(minimum, start + (minimum - start) * t)


def circle_ring_from_reference(
    reference_ring: list[tuple[float, float, float]],
    radius: float,
    z: float,
) -> list[tuple[float, float, float]]:
    count = len(reference_ring)
    ring = []
    for index, point in enumerate(reference_ring):
        angle = math.atan2(point[1], point[0]) if radial_distance(point) > 1e-12 else 2.0 * math.pi * index / count
        ring.append((radius * math.cos(angle), radius * math.sin(angle), z))
    return ring


def append_quad_faces(faces: list[tuple[int, int, int]], a0: int, a1: int, b0: int, b1: int) -> None:
    faces.append((a0, b0, b1))
    faces.append((a0, b1, a1))


def append_ring_bridge(
    faces: list[tuple[int, int, int]],
    a_start: int,
    b_start: int,
    count: int,
    reverse: bool = False,
) -> None:
    for j in range(count):
        k = (j + 1) % count
        if reverse:
            append_quad_faces(faces, a_start + j, b_start + j, a_start + k, b_start + k)
        else:
            append_quad_faces(faces, a_start + j, a_start + k, b_start + j, b_start + k)


def signed_volume(vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> float:
    volume = 0.0
    for face in faces:
        a = vertices[face[0]]
        b = vertices[face[1]]
        c = vertices[face[2]]
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    return volume


def edge_entry(face_index: int, a: int, b: int) -> tuple[tuple[int, int], int, int]:
    lo = min(a, b)
    hi = max(a, b)
    direction = 1 if a == lo else -1
    return (lo, hi), face_index, direction


def orient_closed_faces(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    edge_map: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face_index, face in enumerate(faces):
        for key, _, direction in (
            edge_entry(face_index, face[0], face[1]),
            edge_entry(face_index, face[1], face[2]),
            edge_entry(face_index, face[2], face[0]),
        ):
            edge_map.setdefault(key, []).append((face_index, direction))

    signs = [0] * len(faces)
    for start in range(len(faces)):
        if signs[start] != 0:
            continue
        signs[start] = 1
        stack = [start]
        while stack:
            face_index = stack.pop()
            face = faces[face_index]
            for key, _, direction in (
                edge_entry(face_index, face[0], face[1]),
                edge_entry(face_index, face[1], face[2]),
                edge_entry(face_index, face[2], face[0]),
            ):
                for neighbor_index, neighbor_direction in edge_map.get(key, []):
                    if neighbor_index == face_index:
                        continue
                    required = int(-signs[face_index] * direction / neighbor_direction)
                    if signs[neighbor_index] == 0:
                        signs[neighbor_index] = required
                        stack.append(neighbor_index)

    oriented = [
        (face[0], face[2], face[1]) if signs[index] < 0 else face
        for index, face in enumerate(faces)
    ]
    if signed_volume(vertices, oriented) < 0.0:
        oriented = [(face[0], face[2], face[1]) for face in oriented]
    return oriented


def add_ring(vertices: list[tuple[float, float, float]], ring: list[tuple[float, float, float]]) -> int:
    start = len(vertices)
    vertices.extend(ring)
    return start


def average_z(ring: list[tuple[float, float, float]]) -> float:
    return sum(point[2] for point in ring) / len(ring)


def outer_wall_rings_after_mount(
    outer_rings: list[list[tuple[float, float, float]]],
    mount_end_z: float,
) -> list[list[tuple[float, float, float]]]:
    if not outer_rings:
        return []
    if mount_end_z <= average_z(outer_rings[0]):
        return outer_rings
    for index in range(len(outer_rings) - 1):
        z0 = average_z(outer_rings[index])
        z1 = average_z(outer_rings[index + 1])
        if z0 <= mount_end_z <= z1 and abs(z1 - z0) > 1e-12:
            t = max(0.0, min(1.0, (mount_end_z - z0) / (z1 - z0)))
            start_ring = [
                interpolate_point(outer_rings[index][column], outer_rings[index + 1][column], t)
                for column in range(len(outer_rings[index]))
            ]
            return [start_ring, *outer_rings[index + 1 :]]
    return [outer_rings[-1]]


def build_body_mesh(
    rings: list[list[tuple[float, float, float]]],
    mouth_index: int,
    mouth_h: float,
    mouth_v: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    ring_count = len(rings)
    ring_size = len(rings[0])
    has_return = mouth_index < ring_count - 1
    outer_base_rings = station_scalar_offset_outer_rings(rings, mouth_index, mouth_h, mouth_v)
    outer_rings = trimmed_outer_rings(outer_base_rings, mouth_h, mouth_v) if has_return else outer_base_rings
    throat_inner = rings[0]
    throat_z = sum(point[2] for point in throat_inner) / ring_size
    mount_start_z = throat_z
    mount_end_z = throat_z + max(0.0, PARAMS["mount_flange_thickness"])
    outer_wall_rings = outer_wall_rings_after_mount(outer_rings, mount_end_z)
    outer_wall_start = outer_wall_rings[0]
    required_mount_radius = max(
        max(radial_distance(point) for point in outer_wall_start),
        max(radial_distance(point) for point in throat_inner) + max(0.0, PARAMS["minimum_wall"]),
    )
    mount_radius = max(max(0.0, PARAMS["mount_diameter"]) / 2.0, required_mount_radius)
    mount_outer_start = circle_ring_from_reference(throat_inner, mount_radius, mount_start_z)
    mount_outer_end = circle_ring_from_reference(throat_inner, mount_radius, mount_end_z)

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    inner_starts = [add_ring(vertices, ring) for ring in rings]
    outer_wall_starts = [add_ring(vertices, ring) for ring in outer_wall_rings]
    mount_outer_start_start = add_ring(vertices, mount_outer_start)
    mount_outer_end_start = add_ring(vertices, mount_outer_end)

    for i in range(ring_count - 1):
        append_ring_bridge(faces, inner_starts[i], inner_starts[i + 1], ring_size)
    if has_return:
        append_ring_bridge(faces, inner_starts[-1], outer_wall_starts[-1], ring_size)
    else:
        append_ring_bridge(faces, inner_starts[mouth_index], outer_wall_starts[-1], ring_size)
    for i in range(len(outer_wall_starts) - 1, 0, -1):
        append_ring_bridge(faces, outer_wall_starts[i], outer_wall_starts[i - 1], ring_size, True)
    append_ring_bridge(faces, outer_wall_starts[0], mount_outer_end_start, ring_size, True)
    append_ring_bridge(faces, mount_outer_end_start, mount_outer_start_start, ring_size, True)
    append_ring_bridge(faces, mount_outer_start_start, inner_starts[0], ring_size)

    return vertices, orient_closed_faces(vertices, faces)


def build_acoustic_surface_mesh(
    rings: list[list[tuple[float, float, float]]],
    mouth_index: int,
    mouth_h: float,
    mouth_v: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = [point for ring in rings for point in ring]
    faces: list[tuple[int, int, int]] = []
    ring_size = len(rings[0])
    radius = mouth_radius(mouth_h, mouth_v)
    mouth_center_z = PARAMS["length"] - radius if math.isfinite(radius) else PARAMS["length"]
    for i in range(len(rings) - 1):
        row = i * ring_size
        next_row = (i + 1) * ring_size
        for j in range(ring_size):
            k = (j + 1) % ring_size
            a0 = vertices[row + j]
            a1 = vertices[row + k]
            b0 = vertices[next_row + j]
            b1 = vertices[next_row + k]
            center = (
                (a0[0] + a1[0] + b0[0] + b1[0]) / 4.0,
                (a0[1] + a1[1] + b0[1] + b1[1]) / 4.0,
                (a0[2] + a1[2] + b0[2] + b1[2]) / 4.0,
            )
            actual = normal(a0, b0, a1)
            expected = expected_outward_normal(i, center, mouth_index, mouth_center_z)
            if dot(actual, expected) >= 0.0:
                faces.append((row + j, next_row + j, next_row + k))
                faces.append((row + j, next_row + k, row + k))
            else:
                faces.append((row + j, next_row + k, next_row + j))
                faces.append((row + j, row + k, next_row + k))
    return vertices, faces


def main() -> None:
    h_profile = profile("h")
    v_profile = profile("v")
    length = PARAMS["length"]
    mouth_h = h_profile(length)
    mouth_v = v_profile(length)

    rings = []
    extension = max(0.0, PARAMS["throat_extension"])
    if extension > 0.0:
        extension_stations = max(2, round(Z_STATIONS * extension / max(length, 1e-9)) + 1)
        for i in range(extension_stations):
            rings.append(conical_extension_ring(i / (extension_stations - 1)))

    horn_samples = adaptive_profile_z_samples(Z_STATIONS, length, h_profile, v_profile)
    if extension > 0.0:
        horn_samples = horn_samples[1:]
    for profile_z in horn_samples:
        tau = profile_z / max(length, 1e-9)
        rings.append(ring_at(tau, h_profile(profile_z), v_profile(profile_z), mouth_h, mouth_v))

    mouth_index = len(rings) - 1
    if PARAMS["mouth_rear_offset"] > 0.0:
        rings.append(mouth_rear_ring(rings, mouth_h, mouth_v))

    export_mode = PARAMS.get("stl_export_mode", "body")
    if export_mode == "acoustic_surface":
        vertices, faces = build_acoustic_surface_mesh(rings, mouth_index, mouth_h, mouth_v)
    else:
        export_mode = "body"
        vertices, faces = build_body_mesh(rings, mouth_index, mouth_h, mouth_v)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    trimesh.repair.fix_normals(mesh, multibody=True)
    mesh.export(OUTPUT)
    print(OUTPUT)
    print(f"export_mode={export_mode}")
    print(f"inner_rings={len(rings)} vertices_per_ring={len(rings[0])} vertices={len(mesh.vertices)} triangles={len(mesh.faces)}")
    print(f"watertight={mesh.is_watertight} winding_consistent={mesh.is_winding_consistent} components={len(mesh.split(only_watertight=False))}")


if __name__ == "__main__":
    main()
