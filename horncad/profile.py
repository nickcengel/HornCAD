"""Principal-axis OS-SE profile calculations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Mapping, Tuple

from horncad.config import (
    profile_coverage,
    profile_k,
    profile_n,
    profile_q,
    refinement_s_bounds,
)
from horncad.sampling import adaptive_stations


@dataclass(frozen=True)
class DerivedConfig:
    r0: float
    alpha0_deg: float
    l_conic: float
    alpha_exit_deg: float
    r_conic_exit: float
    mouth_half_width: float
    mouth_half_height: float
    curvature_radius: float | None
    curvature_sag: float | None


@dataclass(frozen=True)
class ProfilePoint:
    axis: str
    z: float
    radius: float
    segment: str


@dataclass(frozen=True)
class FeasibilityIssue:
    code: str
    message: str
    likely_culprit: str


@dataclass(frozen=True)
class ProfileResult:
    axis: str
    coverage_deg: float
    k: float
    q: float
    n: float
    target_boundary_distance: float
    local_length: float
    profile_length: float
    solved_s: float
    final_radius: float
    boundary_fit_error: float
    points: List[ProfilePoint]
    issues: List[FeasibilityIssue]

    @property
    def warnings(self) -> List[str]:
        return [issue.message for issue in self.issues]


@dataclass(frozen=True)
class RoundoverMetrics:
    roundover_contribution_percent: float


def roundover_metrics(profile: ProfileResult) -> RoundoverMetrics:
    start_radius = profile.points[0].radius if profile.points else 0.0
    end_radius = profile.target_boundary_distance
    return RoundoverMetrics(
        roundover_contribution_percent=_roundover_contribution_percent(profile, start_radius, end_radius),
    )


def _roundover_contribution_percent(
    profile: ProfileResult,
    start_radius: float,
    end_radius: float,
) -> float:
    total_growth = end_radius - start_radius
    if total_growth <= 0.0 or profile.profile_length <= 0.0:
        return 0.0
    contribution = profile.solved_s * termination_radius(
        profile.profile_length,
        profile.profile_length,
        1.0,
        profile.q,
        profile.n,
    )
    return max(0.0, min(100.0, 100.0 * contribution / total_growth))


def derive_config(config: Mapping[str, Any]) -> DerivedConfig:
    throat = config["throat"]
    mouth = config["mouth"]
    curvature = mouth["curvature"]

    r0 = float(throat["diameter"]) / 2.0
    alpha0_deg = float(throat["angle"])
    l_conic = float(throat["conic_extension"]["length"])
    alpha_exit_deg = alpha0_deg if l_conic == 0.0 else float(throat["conic_extension"]["exit_angle"])
    r_conic_exit = r0 + l_conic * math.tan(math.radians(alpha_exit_deg))
    mouth_half_width = float(mouth["width"]) / 2.0
    mouth_half_height = float(mouth["height"]) / 2.0

    sag = curvature.get("sag")
    radius = curvature.get("radius")
    curvature_sag = float(sag) if sag is not None else None
    curvature_radius = float(radius) if radius is not None else None

    if curvature["type"] == "cylinder" and curvature_sag is not None:
        curvature_radius = radius_from_sag(mouth_half_width, curvature_sag)
    elif curvature["type"] == "sphere" and curvature_sag is not None:
        half_diagonal = math.hypot(mouth_half_width, mouth_half_height)
        curvature_radius = radius_from_sag(half_diagonal, curvature_sag)
    elif curvature["type"] == "flat":
        curvature_sag = 0.0
        curvature_radius = None

    return DerivedConfig(
        r0=r0,
        alpha0_deg=alpha0_deg,
        l_conic=l_conic,
        alpha_exit_deg=alpha_exit_deg,
        r_conic_exit=r_conic_exit,
        mouth_half_width=mouth_half_width,
        mouth_half_height=mouth_half_height,
        curvature_radius=curvature_radius,
        curvature_sag=curvature_sag,
    )


def solve_principal_profiles(config: Mapping[str, Any]) -> Tuple[DerivedConfig, List[ProfileResult]]:
    derived = derive_config(config)
    length_max = float(config["length"]["max"])
    curvature = config["mouth"]["curvature"]

    horizontal_setback = _principal_setback(curvature, derived, "horizontal")
    vertical_setback = _principal_setback(curvature, derived, "vertical")

    results = [
        solve_profile(config, derived, "horizontal", derived.mouth_half_width, length_max - horizontal_setback),
        solve_profile(config, derived, "vertical", derived.mouth_half_height, length_max - vertical_setback),
    ]
    return derived, results


def solve_profile(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    axis: str,
    target_boundary_distance: float,
    local_length: float,
) -> ProfileResult:
    coverage_deg = profile_coverage(config, axis)
    k = profile_k(config, axis)
    q = profile_q(config)
    n = profile_n(config)
    lower_s, upper_s = refinement_s_bounds(config)
    length_segments = int(config["resolution"]["length_segments"])
    profile_length = local_length - derived.l_conic
    issues: List[FeasibilityIssue] = []

    if not math.isfinite(local_length) or profile_length <= 0.0:
        issues.append(
            FeasibilityIssue(
                code="conic_extension_length_gte_local_profile_length",
                message=f"{axis}: conic extension length is greater than or equal to local profile length",
                likely_culprit=(
                    "The conic extension, mouth curvature setback, and maximum horn length leave no "
                    "remaining OS-SE profile length. Reduce conic extension length or mouth curvature sag, "
                    "or increase length.max."
                ),
            )
        )
        solved_s = lower_s
        points = _conic_points(axis, derived, max(local_length, 0.0), length_segments)
        final_radius = points[-1].radius if points else derived.r0
        return ProfileResult(
            axis=axis,
            coverage_deg=coverage_deg,
            k=k,
            q=q,
            n=n,
            target_boundary_distance=target_boundary_distance,
            local_length=local_length,
            profile_length=profile_length,
            solved_s=solved_s,
            final_radius=final_radius,
            boundary_fit_error=final_radius - target_boundary_distance,
            points=points,
            issues=issues,
        )

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
    solved_s = (target_boundary_distance - base_boundary_distance) / termination_unit

    if solved_s < lower_s or solved_s > upper_s:
        issues.append(
            FeasibilityIssue(
                code="solved_s_outside_bounds",
                message=f"{axis}: solved S {solved_s:.6g} is outside configured bounds {lower_s:g}..{upper_s:g}",
                likely_culprit=_s_bounds_culprit(
                    axis,
                    solved_s,
                    lower_s,
                    upper_s,
                    target_boundary_distance,
                    base_boundary_distance,
                    local_length,
                ),
            )
        )

    sample_s = min(max(solved_s, lower_s), upper_s)
    if sample_s != solved_s:
        issues.append(
            FeasibilityIssue(
                code="plotted_s_clamped",
                message=f"{axis}: plotted profile uses clamped S {sample_s:.6g}",
                likely_culprit="The solved profile is outside the configured S bounds, so the plot is diagnostic only.",
            )
        )

    points = sample_profile(config, derived, axis, local_length, profile_length, coverage_deg, k, sample_s)
    final_radius = points[-1].radius
    return ProfileResult(
        axis=axis,
        coverage_deg=coverage_deg,
        k=k,
        q=q,
        n=n,
        target_boundary_distance=target_boundary_distance,
        local_length=local_length,
        profile_length=profile_length,
        solved_s=solved_s,
        final_radius=final_radius,
        boundary_fit_error=final_radius - target_boundary_distance,
        points=points,
        issues=issues,
    )


def sample_profile(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    axis: str,
    local_length: float,
    profile_length: float,
    coverage_deg: float,
    k: float,
    s: float,
) -> List[ProfilePoint]:
    length_segments = int(config["resolution"]["length_segments"])
    q = profile_q(config)
    n = profile_n(config)
    points: List[ProfilePoint] = []

    conic_count = max(2, int(round(length_segments * derived.l_conic / max(local_length, 1.0))) + 1)
    if derived.l_conic > 0.0:
        for index in range(conic_count):
            z = derived.l_conic * index / (conic_count - 1)
            radius = derived.r0 + z * math.tan(math.radians(derived.alpha_exit_deg))
            points.append(ProfilePoint(axis=axis, z=z, radius=radius, segment="conic"))
    else:
        points.append(ProfilePoint(axis=axis, z=0.0, radius=derived.r0, segment="osse"))

    osse_count = max(2, length_segments - len(points) + 2)
    stations = adaptive_stations(
        profile_length,
        osse_count - 1,
        lambda z: osse_radius(
            z,
            profile_length,
            derived.r_conic_exit,
            derived.alpha_exit_deg,
            coverage_deg,
            k,
            s,
            q,
            n,
        ),
    )
    for index, z_local in enumerate(stations):
        if index == 0 and derived.l_conic > 0.0:
            continue
        z_global = derived.l_conic + z_local
        radius = osse_radius(
            z_local,
            profile_length,
            derived.r_conic_exit,
            derived.alpha_exit_deg,
            coverage_deg,
            k,
            s,
            q,
            n,
        )
        points.append(ProfilePoint(axis=axis, z=z_global, radius=radius, segment="osse"))

    return points


def osse_radius(
    z: float,
    length: float,
    r0: float,
    alpha0_deg: float,
    alpha_deg: float,
    k: float,
    s: float,
    q: float,
    n: float,
) -> float:
    alpha0 = math.radians(alpha0_deg)
    alpha = math.radians(alpha_deg)
    gos = math.sqrt(
        k * k * r0 * r0
        + 2.0 * k * r0 * z * math.tan(alpha0)
        + z * z * math.tan(alpha) * math.tan(alpha)
    ) + r0 * (1.0 - k)
    return gos + termination_radius(z, length, s, q, n)


def termination_radius(z: float, length: float, s: float, q: float, n: float) -> float:
    if s == 0.0 or length <= 0.0:
        return 0.0
    term_inner = 1.0 - (q * z / length) ** n
    term_inner = max(term_inner, 0.0)
    return (s * length / q) * (1.0 - term_inner ** (1.0 / n))


def radius_from_sag(half_span: float, sag: float) -> float:
    if sag == 0.0:
        return math.inf
    return (half_span * half_span + sag * sag) / (2.0 * sag)


def setback_from_radius(distance: float, radius: float) -> float:
    if math.isinf(radius):
        return 0.0
    if radius < distance:
        return math.nan
    return radius - math.sqrt(radius * radius - distance * distance)


def feasibility_issues(config: Mapping[str, Any], derived: DerivedConfig) -> List[FeasibilityIssue]:
    curvature = config["mouth"]["curvature"]
    curvature_type = curvature["type"]
    radius = curvature.get("radius")
    issues: List[FeasibilityIssue] = []

    if radius is None:
        return issues

    radius_value = float(radius)
    if curvature_type == "cylinder":
        required = derived.mouth_half_width
    elif curvature_type == "sphere":
        required = math.hypot(derived.mouth_half_width, derived.mouth_half_height)
    else:
        return issues

    if radius_value < required:
        issues.append(
            FeasibilityIssue(
                code="mouth_curvature_radius_too_small",
                message=(
                    f"mouth: curvature radius {radius_value:.6g} mm is smaller than the required "
                    f"{required:.6g} mm for {curvature_type} curvature"
                ),
                likely_culprit=(
                    "The requested mouth curvature is mechanically impossible for the configured mouth size. "
                    "Increase mouth.curvature.radius or specify a smaller sag."
                ),
            )
        )

    return issues


def _principal_setback(curvature: Mapping[str, Any], derived: DerivedConfig, axis: str) -> float:
    curvature_type = curvature["type"]
    if curvature_type == "flat":
        return 0.0
    if curvature_type == "cylinder":
        if axis == "vertical":
            return 0.0
        if curvature.get("sag") is not None:
            return float(curvature["sag"])
        setback = setback_from_radius(derived.mouth_half_width, float(curvature["radius"]))
        return math.inf if math.isnan(setback) else setback
    if curvature_type == "sphere":
        distance = derived.mouth_half_width if axis == "horizontal" else derived.mouth_half_height
        if curvature.get("sag") is not None and derived.curvature_radius is not None:
            return setback_from_radius(distance, derived.curvature_radius)
        setback = setback_from_radius(distance, float(curvature["radius"]))
        return math.inf if math.isnan(setback) else setback
    raise ValueError(f"unsupported curvature type: {curvature_type}")


def _s_bounds_culprit(
    axis: str,
    solved_s: float,
    lower_s: float,
    upper_s: float,
    target_boundary_distance: float,
    base_boundary_distance: float,
    local_length: float,
) -> str:
    if solved_s < lower_s:
        return (
            f"The {axis} base OS profile reaches {base_boundary_distance:.6g} mm before termination flare, "
            f"which already overshoots the {target_boundary_distance:.6g} mm target. Likely fixes: reduce coverage, "
            "reduce throat/conic exit angle, reduce K if appropriate, or increase the mouth boundary dimension "
            "in that direction."
        )
    if solved_s > upper_s:
        return (
            f"The {axis} target boundary distance {target_boundary_distance:.6g} mm is too large for the current "
            f"{local_length:.6g} mm local length, coverage, K, Q, N, and S upper bound. Likely fixes: "
            "increase length.max, reduce mouth curvature sag, increase coverage, increase the S upper bound, or reduce "
            "the mouth boundary dimension in that direction."
        )
    return "The solved S value is outside the configured bounds."


def _conic_points(
    axis: str,
    derived: DerivedConfig,
    local_length: float,
    length_segments: int,
) -> List[ProfilePoint]:
    count = max(length_segments, 2)
    return [
        ProfilePoint(
            axis=axis,
            z=local_length * index / (count - 1),
            radius=derived.r0
            + min(local_length * index / (count - 1), derived.l_conic)
            * math.tan(math.radians(derived.alpha_exit_deg)),
            segment="conic",
        )
        for index in range(count)
    ]
