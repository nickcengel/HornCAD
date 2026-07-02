"""Inside-surface generation and area diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence

_CACHE_DIR = Path(tempfile.gettempdir()) / "horncad-matplotlib"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))

from horncad.config import (
    morph_rate,
    profile_coverage,
    profile_k,
    profile_n,
    profile_q,
)
from horncad.profile import (
    DerivedConfig,
    FeasibilityIssue,
    derive_config,
    feasibility_issues,
    osse_radius,
    setback_from_radius,
    termination_radius,
)
from horncad.sampling import adaptive_closed_angles, adaptive_stations


@dataclass(frozen=True)
class RadialCurve:
    p_deg: float
    boundary_x: float
    boundary_y: float
    boundary_distance: float
    curvature_setback: float
    local_length: float
    profile_length: float
    coverage_deg: float
    k: float
    n: float
    solved_s: float
    boundary_fit_error: float
    issues: List[FeasibilityIssue]


@dataclass(frozen=True)
class SectionSample:
    station: float
    z_ref: float
    morph_weight: float
    actual_area: float
    target_area: float
    area_error: float
    log_area_error: float


@dataclass(frozen=True)
class AreaFit:
    score: float
    rms_log_error: float
    rms_percent_error: float
    max_abs_percent_error: float
    mean_signed_percent_error: float
    worst_z_ref: float


@dataclass(frozen=True)
class SurfaceResult:
    derived: DerivedConfig
    radial_curves: List[RadialCurve]
    sections: List[SectionSample]
    area_fit: AreaFit
    issues: List[FeasibilityIssue]
    shared_section_length: float


@dataclass(frozen=True)
class ReferenceAcousticValues:
    coverage_deg: float
    k: float
    n: float


def generate_inside_surface(config: Mapping[str, Any], target_config: Mapping[str, Any] | None = None) -> SurfaceResult:
    derived = derive_config(config)
    target_config = target_config if target_config is not None else config
    target_derived = derive_config(target_config)
    radial_curves = solve_radial_curves(config, derived)
    issues = feasibility_issues(config, derived)
    for curve in radial_curves:
        issues.extend(curve.issues)
    sections = generate_sections(config, derived, radial_curves, target_config, target_derived)
    area_fit = compute_area_fit(sections)
    return SurfaceResult(
        derived=derived,
        radial_curves=radial_curves,
        sections=sections,
        area_fit=area_fit,
        issues=issues,
        shared_section_length=shared_section_length(radial_curves),
    )


def solve_radial_curves(config: Mapping[str, Any], derived: DerivedConfig) -> List[RadialCurve]:
    curves: List[RadialCurve] = []
    for p in radial_sample_angles(config, derived):
        curves.append(radial_curve_at_angle(config, derived, p))
    return curves


def radial_curve_at_angle(config: Mapping[str, Any], derived: DerivedConfig, p: float) -> RadialCurve:
    boundary_distance = superellipse_boundary_distance(config, derived, p)
    boundary_x = boundary_distance * math.cos(p)
    boundary_y = boundary_distance * math.sin(p)
    curvature_setback = mouth_curvature_setback(config, derived, boundary_x, boundary_y)
    local_length = float(config["length"]["max"]) - curvature_setback
    coverage = interpolate_principal_value(
        profile_coverage(config, "horizontal"),
        profile_coverage(config, "vertical"),
        p,
    )
    k = interpolate_principal_value(
        profile_k(config, "horizontal"),
        profile_k(config, "vertical"),
        p,
    )
    n = interpolate_principal_value(
        profile_n(config, "horizontal"),
        profile_n(config, "vertical"),
        p,
    )
    return solve_radial_curve(
        config=config,
        derived=derived,
        p_deg=math.degrees(p),
        boundary_x=boundary_x,
        boundary_y=boundary_y,
        boundary_distance=boundary_distance,
        curvature_setback=curvature_setback,
        local_length=local_length,
        coverage_deg=coverage,
        k=k,
        n=n,
    )


def radial_sample_angles(config: Mapping[str, Any], derived: DerivedConfig) -> List[float]:
    count = int(config["resolution"]["angular_segments"])
    return snap_cardinal_angles(adaptive_closed_angles(
        count,
        lambda p: boundary_point_at_angle(config, derived, p),
        forced_quadrant_angles=corner_anchor_angles(config, derived),
    ))


def snap_cardinal_angles(angles: Sequence[float]) -> List[float]:
    snapped = []
    cardinals = (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0)
    for angle in angles:
        snapped.append(min(cardinals, key=lambda cardinal: abs(angle - cardinal)) if any(abs(angle - cardinal) < 1e-9 for cardinal in cardinals) else angle)
    return sorted(set(snapped))


def boundary_point_at_angle(config: Mapping[str, Any], derived: DerivedConfig, p: float) -> tuple[float, float]:
    boundary_distance = superellipse_boundary_distance(config, derived, p)
    return boundary_distance * math.cos(p), boundary_distance * math.sin(p)


def corner_anchor_angles(config: Mapping[str, Any], derived: DerivedConfig) -> List[float]:
    shape_type = config["mouth"]["shape"]["type"]
    corner_radius = config["mouth"]["shape"].get("corner_radius")
    if shape_type not in {"rectangle", "rounded_rectangle"} or corner_radius is None:
        return []
    r = float(corner_radius)
    a = derived.mouth_half_width
    b = derived.mouth_half_height
    if r <= 0.0 or r >= min(a, b):
        return []

    corner_center_x = a - r
    corner_center_y = b - r
    arc_angles = [math.radians(value) for value in (0.0, 22.5, 45.0, 67.5, 90.0)]
    return [
        math.atan2(corner_center_y + r * math.sin(angle), corner_center_x + r * math.cos(angle))
        for angle in arc_angles
    ]


def solve_radial_curve(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    p_deg: float,
    boundary_x: float,
    boundary_y: float,
    boundary_distance: float,
    curvature_setback: float,
    local_length: float,
    coverage_deg: float,
    k: float,
    n: float,
) -> RadialCurve:
    q = profile_q(config)
    profile_length = local_length - derived.l_conic
    issues: List[FeasibilityIssue] = []

    if not math.isfinite(local_length) or profile_length <= 0.0:
        issues.append(
            FeasibilityIssue(
                code="conic_extension_length_gte_local_profile_length",
                message=f"p={p_deg:.6g}: conic extension length is greater than or equal to local profile length",
                likely_culprit=(
                    "Mouth curvature setback and conic extension leave no OS-SE profile length in this direction. "
                    "Reduce mouth curvature sag, reduce conic extension length, or increase length.max."
                ),
            )
        )
        solved_s = 0.0
        final_distance = derived.r_conic_exit
    else:
        base_boundary_distance = osse_radius(
            profile_length,
            profile_length,
            derived.r_conic_exit,
            derived.alpha_exit_deg,
            coverage_deg,
            k,
            0.0,
            q,
            n,
        )
        termination_unit = termination_radius(profile_length, profile_length, 1.0, q, n)
        solved_s = (boundary_distance - base_boundary_distance) / termination_unit
        if solved_s < 0.0:
            issues.append(
                FeasibilityIssue(
                    code="negative_s_termination",
                    message=f"p={p_deg:.6g}: solved S is negative, reversing the terminal roundover direction",
                    likely_culprit=(
                        "The interpolated OS-SE base curve overshoots the mouth boundary in this direction. "
                        "Reduce the base expansion, increase the boundary distance, or increase the available "
                        "profile length."
                    ),
                )
            )
        final_distance = osse_radius(
            profile_length,
            profile_length,
            derived.r_conic_exit,
            derived.alpha_exit_deg,
            coverage_deg,
            k,
            solved_s,
            q,
            n,
        )

    return RadialCurve(
        p_deg=p_deg,
        boundary_x=boundary_x,
        boundary_y=boundary_y,
        boundary_distance=boundary_distance,
        curvature_setback=curvature_setback,
        local_length=local_length,
        profile_length=profile_length,
        coverage_deg=coverage_deg,
        k=k,
        n=n,
        solved_s=solved_s,
        boundary_fit_error=final_distance - boundary_distance,
        issues=issues,
    )


def generate_sections(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    curves: Sequence[RadialCurve],
    target_config: Mapping[str, Any] | None = None,
    target_derived: DerivedConfig | None = None,
) -> List[SectionSample]:
    count = int(config["resolution"]["length_segments"])
    length_max = float(config["length"]["max"])
    section_length = shared_section_length(curves)
    target_config = target_config if target_config is not None else config
    target_derived = target_derived if target_derived is not None else derived
    z_values = adaptive_stations(
        section_length,
        count,
        lambda z: reference_radius_at_z(target_config, target_derived, z),
    )
    sections: List[SectionSample] = []
    for index, z_ref in enumerate(z_values):
        station = index / count
        morph_weight = morph_weight_at_z(config, derived, curves, z_ref)
        round_radius = reference_radius_at_z(target_config, target_derived, z_ref)
        points = []
        for curve in curves:
            p = math.radians(curve.p_deg)
            raw_radius = radial_curve_distance_at_z(config, derived, curve, z_ref)
            surface_radius = (1.0 - morph_weight) * round_radius + morph_weight * raw_radius
            points.append((surface_radius * math.cos(p), surface_radius * math.sin(p)))
        actual_area = polygon_area(points)
        target_area = math.pi * round_radius**2
        if target_area <= 0.0 or actual_area <= 0.0:
            area_error = 0.0
            log_error = 0.0
        else:
            area_error = actual_area / target_area - 1.0
            log_error = math.log(actual_area / target_area)
        sections.append(
            SectionSample(
                station=station,
                z_ref=z_ref,
                morph_weight=morph_weight,
                actual_area=actual_area,
                target_area=target_area,
                area_error=area_error,
                log_area_error=log_error,
            )
        )
    return sections


def write_inside_surface_stl(config: Mapping[str, Any], surface: SurfaceResult, path: Path) -> None:
    """Write the open inside surface as an ASCII STL triangle mesh."""

    triangles = inside_surface_triangles(config, surface)
    _write_ascii_stl(path, triangles)


def write_superellipse_surface_stl(config: Mapping[str, Any], path: Path) -> None:
    """Write an open surface lofted from H/V basis profiles and superellipse sections."""

    triangles = superellipse_surface_triangles(config)
    _write_ascii_stl(path, triangles)


def _write_ascii_stl(
    path: Path,
    triangles: Sequence[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]],
) -> None:
    name = _stl_solid_name(path.stem)
    lines = [f"solid {name}"]
    for triangle in triangles:
        normal = _triangle_normal(triangle)
        if normal is None:
            continue
        lines.append(f"  facet normal {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}")
        lines.append("    outer loop")
        for vertex in triangle:
            lines.append(f"      vertex {vertex[0]:.9g} {vertex[1]:.9g} {vertex[2]:.9g}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def superellipse_surface_triangles(
    config: Mapping[str, Any],
) -> List[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]:
    derived = derive_config(config)
    horizontal = radial_curve_at_angle(config, derived, 0.0)
    vertical = radial_curve_at_angle(config, derived, math.pi / 2.0)
    angles = _superellipse_scope_angles(config, derived)
    if len(angles) < 2:
        return []

    count = int(config["resolution"]["length_segments"])
    fractions = [index / count for index in range(count + 1)] if count > 0 else [0.0]
    vertices = [
        [_superellipse_surface_vertex(config, derived, horizontal, vertical, theta, fraction) for theta in angles]
        for fraction in fractions
    ]
    wrap = config["outputs"]["scope"] == "full"
    angular_spans = len(angles) if wrap else len(angles) - 1
    triangles = []
    for fraction_index in range(len(vertices) - 1):
        current_ring = vertices[fraction_index]
        next_ring = vertices[fraction_index + 1]
        for angle_index in range(angular_spans):
            next_angle = (angle_index + 1) % len(angles)
            a = current_ring[angle_index]
            b = current_ring[next_angle]
            c = next_ring[angle_index]
            d = next_ring[next_angle]
            triangles.extend(_triangulate_quad(a, b, c, d))
    return triangles


def inside_surface_triangles(
    config: Mapping[str, Any],
    surface: SurfaceResult,
) -> List[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]:
    curves = _scope_curves(config, surface.radial_curves)
    if len(curves) < 2 or len(surface.sections) < 2:
        return []

    station_fractions = _mesh_station_fractions(surface)
    vertices = [
        [_surface_vertex_at_fraction(config, surface, curve, fraction) for curve in curves]
        for fraction in station_fractions
    ]
    wrap = config["outputs"]["scope"] == "full"
    radial_spans = len(curves) if wrap else len(curves) - 1
    triangles = []
    for station_index in range(len(vertices) - 1):
        current_ring = vertices[station_index]
        next_ring = vertices[station_index + 1]
        for radial_index in range(radial_spans):
            next_radial = (radial_index + 1) % len(curves)
            a = current_ring[radial_index]
            b = current_ring[next_radial]
            c = next_ring[radial_index]
            d = next_ring[next_radial]
            triangles.extend(_triangulate_quad(a, b, c, d))
    return triangles


def _superellipse_scope_angles(config: Mapping[str, Any], derived: DerivedConfig) -> List[float]:
    count = int(config["resolution"]["angular_segments"])
    full_angles = _superellipse_axis_detail_angles(count, _superellipse_mouth_power(config))
    scope = config["outputs"]["scope"]
    if scope == "full":
        return full_angles
    upper = math.pi / 2.0 if scope == "quarter" else math.pi
    return [theta for theta in full_angles if -1e-12 <= theta <= upper + 1e-12]


def _superellipse_axis_detail_angles(count: int, power: float) -> List[float]:
    if count <= 0:
        return []
    quadrant_segments = max(1, count // 4)
    quadrant = set()
    for index in range(quadrant_segments + 1):
        fraction = index / quadrant_segments
        x_fraction = 1.0 - fraction
        y_fraction = fraction
        if index == 0:
            quadrant.add(0.0)
            continue
        if index == quadrant_segments:
            quadrant.add(math.pi / 2.0)
            continue
        cos_theta = x_fraction ** (power / 2.0)
        sin_theta = y_fraction ** (power / 2.0)
        quadrant.add(round(math.acos(min(max(cos_theta, 0.0), 1.0)), 12))
        quadrant.add(round(math.asin(min(max(sin_theta, 0.0), 1.0)), 12))
    angles = set()
    for angle in quadrant:
        for mirrored in (
            angle,
            math.pi - angle,
            math.pi + angle,
            2.0 * math.pi - angle,
        ):
            angles.add(round(mirrored % (2.0 * math.pi), 12))
    return sorted(angles)


def _superellipse_surface_vertex(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    horizontal: RadialCurve,
    vertical: RadialCurve,
    theta: float,
    fraction: float,
) -> tuple[float, float, float]:
    fraction = min(max(fraction, 0.0), 1.0)
    horizontal_radius = radial_curve_distance_at_z(config, derived, horizontal, horizontal.local_length * fraction)
    vertical_radius = radial_curve_distance_at_z(config, derived, vertical, vertical.local_length * fraction)
    power = _superellipse_power_at_fraction(config, fraction)
    x, y = _superellipse_xy(horizontal_radius, vertical_radius, power, theta)
    mouth_x, mouth_y = _superellipse_xy(derived.mouth_half_width, derived.mouth_half_height, _superellipse_mouth_power(config), theta)
    local_length = float(config["length"]["max"]) - mouth_curvature_setback(config, derived, mouth_x, mouth_y)
    return x, y, local_length * fraction


def _superellipse_power_at_fraction(config: Mapping[str, Any], fraction: float) -> float:
    start_power = 2.0
    end_power = _superellipse_mouth_power(config)
    completion_fraction = min(max(morph_rate(config), 1e-9), 1.0)
    progress = min(max(fraction / completion_fraction, 0.0), 1.0)
    return start_power + (end_power - start_power) * progress


def _smoothstep(value: float) -> float:
    value = min(max(value, 0.0), 1.0)
    return value * value * (3.0 - 2.0 * value)


def _superellipse_mouth_power(config: Mapping[str, Any]) -> float:
    power = config["mouth"]["shape"].get("shape_power")
    return max(2.0, float(power) if power is not None else 6.0)


def _superellipse_xy(a: float, b: float, power: float, theta: float) -> tuple[float, float]:
    exponent = 2.0 / max(power, 1e-9)
    c = math.cos(theta)
    s = math.sin(theta)
    if abs(c) < 1e-12:
        c = 0.0
    if abs(s) < 1e-12:
        s = 0.0
    x = a * math.copysign(abs(c) ** exponent, c)
    y = b * math.copysign(abs(s) ** exponent, s)
    return x, y


def _scope_curves(config: Mapping[str, Any], curves: Sequence[RadialCurve]) -> List[RadialCurve]:
    scope = config["outputs"]["scope"]
    if scope == "full":
        return list(curves)
    upper = 90.0 if scope == "quarter" else 180.0
    scoped = [curve for curve in curves if -1e-9 <= curve.p_deg <= upper + 1e-9]
    return sorted(scoped, key=lambda curve: curve.p_deg)


def _mesh_station_fractions(surface: SurfaceResult) -> List[float]:
    if surface.shared_section_length <= 0.0:
        return [0.0]
    fractions = [
        min(max(section.z_ref / surface.shared_section_length, 0.0), 1.0)
        for section in surface.sections
    ]
    fractions[0] = 0.0
    fractions[-1] = 1.0
    return fractions


def _surface_vertex_at_fraction(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    curve: RadialCurve,
    fraction: float,
) -> tuple[float, float, float]:
    z = curve.local_length * fraction
    p = math.radians(curve.p_deg)
    raw_radius = radial_curve_distance_at_z(config, surface.derived, curve, z)
    round_radius = reference_radius_at_z(config, surface.derived, z)
    morph_weight = morph_weight_at_z(config, surface.derived, surface.radial_curves, z)
    radius = (1.0 - morph_weight) * round_radius + morph_weight * raw_radius
    return radius * math.cos(p), radius * math.sin(p), z


def _triangle_normal(
    triangle: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    a, b, c = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return None
    return nx / length, ny / length, nz / length


def _triangulate_quad(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> List[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]:
    if _distance_squared(a, d) <= _distance_squared(b, c):
        return [(a, c, d), (a, d, b)]
    return [(a, c, b), (b, c, d)]


def _distance_squared(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _stl_solid_name(name: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "_-" else "_" for character in name)
    return cleaned or "horncad_surface"


def radial_curve_distance_at_z(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    curve: RadialCurve,
    z_global: float,
) -> float:
    if curve.profile_length <= 0.0:
        return derived.r_conic_exit
    if z_global > curve.local_length:
        raise ValueError("cannot evaluate a radial curve past its local mouth boundary")
    if z_global <= derived.l_conic:
        return derived.r0 + z_global * math.tan(math.radians(derived.alpha_exit_deg))
    z_profile = z_global - derived.l_conic
    return osse_radius(
        z_profile,
        curve.profile_length,
        derived.r_conic_exit,
        derived.alpha_exit_deg,
        curve.coverage_deg,
        curve.k,
        curve.solved_s,
        profile_q(config),
        curve.n,
    )


def reference_radius_at_z(config: Mapping[str, Any], derived: DerivedConfig, z_global: float) -> float:
    length_max = float(config["length"]["max"])
    profile_length = length_max - derived.l_conic
    if z_global <= derived.l_conic:
        return derived.r0 + z_global * math.tan(math.radians(derived.alpha_exit_deg))

    z_profile = z_global - derived.l_conic
    reference = equivalent_round_reference_values(config, derived)
    target_area = mouth_area(config, derived)
    target_radius = math.sqrt(target_area / math.pi)
    q = profile_q(config)
    n = reference.n
    base_distance = osse_radius(
        profile_length,
        profile_length,
        derived.r_conic_exit,
        derived.alpha_exit_deg,
        reference.coverage_deg,
        reference.k,
        0.0,
        q,
        n,
    )
    termination_unit = termination_radius(profile_length, profile_length, 1.0, q, n)
    s_ref = (target_radius - base_distance) / termination_unit
    return osse_radius(
        z_profile,
        profile_length,
        derived.r_conic_exit,
        derived.alpha_exit_deg,
        reference.coverage_deg,
        reference.k,
        s_ref,
        q,
        n,
    )


def equivalent_round_reference_values(config: Mapping[str, Any], derived: DerivedConfig) -> ReferenceAcousticValues:
    count = int(config["resolution"]["angular_segments"])
    coverage_h = profile_coverage(config, "horizontal")
    coverage_v = profile_coverage(config, "vertical")
    k_h = profile_k(config, "horizontal")
    k_v = profile_k(config, "vertical")
    n_h = profile_n(config, "horizontal")
    n_v = profile_n(config, "vertical")
    weighted_coverage = 0.0
    weighted_k = 0.0
    weighted_n = 0.0
    total_weight = 0.0
    for index in range(count):
        p = 2.0 * math.pi * index / count
        boundary_distance = superellipse_boundary_distance(config, derived, p)
        weight = boundary_distance * boundary_distance
        weighted_coverage += interpolate_principal_value(coverage_h, coverage_v, p) * weight
        weighted_k += interpolate_principal_value(k_h, k_v, p) * weight
        weighted_n += interpolate_principal_value(n_h, n_v, p) * weight
        total_weight += weight
    if total_weight == 0.0:
        return ReferenceAcousticValues((coverage_h + coverage_v) / 2.0, (k_h + k_v) / 2.0, (n_h + n_v) / 2.0)
    return ReferenceAcousticValues(
        weighted_coverage / total_weight,
        weighted_k / total_weight,
        weighted_n / total_weight,
    )


def plotted_target_area_normalizer(sections: Sequence[SectionSample]) -> float:
    if not sections:
        return 1.0
    target_area = sections[-1].target_area
    return target_area if target_area > 0.0 else 1.0


def morph_weight_at_z(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    curves: Sequence[RadialCurve],
    z: float,
) -> float:
    start = float(config["morph"]["start"])
    if z <= start:
        return 0.0
    start_progress = raw_radial_log_area_progress_at_z(config, derived, curves, start)
    progress = raw_radial_log_area_progress_at_z(config, derived, curves, z)
    if progress <= start_progress:
        return 0.0
    remaining = 1.0 - start_progress
    if remaining <= 1e-12:
        return 1.0
    completion_progress = max(morph_rate(config), 1e-9)
    local_progress = (progress - start_progress) / remaining
    return min(max(local_progress / completion_progress, 0.0), 1.0)


def raw_radial_log_area_progress_at_z(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    curves: Sequence[RadialCurve],
    z: float,
) -> float:
    start_area = raw_radial_section_area_at_z(config, derived, curves, 0.0)
    current_area = raw_radial_section_area_at_z(config, derived, curves, z)
    end_area = mouth_area(config, derived)
    if start_area <= 0.0 or current_area <= 0.0 or end_area <= start_area:
        return 0.0
    progress = (math.log(current_area) - math.log(start_area)) / (math.log(end_area) - math.log(start_area))
    return min(max(progress, 0.0), 1.0)


def raw_radial_section_area_at_z(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    curves: Sequence[RadialCurve],
    z: float,
) -> float:
    points = []
    for curve in curves:
        p = math.radians(curve.p_deg)
        local_z = min(max(z, 0.0), curve.local_length)
        radius = radial_curve_distance_at_z(config, derived, curve, local_z)
        points.append((radius * math.cos(p), radius * math.sin(p)))
    return polygon_area(points)


def compute_area_fit(sections: Sequence[SectionSample]) -> AreaFit:
    if not sections:
        return AreaFit(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    rms_log = math.sqrt(sum(section.log_area_error ** 2 for section in sections) / len(sections))
    rms_percent = math.sqrt(sum(section.area_error ** 2 for section in sections) / len(sections))
    worst = max(sections, key=lambda section: abs(section.area_error))
    mean_signed = sum(section.area_error for section in sections) / len(sections)
    return AreaFit(
        score=math.exp(-rms_log),
        rms_log_error=rms_log,
        rms_percent_error=rms_percent,
        max_abs_percent_error=abs(worst.area_error),
        mean_signed_percent_error=mean_signed,
        worst_z_ref=worst.z_ref,
    )


def shared_section_length(curves: Sequence[RadialCurve]) -> float:
    finite_lengths = [curve.local_length for curve in curves if math.isfinite(curve.local_length)]
    return min(finite_lengths) if finite_lengths else 0.0


def superellipse_boundary_distance(config: Mapping[str, Any], derived: DerivedConfig, p: float) -> float:
    shape_type = config["mouth"]["shape"]["type"]
    corner_radius = config["mouth"]["shape"].get("corner_radius")
    if shape_type == "rectangle":
        return rounded_rectangle_boundary_distance(
            derived.mouth_half_width,
            derived.mouth_half_height,
            float(corner_radius or 0.0),
            p,
        )
    if shape_type == "rounded_rectangle" and corner_radius is not None:
        return rounded_rectangle_boundary_distance(
            derived.mouth_half_width,
            derived.mouth_half_height,
            float(corner_radius),
            p,
        )
    if shape_type == "ellipse":
        power = 2.0
    else:
        power = float(config["mouth"]["shape"]["shape_power"])
    a = derived.mouth_half_width
    b = derived.mouth_half_height
    return 1.0 / (((abs(math.cos(p)) / a) ** power + (abs(math.sin(p)) / b) ** power) ** (1.0 / power))


def superellipse_area(a: float, b: float, power: float) -> float:
    return 4.0 * a * b * math.gamma(1.0 + 1.0 / power) ** 2 / math.gamma(1.0 + 2.0 / power)


def mouth_area(config: Mapping[str, Any], derived: DerivedConfig) -> float:
    shape = config["mouth"]["shape"]
    shape_type = shape["type"]
    corner_radius = shape.get("corner_radius")
    if shape_type == "ellipse":
        return math.pi * derived.mouth_half_width * derived.mouth_half_height
    if shape_type == "rectangle":
        return rounded_rectangle_area(
            2.0 * derived.mouth_half_width,
            2.0 * derived.mouth_half_height,
            float(corner_radius or 0.0),
        )
    if shape_type == "rounded_rectangle" and corner_radius is not None:
        return rounded_rectangle_area(
            2.0 * derived.mouth_half_width,
            2.0 * derived.mouth_half_height,
            float(corner_radius),
        )
    return superellipse_area(
        derived.mouth_half_width,
        derived.mouth_half_height,
        float(shape["shape_power"]),
    )


def rounded_rectangle_area(width: float, height: float, corner_radius: float) -> float:
    return width * height - (4.0 - math.pi) * corner_radius * corner_radius


def rounded_rectangle_boundary_distance(a: float, b: float, corner_radius: float, p: float) -> float:
    c = abs(math.cos(p))
    s = abs(math.sin(p))
    radius = min(max(corner_radius, 0.0), a, b)

    if radius == 0.0:
        candidates = []
        if c > 0.0:
            candidates.append(a / c)
        if s > 0.0:
            candidates.append(b / s)
        return min(candidates)

    side_x = a - radius
    side_y = b - radius
    candidates = []

    if c > 0.0:
        t = a / c
        y = t * s
        if y <= side_y:
            candidates.append(t)
    if s > 0.0:
        t = b / s
        x = t * c
        if x <= side_x:
            candidates.append(t)

    dot = c * side_x + s * side_y
    center_sq = side_x * side_x + side_y * side_y
    discriminant = dot * dot - (center_sq - radius * radius)
    if discriminant >= 0.0:
        candidates.append(dot + math.sqrt(discriminant))

    if not candidates:
        raise ValueError("ray does not intersect rounded rectangle")
    return min(t for t in candidates if t >= 0.0)


def interpolate_principal_value(horizontal: float, vertical: float, p: float) -> float:
    return vertical + (horizontal - vertical) * math.cos(p) ** 2


def mouth_curvature_setback(config: Mapping[str, Any], derived: DerivedConfig, x: float, y: float) -> float:
    curvature = config["mouth"]["curvature"]
    curvature_type = curvature["type"]
    if curvature_type == "flat":
        return 0.0
    if curvature_type == "cylinder":
        if curvature.get("sag") is not None:
            radius = derived.curvature_radius
        else:
            radius = float(curvature["radius"])
        setback = setback_from_radius(abs(x), radius)
    elif curvature_type == "sphere":
        if curvature.get("sag") is not None:
            radius = derived.curvature_radius
        else:
            radius = float(curvature["radius"])
        setback = setback_from_radius(math.hypot(x, y), radius)
    else:
        raise ValueError(f"unsupported curvature type: {curvature_type}")
    return math.inf if math.isnan(setback) else setback


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return abs(total) * 0.5


def rejected_issues(config: Mapping[str, Any], issues: Sequence[FeasibilityIssue]) -> List[FeasibilityIssue]:
    reject_codes = set(config["validation"]["reject_if"])
    reject_codes.add("negative_s_termination")
    return [issue for issue in issues if issue.code in reject_codes]

