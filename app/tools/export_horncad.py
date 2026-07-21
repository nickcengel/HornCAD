#!/usr/bin/env python3
"""Export a HornCAD acoustic surface or printable body mesh."""

import argparse
import math
from pathlib import Path

import trimesh
import yaml


OUTPUT_DIR = Path(__file__).resolve().parent / "output"
Z_STATIONS = 44
SIDE_SAMPLES = 160

PARAMS = {
    "length": 250.0,
    "r0": 12.7,
    "throat_angle": 6.0,
    "throat_extension": 30.0,
    "mouth_width": 400.0,
    "mouth_height": 260.0,
    "h_coverage": 45.0,
    "h_k": 10.0,
    "h_n": 10.0,
    "v_coverage": 30.0,
    "v_k": 10.0,
    "v_n": 10.0,
    "mouth_sag": 60.0,
    "mouth_sag_h_enabled": True,
    "mouth_sag_v_enabled": True,
    "mouth_rear_offset": 6.0,
    "mount_diameter": 140.0,
    "mount_flange_thickness": 12.0,
    "throat_start_wall": 6.0,
    "minimum_wall": 6.0,
    "screw_hole_count": 3,
    "screw_hole_diameter": 5.0,
    "screw_pattern_diameter": 110.0,
    "mount_fillet": 12.0,
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


def spline_from_yaml(points: list[dict[str, float]], y_key: str = "y") -> list[dict[str, float]]:
    return [
        {
            "x": float(point.get("x", 0.0)),
            "y": float(point.get(y_key, point.get("y", 0.0))),
            "angle": math.radians(float(point.get("angle_deg", 0.0))),
            "tension": float(point.get("tension", 0.35)),
        }
        for point in points
    ]


def apply_horncad_yaml(path: Path) -> None:
    global Z_STATIONS, SIDE_SAMPLES

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("horncad_config"), dict):
        raise ValueError(f"{path} does not look like a HornCAD YAML file")

    config = data["horncad_config"]
    global_config = config.get("global", {})
    body_config = config.get("body", {})
    h_basis = config.get("horizontal_basis", {})
    v_basis = config.get("vertical_basis", {})
    section_config = config.get("section_modifier", {})
    export_config = config.get("export", {})

    mapping = {
        "length": (global_config, "length"),
        "r0": (global_config, "throat_radius"),
        "throat_angle": (global_config, "throat_angle_deg"),
        "throat_extension": (global_config, "conical_extension_length"),
        "mouth_width": (global_config, "mouth_width"),
        "mouth_height": (global_config, "mouth_height"),
        "mouth_sag": (global_config, "mouth_sag"),
        "mouth_sag_h_enabled": (global_config, "mouth_sag_h_enabled"),
        "mouth_sag_v_enabled": (global_config, "mouth_sag_v_enabled"),
        "mouth_rear_offset": (body_config, "mouth_rear_offset"),
        "mount_diameter": (body_config, "mount_diameter"),
        "mount_flange_thickness": (body_config, "mount_flange_thickness"),
        "throat_start_wall": (body_config, "throat_start_wall_thickness"),
        "minimum_wall": (body_config, "minimum_wall_thickness"),
        "screw_hole_count": (body_config, "screw_hole_count"),
        "screw_hole_diameter": (body_config, "screw_hole_diameter"),
        "screw_pattern_diameter": (body_config, "screw_pattern_diameter"),
        "mount_fillet": (body_config, "mount_fillet"),
        "stl_export_mode": (body_config, "stl_export_mode"),
        "h_coverage": (h_basis, "coverage_deg"),
        "h_k": (h_basis, "k"),
        "h_n": (h_basis, "n"),
        "v_coverage": (v_basis, "coverage_deg"),
        "v_k": (v_basis, "k"),
        "v_n": (v_basis, "n"),
        "section_shape_1": (section_config, "mouth_squareness"),
    }

    for param_name, (source, yaml_name) in mapping.items():
        if yaml_name in source:
            PARAMS[param_name] = source[yaml_name]

    if "squareness_morph_spline" in section_config:
        PARAMS["squareness_morph_spline"] = spline_from_yaml(section_config["squareness_morph_spline"])

    for axis, yaml_name in (("h", "horizontal_modifier"), ("v", "vertical_modifier")):
        modifier = section_config.get(yaml_name, {})
        PARAMS[f"{axis}_modifier_enabled"] = bool(modifier.get("enabled", PARAMS[f"{axis}_modifier_enabled"]))
        if "profile_delta_spline" in modifier:
            PARAMS[f"{axis}_modifier_profile_spline"] = spline_from_yaml(modifier["profile_delta_spline"], "y_mm")
        if "thickness_spline" in modifier:
            PARAMS[f"{axis}_modifier_thickness_spline"] = spline_from_yaml(modifier["thickness_spline"])

    if "stl_z_stations" in export_config:
        Z_STATIONS = max(8, round(float(export_config["stl_z_stations"])))
    if "stl_side_samples" in export_config:
        SIDE_SAMPLES = max(96, round(float(export_config["stl_side_samples"])))


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


