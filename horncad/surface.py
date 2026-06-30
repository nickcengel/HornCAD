"""M2 inside-surface generation and area diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import yaml

_CACHE_DIR = Path(tempfile.gettempdir()) / "horncad-matplotlib"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))

from horncad.config import (
    ConfigError,
    dump_config,
    load_project,
    morph_rate,
    profile_coverage,
    profile_k,
    profile_n,
    profile_q,
    refinement_s_bounds,
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


def generate_surface_review(project_path: Path, output_dir: Path | None = None) -> Dict[str, Path]:
    project_path = Path(project_path)
    if output_dir is None:
        output_dir = project_path.parent / "surface_review"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_project(project_path)
    result = generate_inside_surface(config)
    rejected = rejected_issues(config, result.issues)
    if rejected:
        raise SurfaceFeasibilityError(rejected)

    stem = project_path.stem
    artifacts = {
        "area_fit": output_dir / f"{stem}_area_fit.png",
        "report": output_dir / f"{stem}_surface_report.md",
        "resolved": output_dir / f"{stem}_resolved.yaml",
    }

    _plot_area_fit(result.sections, artifacts["area_fit"])
    artifacts["resolved"].write_text(dump_config(config), encoding="utf-8")
    _write_surface_report(project_path, config, result, artifacts)
    return artifacts


class SurfaceFeasibilityError(ValueError):
    """Raised when M2 surface generation hits configured reject conditions."""

    def __init__(self, issues: Sequence[FeasibilityIssue]):
        self.issues = list(issues)
        super().__init__("\n".join(issue.message for issue in self.issues))


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
) -> RadialCurve:
    q = profile_q(config)
    n = profile_n(config)
    lower_s, upper_s = refinement_s_bounds(config)
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
        solved_s = lower_s
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
        final_distance = osse_radius(
            profile_length,
            profile_length,
            derived.r_conic_exit,
            derived.alpha_exit_deg,
            coverage_deg,
            k,
            min(max(solved_s, lower_s), upper_s),
            q,
            n,
        )
        if solved_s < lower_s or solved_s > upper_s:
            issues.append(
                FeasibilityIssue(
                    code="solved_s_outside_bounds",
                    message=f"p={p_deg:.6g}: solved S {solved_s:.6g} is outside configured bounds {lower_s:g}..{upper_s:g}",
                    likely_culprit=(
                        "The mouth boundary distance in this direction is not reachable with the current local length, "
                        "coverage, K, Q, N, and S bounds."
                    ),
                )
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
        morph_weight = morph_weight_at_z(config, z_ref, length_max)
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
        profile_n(config),
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
    n = profile_n(config)
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
    weighted_coverage = 0.0
    weighted_k = 0.0
    total_weight = 0.0
    for index in range(count):
        p = 2.0 * math.pi * index / count
        boundary_distance = superellipse_boundary_distance(config, derived, p)
        weight = boundary_distance * boundary_distance
        weighted_coverage += interpolate_principal_value(coverage_h, coverage_v, p) * weight
        weighted_k += interpolate_principal_value(k_h, k_v, p) * weight
        total_weight += weight
    if total_weight == 0.0:
        return ReferenceAcousticValues((coverage_h + coverage_v) / 2.0, (k_h + k_v) / 2.0)
    return ReferenceAcousticValues(weighted_coverage / total_weight, weighted_k / total_weight)


def plotted_target_area_normalizer(sections: Sequence[SectionSample]) -> float:
    if not sections:
        return 1.0
    target_area = sections[-1].target_area
    return target_area if target_area > 0.0 else 1.0


def morph_weight_at_z(config: Mapping[str, Any], z: float, length_max: float) -> float:
    start = float(config["morph"]["start"])
    rate = morph_rate(config)
    if z <= start:
        return 0.0
    if length_max <= start:
        return 1.0
    return min(max(((z - start) / (length_max - start)) ** rate, 0.0), 1.0)


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
    return [issue for issue in issues if issue.code in reject_codes]


def _plot_area_fit(sections: Sequence[SectionSample], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    scale = plotted_target_area_normalizer(sections)
    ax.plot(
        [section.z_ref for section in sections],
        [section.actual_area / scale for section in sections],
        label="actual area",
    )
    ax.plot(
        [section.z_ref for section in sections],
        [section.target_area / scale for section in sections],
        label="target area",
    )
    ax.set_title("Area Expansion")
    ax.set_xlabel("reference z (mm)")
    ax.set_ylabel("area / target area at plotted end")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _write_surface_report(
    project_path: Path,
    config: Mapping[str, Any],
    result: SurfaceResult,
    artifacts: Mapping[str, Path],
) -> None:
    fit = result.area_fit
    lines = [
        f"# HornCAD Surface Review: {project_path.stem}",
        "",
        "## Area Expansion",
        "",
        "- Target: polar-area-weighted circular OS-SE reference",
        "- Section basis: closed constant-z sections over the shared radial-curve length",
        f"- Shared section length: {result.shared_section_length:.6g} mm",
        f"- Area fit score: {fit.score:.6g}",
        f"- RMS log area error: {fit.rms_log_error:.6g}",
        f"- RMS area error: {fit.rms_percent_error * 100.0:.6g}%",
        f"- Max area error: {fit.max_abs_percent_error * 100.0:.6g}%",
        f"- Mean signed area error: {fit.mean_signed_percent_error * 100.0:.6g}%",
        f"- Worst reference z: {fit.worst_z_ref:.6g} mm",
        "",
        "## Surface Summary",
        "",
        f"- Radial curves: {len(result.radial_curves)}",
        f"- Section samples: {len(result.sections)}",
        f"- Output scope: {config['outputs']['scope']}",
        f"- Morph start: {float(config['morph']['start']):.6g} mm",
        f"- Morph rate: {morph_rate(config):.6g}",
        "",
        "## Warnings And Infeasible Conditions",
        "",
    ]
    if result.issues:
        for issue in result.issues:
            lines.append(f"- `{issue.code}`: {issue.message}")
            lines.append(f"  Likely culprit: {issue.likely_culprit}")
    else:
        lines.append("- None")
    lines.extend(["", "## Generated Artifacts", ""])
    lines.extend(f"- `{name}`: `{path}`" for name, path in artifacts.items())
    lines.append("")
    artifacts["report"].write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate HornCAD M2 inside-surface review artifacts.")
    parser.add_argument("project", type=Path, help="Path to a HornCAD project YAML file.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated surface-review artifacts. Defaults to surface_review/ beside the project file.",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = generate_surface_review(args.project, args.output_dir)
    except (OSError, yaml.YAMLError, ConfigError, SurfaceFeasibilityError, ValueError) as exc:
        if isinstance(exc, SurfaceFeasibilityError):
            sys.stderr.write("Surface feasibility check failed:\n")
            for issue in exc.issues:
                sys.stderr.write(f"  - [{issue.code}] {issue.message}\n")
                sys.stderr.write(f"    likely culprit: {issue.likely_culprit}\n")
        else:
            sys.stderr.write(f"{exc}\n")
        return 1

    for path in artifacts.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