def termination_metrics(length: float, r0: float, coverage: float, k: float,
                        n: float, end_radius: float,
                        throat_angle: float = 0.0) -> dict[str, float]:
    """Measure the realized wall termination at the mouth without meshing."""
    s = solved_s(length, r0, coverage, k, n, end_radius, throat_angle)
    step = max(0.01, length * 1e-4)
    samples = [osse_radius(max(0.0, length - index * step), length, r0,
                           coverage, k, n, s, throat_angle) for index in range(4)]
    slope = (3 * samples[0] - 4 * samples[1] + samples[2]) / (2 * step)
    second = (2 * samples[0] - 5 * samples[1] +
              4 * samples[2] - samples[3]) / (step * step)
    curvature = abs(second) / max((1 + slope * slope) ** 1.5, 1e-12)
    radius = math.inf if curvature < 1e-12 else 1.0 / curvature
    return {
        "s": float(s),
        "exit_angle_deg": math.degrees(math.atan(slope)),
        "curvature_radius_mm": float(radius),
        "normalized_curvature_radius": float(radius / max(end_radius, 1e-9)),
    }


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
    def side_t(index: int) -> float:
        u = index / SIDE_SAMPLES
        cosine = 0.5 - 0.5 * math.cos(math.pi * u)
        return 0.35 * u + 0.65 * cosine

    samples: list[tuple[float, float]] = []
    for i in range(SIDE_SAMPLES):
        t = side_t(i)
        samples.append((-1.0 + 2.0 * t, 1.0))
    for i in range(SIDE_SAMPLES):
        t = side_t(i)
        samples.append((1.0, 1.0 - 2.0 * t))
    for i in range(SIDE_SAMPLES):
        t = side_t(i)
        samples.append((1.0 - 2.0 * t, -1.0))
    for i in range(SIDE_SAMPLES):
        t = side_t(i)
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


def screw_hole_centers() -> list[tuple[float, float]]:
    count = max(0, round(float(PARAMS.get("screw_hole_count", 0))))
    diameter = max(0.0, float(PARAMS.get("screw_hole_diameter", 0.0)))
    pattern_radius = max(0.0, float(PARAMS.get("screw_pattern_diameter", 0.0))) / 2.0
    if count <= 0 or diameter <= 0.0 or pattern_radius <= 0.0:
        return []
    start_angle = math.pi / 2.0
    return [
        (
            pattern_radius * math.cos(start_angle + 2.0 * math.pi * index / count),
            pattern_radius * math.sin(start_angle + 2.0 * math.pi * index / count),
        )
        for index in range(count)
    ]


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


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def mouth_envelope_blend_weight(
    point: tuple[float, float, float],
    target: tuple[float, float, float],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> float:
    required = 0.0
    for axis, limit in ((0, mouth_h_radius), (1, mouth_v_radius)):
        point_value = abs(point[axis])
        target_value = abs(target[axis])
        if point_value > limit and point_value > target_value + 1e-12:
            required = max(required, (point_value - limit) / (point_value - target_value))
    return max(0.0, min(1.0, required))


def mouth_constrained_outer_rings(
    inner_horn_rings: list[list[tuple[float, float, float]]],
    outer_base_rings: list[list[tuple[float, float, float]]],
    mouth_boundary_ring: list[tuple[float, float, float]],
    mouth_h_radius: float,
    mouth_v_radius: float,
) -> list[list[tuple[float, float, float]]]:
    ring_count = len(outer_base_rings)
    minimum_wall = max(0.0, PARAMS["minimum_wall"])
    constrained: list[list[tuple[float, float, float]]] = []
    for i, ring in enumerate(outer_base_rings):
        if i == ring_count - 1:
            constrained.append(mouth_boundary_ring)
            continue
        station_t = i / max(1, ring_count - 1)
        station_weight = smoothstep(station_t)
        envelope_weight = max(
            mouth_envelope_blend_weight(base, mouth_boundary, mouth_h_radius, mouth_v_radius)
            for base, mouth_boundary in zip(ring, mouth_boundary_ring)
        )
        weight = max(station_weight, envelope_weight)
        constrained_ring = [
            interpolate_point(base, mouth_boundary, weight)
            for base, mouth_boundary in zip(ring, mouth_boundary_ring)
        ]
        if any(math.dist(inner, point) < minimum_wall for inner, point in zip(inner_horn_rings[i], constrained_ring)):
            low = 0.0
            high = weight
            for _ in range(40):
                mid = (low + high) / 2.0
                candidate_ring = [
                    interpolate_point(base, mouth_boundary, mid)
                    for base, mouth_boundary in zip(ring, mouth_boundary_ring)
                ]
                if all(math.dist(inner, point) >= minimum_wall for inner, point in zip(inner_horn_rings[i], candidate_ring)):
                    low = mid
                else:
                    high = mid
            if low >= envelope_weight:
                constrained_ring = [
                    interpolate_point(base, mouth_boundary, low)
                    for base, mouth_boundary in zip(ring, mouth_boundary_ring)
                ]
        constrained.append(constrained_ring)
    return constrained


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


def compact_mouth_outer_rings(
    outer_rings: list[list[tuple[float, float, float]]],
) -> list[list[tuple[float, float, float]]]:
    if len(outer_rings) <= 2:
        return outer_rings
    # A strongly mouth-constrained profile can reach the rear mouth boundary
    # before its final sampled station. Continuing past that first contact
    # makes the outer wall leave and later return to the exact same ring,
    # producing a self-touching (four-face) seam in STL consumers. The first
    # contact is already the complete outer-wall endpoint.
    def truncate_at_first_mouth_contact(
        rings: list[list[tuple[float, float, float]]],
    ) -> list[list[tuple[float, float, float]]]:
        mouth_ring = rings[-1]
        for index, ring in enumerate(rings[:-1]):
            if max(math.dist(point, mouth) for point, mouth in zip(ring, mouth_ring)) < 1e-9:
                return rings[: index + 1]
        return rings

    outer_rings = truncate_at_first_mouth_contact(outer_rings)
    if len(outer_rings) <= 2:
        return outer_rings
    min_spacing = max(1.0, max(0.0, PARAMS["minimum_wall"]) * 0.25)
    resample_span = max(min_spacing * 8.0, max(0.0, PARAMS["minimum_wall"]) * 4.0)
    segment_lengths = [
        sum(math.dist(a, b) for a, b in zip(outer_rings[i], outer_rings[i + 1])) / max(1, len(outer_rings[i]))
        for i in range(len(outer_rings) - 1)
    ]
    cumulative = [0.0 for _ in outer_rings]
    for i in range(len(outer_rings) - 2, -1, -1):
        cumulative[i] = cumulative[i + 1] + segment_lengths[i]

    start = len(outer_rings) - 1
    while start > 0 and cumulative[start - 1] <= resample_span:
        start -= 1
    if start >= len(outer_rings) - 2:
        return outer_rings

    total = cumulative[start]
    target_count = max(2, math.ceil(total / min_spacing) + 1)
    targets = [total * (target_count - 1 - i) / (target_count - 1) for i in range(target_count)]

    def ring_at_distance(distance_from_mouth: float) -> list[tuple[float, float, float]]:
        for index in range(start, len(outer_rings) - 1):
            if cumulative[index] >= distance_from_mouth >= cumulative[index + 1]:
                span = max(1e-12, cumulative[index] - cumulative[index + 1])
                t = (cumulative[index] - distance_from_mouth) / span
                return [
                    interpolate_point(outer_rings[index][column], outer_rings[index + 1][column], t)
                    for column in range(len(outer_rings[index]))
                ]
        return outer_rings[-1]

    compacted = [*outer_rings[:start], *[ring_at_distance(target) for target in targets]]
    return truncate_at_first_mouth_contact(compacted)


def mount_fillet_arc_rings(
    outer_wall_start: list[tuple[float, float, float]],
    mount_end_z: float,
) -> list[list[tuple[float, float, float]]]:
    fillet = max(0.0, float(PARAMS.get("mount_fillet", 0.0)))
    if fillet <= 1e-9:
        return []
    import cadquery as cq

    steps = max(3, min(18, round(fillet / 1.5) + 2))
    arc = cq.Edge.makeCircle(
        fillet,
        cq.Vector(0.0, 0.0, 0.0),
        cq.Vector(0.0, 0.0, 1.0),
        180.0,
        270.0,
    )
    rings: list[list[tuple[float, float, float]]] = []
    for index in range(1, steps):
        t = index / steps
        offset = arc.positionAt(t)
        ring: list[tuple[float, float, float]] = []
        for outer_point in outer_wall_start:
            outer_radius = radial_distance(outer_point)
            if outer_radius <= 1e-12:
                unit_x, unit_y = 1.0, 0.0
            else:
                unit_x, unit_y = outer_point[0] / outer_radius, outer_point[1] / outer_radius
            radius = outer_radius + fillet + offset.x
            z = mount_end_z + fillet + offset.y
            ring.append((unit_x * radius, unit_y * radius, z))
        rings.append(ring)
    return rings


def mount_fillet_foot_ring(
    outer_wall_start: list[tuple[float, float, float]],
    mount_end_z: float,
) -> list[tuple[float, float, float]]:
    fillet = max(0.0, float(PARAMS.get("mount_fillet", 0.0)))
    if fillet <= 1e-9:
        return outer_wall_start
    foot_ring: list[tuple[float, float, float]] = []
    for outer_point in outer_wall_start:
        outer_radius = radial_distance(outer_point)
        if outer_radius <= 1e-12:
            unit_x, unit_y = 1.0, 0.0
        else:
            unit_x, unit_y = outer_point[0] / outer_radius, outer_point[1] / outer_radius
        radius = outer_radius + fillet
        foot_ring.append((unit_x * radius, unit_y * radius, mount_end_z))
    return foot_ring


def build_body_mesh(
    rings: list[list[tuple[float, float, float]]],
    mouth_index: int,
    mouth_h: float,
    mouth_v: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    ring_count = len(rings)
    ring_size = len(rings[0])
    has_return = mouth_index < ring_count - 1
    inner_rings = rings[: mouth_index + 1] if has_return else rings
    outer_base_rings = station_scalar_offset_outer_rings(rings, mouth_index, mouth_h, mouth_v)
    outer_rings = (
        mouth_constrained_outer_rings(inner_rings, outer_base_rings, rings[-1], mouth_h, mouth_v)
        if has_return
        else outer_base_rings
    )
    throat_inner = rings[0]
    throat_z = sum(point[2] for point in throat_inner) / ring_size
    mount_start_z = throat_z
    mount_end_z = throat_z + max(0.0, PARAMS["mount_flange_thickness"])
    fillet = max(0.0, float(PARAMS.get("mount_fillet", 0.0)))
    outer_wall_start_z = min(PARAMS["length"], mount_end_z + fillet)
    outer_wall_rings = compact_mouth_outer_rings(outer_wall_rings_after_mount(outer_rings, outer_wall_start_z))
    outer_wall_start = outer_wall_rings[0]
    mount_fillet_foot = mount_fillet_foot_ring(outer_wall_start, mount_end_z)
    required_mount_radius = max(
        max(radial_distance(point) for point in mount_fillet_foot),
        max(radial_distance(point) for point in outer_wall_start),
        max(radial_distance(point) for point in throat_inner) + max(0.0, PARAMS["minimum_wall"]),
    )
    mount_radius = max(max(0.0, PARAMS["mount_diameter"]) / 2.0, required_mount_radius)
    mount_outer_start = circle_ring_from_reference(throat_inner, mount_radius, mount_start_z)
    mount_outer_end = circle_ring_from_reference(throat_inner, mount_radius, mount_end_z)

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    inner_starts = [add_ring(vertices, ring) for ring in inner_rings]
    outer_wall_starts = [add_ring(vertices, ring) for ring in outer_wall_rings]
    blend_starts = [
        add_ring(vertices, ring)
        for ring in mount_fillet_arc_rings(outer_wall_start, mount_end_z)
    ]
    mount_fillet_foot_start = add_ring(vertices, mount_fillet_foot)
    mount_outer_start_start = add_ring(vertices, mount_outer_start)
    mount_outer_end_start = add_ring(vertices, mount_outer_end)

    for i in range(len(inner_rings) - 1):
        append_ring_bridge(faces, inner_starts[i], inner_starts[i + 1], ring_size)
    append_ring_bridge(faces, inner_starts[-1], outer_wall_starts[-1], ring_size)
    for i in range(len(outer_wall_starts) - 1, 0, -1):
        append_ring_bridge(faces, outer_wall_starts[i], outer_wall_starts[i - 1], ring_size, True)
    previous_start = outer_wall_starts[0]
    for blend_start in blend_starts:
        append_ring_bridge(faces, previous_start, blend_start, ring_size, True)
        previous_start = blend_start
    append_ring_bridge(faces, previous_start, mount_fillet_foot_start, ring_size, True)
    append_ring_bridge(faces, mount_fillet_foot_start, mount_outer_end_start, ring_size, True)
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


def subtract_mount_screw_holes(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    centers = screw_hole_centers()
    if not centers:
        return mesh

    hole_radius = max(0.0, float(PARAMS["screw_hole_diameter"])) / 2.0
    extension = max(0.0, float(PARAMS["throat_extension"]))
    mount_thickness = max(0.0, float(PARAMS["mount_flange_thickness"]))
    mount_fillet = max(0.0, float(PARAMS.get("mount_fillet", 0.0)))
    start_z = -extension - 1.0
    end_z = -extension + mount_thickness + mount_fillet + 1.0
    cutters = []
    for center_x, center_y in centers:
        cutters.append(
            trimesh.creation.cylinder(
                radius=hole_radius,
                height=end_z - start_z,
                sections=64,
                transform=trimesh.transformations.translation_matrix(
                    [center_x, center_y, (start_z + end_z) / 2.0]
                ),
            )
        )

    result = trimesh.boolean.difference([mesh, *cutters], engine="manifold")
    if isinstance(result, list):
        result = trimesh.util.concatenate(result)
    result.process(validate=True)
    trimesh.repair.fix_normals(result, multibody=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a HornCAD STL from defaults or a HornCAD YAML file."
    )
    parser.add_argument(
        "yaml",
        nargs="?",
        type=Path,
        help="HornCAD YAML exported from the browser app.",
    )
    parser.add_argument(
        "--mode",
        choices=("acoustic_surface", "surface", "body"),
        help="Override the STL export mode from YAML/defaults.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Directory for the generated STL. Defaults to {OUTPUT_DIR}.",
    )
    return parser.parse_args()


def normalized_export_mode(mode: object) -> str:
    return "surface" if mode in ("surface", "acoustic_surface") else "body"


def main() -> None:
    args = parse_args()
    if args.yaml is not None:
        apply_horncad_yaml(args.yaml)
    if args.mode is not None:
        PARAMS["stl_export_mode"] = normalized_export_mode(args.mode)

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

    export_mode = normalized_export_mode(PARAMS.get("stl_export_mode", "body"))
    if export_mode == "surface":
        mouth_index = len(rings) - 1
        vertices, faces = build_acoustic_surface_mesh(rings, mouth_index, mouth_h, mouth_v)
    else:
        export_mode = "body"
        body_rings = list(rings)
        mouth_index = len(body_rings) - 1
        if PARAMS["mouth_rear_offset"] > 0.0:
            body_rings.append(mouth_rear_ring(body_rings, mouth_h, mouth_v))
        vertices, faces = build_body_mesh(body_rings, mouth_index, mouth_h, mouth_v)

    mode_label = "Surface" if export_mode == "surface" else "Body"
    output = args.output_dir / (
        f"HornCAD-{mode_label}-{round(PARAMS['mouth_width'])}x"
        f"{round(PARAMS['mouth_height'])}x{round(PARAMS['length'])}.STL"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    trimesh.repair.fix_normals(mesh, multibody=True)
    if export_mode == "body":
        mesh = subtract_mount_screw_holes(mesh)
    mesh.export(output)
    print(output)
    print(f"export_mode={export_mode}")
    export_ring_count = len(rings) if export_mode == "surface" else len(body_rings)
    print(f"inner_rings={export_ring_count} vertices_per_ring={len(rings[0])} vertices={len(mesh.vertices)} triangles={len(mesh.faces)}")
    print(f"watertight={mesh.is_watertight} winding_consistent={mesh.is_winding_consistent} components={len(mesh.split(only_watertight=False))}")


if __name__ == "__main__":
    main()
