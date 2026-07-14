"""HornCAD candidate search and output generation."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import yaml

from horncad.config import (
    ConfigError,
    load_project,
    mouth_curvature_sag,
    morph_rate,
    profile_coverage,
    profile_k,
    profile_n,
    profile_q,
    profile_roundover_target_percent,
    profile_roundover_tolerance_percent,
    seeded_bounds,
    surface_mode,
)
from horncad.profile import FeasibilityIssue, roundover_metrics, sample_profile, solve_principal_profiles
from horncad.surface import (
    RadialCurve,
    SectionSample,
    SurfaceResult,
    generate_inside_surface,
    interpolate_principal_value,
    plotted_target_area_normalizer,
    radial_curve_at_angle,
    radial_curve_distance_at_z,
    rejected_issues,
    write_inside_surface_stl,
    write_superellipse_surface_stl,
)

INSIDE_SURFACE_SHAPE_POWER = 20.0


@dataclass(frozen=True)
class CandidateResult:
    stage: str
    config: Dict[str, Any]
    surface: SurfaceResult
    rejected: List[FeasibilityIssue]
    objective: float

    @property
    def is_valid(self) -> bool:
        return not self.rejected


@dataclass(frozen=True)
class RefinementResult:
    authored_config: Dict[str, Any]
    initial: SurfaceResult
    best: CandidateResult
    search_space: "SearchSpace"
    candidates_evaluated: int
    candidates_rejected: int
    stage_summaries: List[str]
    workers: int


class OutputFeasibilityError(ValueError):
    """Raised when direct output generation hits configured hard constraints."""

    def __init__(self, issues: Sequence[FeasibilityIssue]):
        self.issues = list(issues)
        super().__init__("\n".join(issue.message for issue in self.issues))


@dataclass(frozen=True)
class SearchSpace:
    aspect_delta: float
    coverage_delta: float
    initial_rms_log_area_error: float
    difficulty: float
    effective_ranges: Dict[str, tuple[float, float]]
    expected_s_span: float


@dataclass(frozen=True)
class SQuality:
    minimum: float
    maximum: float
    span: float
    expected_span: float
    excess_span: float
    rms_deviation: float
    max_adjacent_delta: float


@dataclass(frozen=True)
class ProfileSmoothness:
    max_slope_change: float
    limit: float
    excess: float


@dataclass(frozen=True)
class RadialBasisDeviation:
    rms_radius_deviation: float
    max_radius_deviation: float
    rms_exit_slope_deviation: float


@dataclass(frozen=True)
class MorphTiming:
    z50_fraction: float
    z90_fraction: float
    z50_limit: float
    excess_z50: float


@dataclass(frozen=True)
class AreaZoneMetrics:
    weighted_rms_log_error: float
    throat_rms_log_error: float
    middle_rms_log_error: float
    mouth_rms_log_error: float


@dataclass(frozen=True)
class RoundoverTargetRow:
    axis: str
    target_percent: float | None
    actual_percent: float
    tolerance_percent: float | None
    excess_miss_percent: float | None


@dataclass(frozen=True)
class RoundoverLengthRecommendation:
    axis: str
    target_percent: float | None
    current_percent: float
    required_length: float | None
    required_length_change: float | None
    required_s: float | None
    valid_s: bool | None
    note: str


@dataclass(frozen=True)
class ObjectiveTerm:
    name: str
    raw_value: float
    normalized_value: float
    weight: float
    contribution: float


def generate_output(
    project_path: Path,
    output_dir: Path | None = None,
    workers: int | str | None = None,
) -> Dict[str, Path]:
    project_path = Path(project_path)
    if output_dir is None:
        output_dir = project_path.parent / "output"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_project(project_path)
    mode = surface_mode(config)
    result = refine_project(config, workers=workers) if mode == "profile" else solve_project(config)

    stem = project_path.stem
    for obsolete in (
        output_dir / f"{stem}_refined_horizontal_view.png",
        output_dir / f"{stem}_refined_vertical_view.png",
        output_dir / f"{stem}_refined_area_fit.png",
        output_dir / f"{stem}_refined_hv_profiles.png",
        output_dir / f"{stem}_refined_radial_profiles.png",
        output_dir / f"{stem}_refined_radial_plan.png",
        output_dir / f"{stem}_refined_principal_views.png",
        output_dir / f"{stem}_refinement_report.md",
        output_dir / f"{stem}_refined.yaml",
        output_dir / f"{stem}_refined_inside_surface.stl",
    ):
        obsolete.unlink(missing_ok=True)
    artifacts: Dict[str, Path] = {
        "area_fit": output_dir / f"{stem}_area_fit.png",
        "hv_profiles": output_dir / f"{stem}_hv_profiles.png",
    }
    if result.best.config["outputs"]["cad"]["formats"]["3d"]["stl"]:
        artifacts["inside_surface"] = output_dir / f"{stem}_inside_surface.stl"
    artifacts.update(
        {
            "radial_plan": output_dir / f"{stem}_radial_plan.png",
            "radial_profiles": output_dir / f"{stem}_radial_profiles.png",
            "report": output_dir / f"{stem}_report.md",
        }
    )

    _plot_area_fit(
        result.initial.sections,
        result.best.surface.sections,
        artifacts["area_fit"],
    )
    _plot_hv_profiles(result.best.config, artifacts["hv_profiles"])
    _plot_radial_profiles(result.best.config, result.best.surface, artifacts["radial_profiles"])
    _plot_radial_plan(result.best.surface, artifacts["radial_plan"])
    if "inside_surface" in artifacts and mode == "profile":
        write_inside_surface_stl(result.best.config, result.best.surface, artifacts["inside_surface"])
    elif "inside_surface" in artifacts:
        write_superellipse_surface_stl(_inside_surface_output_config(result.best.config), artifacts["inside_surface"])
    _write_output_report(project_path, result, artifacts)
    return artifacts


def _inside_surface_output_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    output_config = copy.deepcopy(dict(config))
    output_config["mouth"] = copy.deepcopy(dict(config["mouth"]))
    output_config["mouth"]["shape"] = copy.deepcopy(dict(config["mouth"]["shape"]))
    output_config["mouth"]["shape"]["shape_power"] = INSIDE_SURFACE_SHAPE_POWER
    return output_config


def solve_project(config: Mapping[str, Any]) -> RefinementResult:
    authored_config = copy.deepcopy(dict(config))
    surface = generate_inside_surface(authored_config)
    rejected = _slice_rejected_issues(authored_config, surface)
    if rejected:
        raise OutputFeasibilityError(rejected)
    initial_area_zones = area_zone_metrics(surface.sections)
    return RefinementResult(
        authored_config=authored_config,
        initial=surface,
        best=CandidateResult(
            stage="direct",
            config=authored_config,
            surface=surface,
            rejected=[],
            objective=objective_score(authored_config, surface, authored_config, initial_area_zones.weighted_rms_log_error),
        ),
        search_space=build_search_space(authored_config, surface),
        candidates_evaluated=1,
        candidates_rejected=0,
        stage_summaries=[],
        workers=0,
    )


def _slice_rejected_issues(config: Mapping[str, Any], surface: SurfaceResult) -> List[FeasibilityIssue]:
    governing_issues: List[FeasibilityIssue] = []
    for curve in surface.radial_curves:
        if _is_cardinal_profile_angle(curve.p_deg):
            governing_issues.extend(curve.issues)
    global_or_unparsed = [
        issue
        for issue in surface.issues
        if not issue.message.startswith("p=")
    ]
    return rejected_issues(config, [*global_or_unparsed, *governing_issues])


def _is_cardinal_profile_angle(p_deg: float) -> bool:
    normalized = p_deg % 360.0
    return any(abs(normalized - cardinal) < 1e-6 for cardinal in (0.0, 90.0, 180.0, 270.0))


def refine_project(config: Mapping[str, Any], workers: int | str | None = None) -> RefinementResult:
    authored_config = copy.deepcopy(dict(config))
    worker_count = _resolve_workers(workers)
    initial = generate_inside_surface(authored_config)
    initial_area_zones = area_zone_metrics(initial.sections)
    search_space = build_search_space(authored_config, initial)
    candidates: List[CandidateResult] = []
    stage_summaries: List[str] = []

    for stage_name, variable_names in _search_stages(authored_config):
        candidate_configs = list(_candidate_configs(authored_config, variable_names, search_space))
        stage_candidates = _evaluate_candidate_configs(
            stage_name,
            authored_config,
            initial_area_zones.weighted_rms_log_error,
            candidate_configs,
            worker_count,
        )
        candidates.extend(stage_candidates)
        best_stage = min(stage_candidates, key=lambda item: item.objective)
        stage_summaries.append(_stage_summary(stage_name, stage_candidates, best_stage))

    if not candidates:
        surface = generate_inside_surface(authored_config)
        candidates.append(
            CandidateResult(
                stage="authored",
                config=authored_config,
                surface=surface,
                rejected=rejected_issues(authored_config, surface.issues),
                objective=_objective(
                    authored_config,
                    authored_config,
                    surface,
                    rejected_issues(authored_config, surface.issues),
                    initial_area_zones.weighted_rms_log_error,
                ),
            )
        )
        stage_summaries.append("authored: evaluated 1 design")

    best_valid = [candidate for candidate in candidates if candidate.is_valid]
    best = min(best_valid or candidates, key=lambda item: item.objective)
    rejected_count = sum(1 for candidate in candidates if not candidate.is_valid)

    return RefinementResult(
        authored_config=authored_config,
        initial=initial,
        best=best,
        search_space=search_space,
        candidates_evaluated=len(candidates),
        candidates_rejected=rejected_count,
        stage_summaries=stage_summaries,
        workers=worker_count,
    )


def _resolve_workers(workers: int | str | None) -> int:
    if workers is None:
        return 1
    if isinstance(workers, int):
        return max(1, workers)
    if workers == "auto":
        return max(1, os.cpu_count() or 1)
    return max(1, int(workers))


def _evaluate_candidate_configs(
    stage_name: str,
    authored_config: Mapping[str, Any],
    authored_weighted_area_error: float,
    candidate_configs: Sequence[Mapping[str, Any]],
    worker_count: int,
) -> List[CandidateResult]:
    args = [
        (
            stage_name,
            copy.deepcopy(dict(authored_config)),
            authored_weighted_area_error,
            copy.deepcopy(dict(config)),
        )
        for config in candidate_configs
    ]
    if worker_count <= 1 or len(args) <= 1:
        return [_evaluate_candidate_config(arg) for arg in args]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(_evaluate_candidate_config, args))


def _evaluate_candidate_config(arg: tuple[str, Dict[str, Any], float, Dict[str, Any]]) -> CandidateResult:
    stage_name, authored_config, authored_weighted_area_error, candidate_config = arg
    surface = generate_inside_surface(candidate_config)
    rejected = rejected_issues(candidate_config, surface.issues)
    return CandidateResult(
        stage=stage_name,
        config=candidate_config,
        surface=surface,
        rejected=rejected,
        objective=_objective(authored_config, candidate_config, surface, rejected, authored_weighted_area_error),
    )


def _search_stages(config: Mapping[str, Any]) -> List[tuple[str, List[str]]]:
    stages: List[tuple[str, List[str]]] = [("authored", [])]
    searched = _searchable_variables(config)
    if searched:
        stages.append(("searched", searched))
    return stages


def _searchable_variables(config: Mapping[str, Any]) -> List[str]:
    variables = []
    for name in ("morph_rate", "n_horizontal", "n_vertical", "mouth_sag", "k_horizontal", "k_vertical"):
        lower, upper = _bounds_for(config, name)
        if not math.isclose(lower, upper, rel_tol=0.0, abs_tol=1e-12):
            variables.append(name)
    return variables


def build_search_space(config: Mapping[str, Any], initial: SurfaceResult) -> SearchSpace:
    width = float(config["mouth"]["width"])
    height = float(config["mouth"]["height"])
    aspect_delta = abs(width - height) / max(width, height)

    coverage_h = profile_coverage(config, "horizontal")
    coverage_v = profile_coverage(config, "vertical")
    coverage_delta = abs(coverage_h - coverage_v) / max(coverage_h, coverage_v, 1e-9)

    initial_error = min(initial.area_fit.rms_log_error, 1.0)
    difficulty = max(aspect_delta, coverage_delta, initial_error)

    ranges = {
        "morph_rate": _effective_range(_bounds_for(config, "morph_rate"), _current_value(config, "morph_rate"), 1.0 + 14.0 * difficulty),
        "n_horizontal": _bounds_for(config, "n_horizontal"),
        "n_vertical": _bounds_for(config, "n_vertical"),
        "mouth_sag": _bounds_for(config, "mouth_sag"),
        "k_horizontal": _bounds_for(config, "k_horizontal"),
        "k_vertical": _bounds_for(config, "k_vertical"),
    }
    expected_s_span = 0.1 + 0.7 * aspect_delta + 0.5 * coverage_delta
    return SearchSpace(
        aspect_delta=aspect_delta,
        coverage_delta=coverage_delta,
        initial_rms_log_area_error=initial_error,
        difficulty=difficulty,
        effective_ranges=ranges,
        expected_s_span=expected_s_span,
    )


def _effective_range(bounds: Sequence[float], current: float, half_width: float) -> tuple[float, float]:
    lower, upper = float(bounds[0]), float(bounds[1])
    return max(lower, current - half_width), min(upper, current + half_width)


def _candidate_configs(
    config: Mapping[str, Any],
    variable_names: Sequence[str],
    search_space: SearchSpace,
) -> Iterable[Dict[str, Any]]:
    rates = _values_for(config, "morph_rate", variable_names, search_space)
    n_hs = _values_for(config, "n_horizontal", variable_names, search_space)
    n_vs = _values_for(config, "n_vertical", variable_names, search_space)
    sags = _values_for(config, "mouth_sag", variable_names, search_space)
    k_hs = _values_for(config, "k_horizontal", variable_names, search_space)
    k_vs = _values_for(config, "k_vertical", variable_names, search_space)
    for rate in rates:
        for n_h in n_hs:
            for n_v in n_vs:
                for sag in sags:
                    for k_h in k_hs:
                        for k_v in k_vs:
                            candidate = copy.deepcopy(dict(config))
                            _set_current_value(candidate, "morph_rate", rate)
                            _set_current_value(candidate, "n_horizontal", n_h)
                            _set_current_value(candidate, "n_vertical", n_v)
                            _set_current_value(candidate, "mouth_sag", sag)
                            _set_current_value(candidate, "k_horizontal", k_h)
                            _set_current_value(candidate, "k_vertical", k_v)
                            yield candidate


def _values_for(
    config: Mapping[str, Any],
    name: str,
    variable_names: Sequence[str],
    search_space: SearchSpace,
) -> List[float]:
    if name not in variable_names:
        return [_current_value(config, name)]
    if name == "morph_rate":
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 6)
    if name in {"n_horizontal", "n_vertical"}:
        return _log_grid(search_space.effective_ranges[name], _current_value(config, name), 6)
    if name == "mouth_sag":
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 6)
    if name in {"k_horizontal", "k_vertical"}:
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 6)
    raise ValueError(f"unknown refinement variable: {name}")


def _current_value(config: Mapping[str, Any], name: str) -> float:
    if name == "morph_rate":
        return morph_rate(config)
    if name == "n_horizontal":
        return profile_n(config, "horizontal")
    if name == "n_vertical":
        return profile_n(config, "vertical")
    if name == "mouth_sag":
        sag = mouth_curvature_sag(config)
        return 0.0 if sag is None else sag
    if name == "k_horizontal":
        return profile_k(config, "horizontal")
    if name == "k_vertical":
        return profile_k(config, "vertical")
    raise ValueError(f"unknown refinement variable: {name}")


def _bounds_for(config: Mapping[str, Any], name: str) -> tuple[float, float]:
    if name == "morph_rate":
        return seeded_bounds(config, ["morph", "rate"])
    if name == "n_horizontal":
        return seeded_bounds(config, ["profiles", "n", "horizontal"])
    if name == "n_vertical":
        return seeded_bounds(config, ["profiles", "n", "vertical"])
    if name == "mouth_sag":
        curvature = config["mouth"]["curvature"]
        sag = mouth_curvature_sag(config)
        bounds = curvature.get("sag_bounds")
        if sag is None:
            return 0.0, 0.0
        if bounds is None:
            return sag, sag
        return float(bounds[0]), float(bounds[1])
    if name == "k_horizontal":
        return seeded_bounds(config, ["profiles", "k", "horizontal"])
    if name == "k_vertical":
        return seeded_bounds(config, ["profiles", "k", "vertical"])
    raise ValueError(f"unknown refinement variable: {name}")


def _set_current_value(config: Dict[str, Any], name: str, value: float) -> None:
    if name == "morph_rate":
        config["morph"]["rate"]["seed"] = value
    elif name == "n_horizontal":
        config["profiles"]["n"]["horizontal"]["seed"] = value
    elif name == "n_vertical":
        config["profiles"]["n"]["vertical"]["seed"] = value
    elif name == "mouth_sag":
        if config["mouth"]["curvature"].get("sag") is not None:
            config["mouth"]["curvature"]["sag"] = value
    elif name == "k_horizontal":
        config["profiles"]["k"]["horizontal"]["seed"] = value
    elif name == "k_vertical":
        config["profiles"]["k"]["vertical"]["seed"] = value
    else:
        raise ValueError(f"unknown refinement variable: {name}")


def _grid(bounds: Sequence[float], current: float, count: int) -> List[float]:
    lower, upper = float(bounds[0]), float(bounds[1])
    if count <= 1 or lower == upper:
        return [lower]
    if count == 2:
        values = [lower, upper]
    else:
        interior_count = max(count - 3, 0)
        values = [lower, current, upper]
        values.extend(
            lower + (upper - lower) * (index + 1) / (interior_count + 1)
            for index in range(interior_count)
        )
    return sorted({round(value, 10) for value in values if lower <= value <= upper})


def _log_grid(bounds: Sequence[float], current: float, count: int) -> List[float]:
    lower, upper = float(bounds[0]), float(bounds[1])
    if count <= 1 or lower == upper:
        return [lower]
    if lower <= 0.0 or upper <= 0.0:
        return _grid(bounds, current, count)
    log_lower = math.log(lower)
    log_upper = math.log(upper)
    if count == 2:
        values = [lower, upper]
    else:
        interior_count = max(count - 3, 0)
        values = [lower, current, upper]
        values.extend(
            math.exp(log_lower + (log_upper - log_lower) * (index + 1) / (interior_count + 1))
            for index in range(interior_count)
        )
    return sorted({round(value, 10) for value in values if lower <= value <= upper})


def _objective(
    authored_config: Mapping[str, Any],
    config: Mapping[str, Any],
    surface: SurfaceResult,
    rejected: Sequence[FeasibilityIssue],
    authored_weighted_area_error: float | None = None,
) -> float:
    if rejected:
        return 1000.0 + len(rejected) + surface.area_fit.rms_log_error
    return objective_score(config, surface, authored_config, authored_weighted_area_error)


def objective_score(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    authored_config: Mapping[str, Any] | None = None,
    authored_weighted_area_error: float | None = None,
) -> float:
    return sum(term.contribution for term in objective_terms(config, surface, authored_config, authored_weighted_area_error))


def objective_terms(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    authored_config: Mapping[str, Any] | None = None,
    authored_weighted_area_error: float | None = None,
) -> List[ObjectiveTerm]:
    authored_config = authored_config if authored_config is not None else config
    s_quality = s_quality_metrics(config, surface)
    profile_smoothness = profile_smoothness_metrics(config)
    radial_basis = radial_basis_deviation_metrics(config, surface)
    morph_timing = morph_timing_metrics(config, surface)
    morph_timing_scale = max(1.0 - morph_timing.z50_limit, 1e-9)
    s_span_scale = max(s_quality.expected_span, 1e-9)
    profile_smoothness_scale = max(profile_smoothness.limit, 1e-9)
    morph_rate_drift = morph_rate_drift_metric(authored_config, config)
    k_drift = k_drift_metric(authored_config, config)
    sag_drift = sag_drift_metric(authored_config, config)
    return [
        _objective_term("morph timing", morph_timing.excess_z50, morph_timing.excess_z50 / morph_timing_scale, float(config["refinement"]["morph_timing_weight"])),
        _objective_term("morph rate drift", morph_rate_drift, morph_rate_drift, float(config["refinement"]["morph_rate_drift_weight"])),
        _objective_term("S span", s_quality.excess_span, s_quality.excess_span / s_span_scale, float(config["refinement"]["s_span_weight"])),
        _objective_term("S smoothness", s_quality.max_adjacent_delta, s_quality.max_adjacent_delta / s_span_scale, float(config["refinement"]["s_smoothness_weight"])),
        _objective_term("radial basis deviation", radial_basis.rms_radius_deviation, radial_basis.rms_radius_deviation, float(config["refinement"]["radial_basis_weight"])),
        _objective_term(
            "radial exit slope deviation",
            radial_basis.rms_exit_slope_deviation,
            radial_basis.rms_exit_slope_deviation,
            float(config["refinement"]["radial_exit_slope_weight"]),
        ),
        _objective_term("K drift", k_drift, k_drift, float(config["refinement"]["k_drift_weight"])),
        _objective_term("sag drift", sag_drift, sag_drift, float(config["refinement"]["sag_drift_weight"])),
        _objective_term("profile smoothness", profile_smoothness.excess, profile_smoothness.excess / profile_smoothness_scale, float(config["refinement"]["profile_smoothness_weight"])),
    ]


def _objective_term(name: str, raw_value: float, normalized_value: float, weight: float) -> ObjectiveTerm:
    normalized_value = normalized_value if math.isfinite(normalized_value) else 0.0
    return ObjectiveTerm(
        name=name,
        raw_value=raw_value,
        normalized_value=normalized_value,
        weight=weight,
        contribution=weight * normalized_value,
    )


def _stage_summary(stage_name: str, candidates: Sequence[CandidateResult], best: CandidateResult) -> str:
    valid_count = sum(1 for candidate in candidates if candidate.is_valid)
    return (
        f"{stage_name}: evaluated {len(candidates)} designs, {valid_count} valid, "
        f"best RMS log area error {best.surface.area_fit.rms_log_error:.6g}"
    )


def _plot_area_fit(
    initial_sections: Sequence[SectionSample],
    output_sections: Sequence[SectionSample],
    path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    scale = plotted_target_area_normalizer(output_sections)
    ax.plot(
        [section.z_ref for section in initial_sections],
        [section.actual_area / scale for section in initial_sections],
        label="authored area",
    )
    ax.plot(
        [section.z_ref for section in output_sections],
        [section.actual_area / scale for section in output_sections],
        label="output area",
    )
    ax.plot(
        [section.z_ref for section in output_sections],
        [section.target_area / scale for section in output_sections],
        label="target area",
    )
    ax.set_title("Area Fit")
    ax.set_xlabel("reference z (mm)")
    ax.set_ylabel("area / target area at plotted end")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_hv_profiles(config: Mapping[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    derived, profiles = solve_principal_profiles(config)
    plot_config = _plot_sampling_config(config)
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    for profile in profiles:
        plot_points = sample_profile(
            plot_config,
            derived,
            profile.axis,
            profile.local_length,
            profile.profile_length,
            profile.coverage_deg,
            profile.k,
            profile.solved_s,
        )
        (line,) = ax.plot(
            [point.z for point in plot_points],
            [point.radius for point in plot_points],
            linewidth=2.0,
            label=f"{profile.axis} profile",
        )
        zero_s_points = sample_profile(
            plot_config,
            derived,
            profile.axis,
            profile.local_length,
            profile.profile_length,
            profile.coverage_deg,
            profile.k,
            0.0,
        )
        ax.plot(
            [point.z for point in zero_s_points],
            [point.radius for point in zero_s_points],
            color=line.get_color(),
            linestyle="--",
            linewidth=1.5,
            label=f"{profile.axis} S=0",
        )
    ax.set_title("Horizontal / Vertical Profiles")
    ax.set_xlabel("z (mm)")
    ax.set_ylabel("radius (mm)")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_sampling_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    plot_config = copy.deepcopy(dict(config))
    plot_config["resolution"] = dict(config["resolution"])
    plot_config["resolution"]["length_segments"] = max(int(config["resolution"]["length_segments"]) * 4, 400)
    return plot_config


def _plot_radial_profiles(config: Mapping[str, Any], surface: SurfaceResult, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curves = _diagnostic_first_quadrant_curves(config, surface, count=9)
    transition_angle = _transition_center_angle_deg(surface)
    key_curves = {
        _nearest_curve(curves, 0.0).p_deg: "horizontal",
        _nearest_curve(curves, transition_angle).p_deg: "transition",
        _nearest_curve(curves, 90.0).p_deg: "vertical",
    }
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    for curve in curves:
        segment_count = max(int(config["resolution"]["length_segments"]), 1)
        z_values = [
            min(curve.local_length, curve.local_length * index / segment_count)
            for index in range(segment_count + 1)
        ]
        radii = [radial_curve_distance_at_z(config, surface.derived, curve, z) for z in z_values]
        key_label = key_curves.get(curve.p_deg)
        if key_label is not None:
            ax.plot(
                z_values,
                radii,
                color="black",
                linewidth=2.8,
                linestyle="--" if key_label == "transition" else "-",
                label=f"{key_label} p={curve.p_deg:.0f} deg",
            )
        else:
            ax.plot(z_values, radii, linewidth=1.4, alpha=0.9, label=f"p={curve.p_deg:.0f} deg")
    ax.set_title("Radial Profile Sweep")
    ax.set_xlabel("z (mm)")
    ax.set_ylabel("boundary distance (mm)")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.legend(loc="best", ncols=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_radial_plan(surface: SurfaceResult, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.8, 5.8), dpi=140)
    x_values = [curve.boundary_x for curve in surface.radial_curves]
    y_values = [curve.boundary_y for curve in surface.radial_curves]
    closed_x = x_values + [x_values[0]]
    closed_y = y_values + [y_values[0]]
    ax.plot(closed_x, closed_y, color="black", linewidth=1.8)

    for curve in surface.radial_curves:
        is_axis = curve.p_deg in {0.0, 90.0, 180.0, 270.0}
        p = math.radians(curve.p_deg)
        throat_x = surface.derived.r0 * math.cos(p)
        throat_y = surface.derived.r0 * math.sin(p)
        ax.plot(
            [throat_x, curve.boundary_x],
            [throat_y, curve.boundary_y],
            color="black" if is_axis else "#4c78a8",
            linewidth=1.4 if is_axis else 0.55,
            alpha=0.95 if is_axis else 0.45,
        )
    ax.scatter(x_values, y_values, s=10, color="#f58518", zorder=3)
    throat = plt.Circle((0.0, 0.0), surface.derived.r0, fill=False, color="black", linewidth=1.4, zorder=4)
    ax.add_patch(throat)
    ax.set_title("Radial Profile Plan View")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _diagnostic_first_quadrant_curves(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    count: int,
) -> List[RadialCurve]:
    transition_angle = _transition_center_angle_deg(surface)
    target_angles = [math.radians(90.0 * index / (count - 1)) for index in range(count)]
    target_angles.append(math.radians(transition_angle))
    selected = [radial_curve_at_angle(config, surface.derived, angle) for angle in target_angles]
    return sorted({curve.p_deg: curve for curve in selected}.values(), key=lambda curve: curve.p_deg)


def _transition_center_angle_deg(surface: SurfaceResult) -> float:
    return math.degrees(math.atan2(surface.derived.mouth_half_height, surface.derived.mouth_half_width))


def _nearest_curve(curves: Sequence[RadialCurve], p_deg: float) -> RadialCurve:
    return min(curves, key=lambda curve: abs(curve.p_deg - p_deg))


def _write_output_report(
    project_path: Path,
    result: RefinementResult,
    artifacts: Mapping[str, Path],
) -> None:
    initial_fit = result.initial.area_fit
    best_fit = result.best.surface.area_fit
    initial_area_zones = area_zone_metrics(result.initial.sections)
    best_area_zones = area_zone_metrics(result.best.surface.sections)
    best_config = result.best.config
    tolerance = float(best_config["refinement"]["area_rms_log_tolerance"])
    smoothness = log_area_slope_change(result.best.surface.sections)
    smoothness_limit = float(best_config["refinement"]["max_log_area_slope_change"])
    s_quality = s_quality_metrics(best_config, result.best.surface)
    profile_smoothness = profile_smoothness_metrics(best_config)
    radial_basis = radial_basis_deviation_metrics(best_config, result.best.surface)
    morph_timing = morph_timing_metrics(best_config, result.best.surface)
    roundover_rows = roundover_target_rows(best_config)
    length_recommendations = roundover_length_recommendations(best_config)
    terms = objective_terms(
        best_config,
        result.best.surface,
        result.authored_config,
        initial_area_zones.weighted_rms_log_error,
    )
    _, master_profiles = solve_principal_profiles(best_config)
    searched_variables = _searchable_variables(best_config)
    mode = surface_mode(best_config)
    direct_mode = mode == "slice"
    lines = [
        f"# HornCAD Output: {project_path.stem}",
        "",
        "## Solver Model",
        "",
        f"- Surface mode: {mode}",
        "- Hard constraint: mouth boundary fit",
        "- Fixed authored value: coverage",
        "- Internal dependent solve: S(p), solved from authored profile values",
        "- Fixed Q: 0.995",
        "- Area reference: polar-area-weighted circular OS-SE reference using each design's H/V N values",
        (
            "- Output surface: H/V basis profiles lofted through superellipse slices"
            if direct_mode
            else "- Output surface: radial profile family generated by candidate search"
        ),
        (
            "- Search variables from bounds: none; bounds are ignored in slice mode"
            if direct_mode
            else "- Search variables from bounds: " + (", ".join(searched_variables) if searched_variables else "none")
        ),
    ]
    if not direct_mode:
        lines.extend(
            [
                "",
                "## Effective Search Space",
                "",
                _markdown_table(
                    ["Metric", "Value"],
                    [
                        ["Mouth aspect delta", f"{result.search_space.aspect_delta:.6g}"],
                        ["Coverage delta", f"{result.search_space.coverage_delta:.6g}"],
                        ["Authored RMS log area error used for scaling", f"{result.search_space.initial_rms_log_area_error:.6g}"],
                        ["Search difficulty", f"{result.search_space.difficulty:.6g}"],
                        ["Morph rate range", _format_range(result.search_space.effective_ranges["morph_rate"])],
                        ["Horizontal N range", _format_range(result.search_space.effective_ranges["n_horizontal"])],
                        ["Vertical N range", _format_range(result.search_space.effective_ranges["n_vertical"])],
                        ["Mouth sag range", _format_range(result.search_space.effective_ranges["mouth_sag"])],
                        ["Horizontal K range", _format_range(result.search_space.effective_ranges["k_horizontal"])],
                        ["Vertical K range", _format_range(result.search_space.effective_ranges["k_vertical"])],
                    ],
                ),
            ]
        )
    lines.extend(
        [
        "",
        "## Sampling",
        "",
        _markdown_table(
            ["Item", "Behavior"],
            [
                ["Surface sections", "superellipse slices from H/V basis profiles" if direct_mode else "radial profile sections"],
                ["Angular radial curves", "diagnostic only in slice mode" if direct_mode else "adaptive by mouth-boundary change"],
                ["Profile z samples", "adaptive by radial curve change"],
                ["Section z samples", "adaptive by target reference-radius change"],
                ["Configured length segments", str(best_config["resolution"]["length_segments"])],
                ["Configured angular segments", str(best_config["resolution"]["angular_segments"])],
            ],
        ),
        "",
        "## Selected Design",
        "",
        _markdown_table(
            ["Field", "Value"],
            [
                ["Valid under reject_if", "yes" if result.best.is_valid else "no"],
                ["Workers", "not used" if direct_mode else str(result.workers)],
                ["Morph rate", f"{morph_rate(best_config):.6g}"],
                ["Horizontal N", f"{profile_n(best_config, 'horizontal'):.6g}"],
                ["Vertical N", f"{profile_n(best_config, 'vertical'):.6g}"],
                ["Fixed Q", f"{profile_q(best_config):.6g}"],
                ["Mouth sag", _format_optional_number(mouth_curvature_sag(best_config))],
                ["Horizontal K", f"{profile_k(best_config, 'horizontal'):.6g}"],
                ["Vertical K", f"{profile_k(best_config, 'vertical'):.6g}"],
                ["H/V S range" if direct_mode else "S range", _governing_s_range(master_profiles) if direct_mode else _s_range(result.best.surface)],
                ["Shared section length", f"{result.best.surface.shared_section_length:.6g} mm"],
                ["Area RMS log tolerance", f"{tolerance:.6g}"],
                ["Area tolerance met", "yes" if best_fit.rms_log_error <= tolerance else "no"],
                ["Objective score", "not used" if direct_mode else f"{sum(term.contribution for term in terms):.6g}"],
                ["Inside surface shape power", f"{INSIDE_SURFACE_SHAPE_POWER:.6g}"],
            ],
        ),
        "",
    ])
    if not direct_mode:
        lines.extend(
            [
                "## Objective Breakdown",
                "",
                _markdown_table(
                    ["Term", "Raw", "Normalized", "Weight", "Contribution"],
                    [
                        [
                            term.name,
                            f"{term.raw_value:.6g}",
                            f"{term.normalized_value:.6g}",
                            f"{term.weight:.6g}",
                            f"{term.contribution:.6g}",
                        ]
                        for term in terms
                    ],
                ),
                "",
            ]
        )
    lines.extend([
        "## H/V Master Profiles",
        "",
        _markdown_table(
            [
                "Axis",
                "Coverage deg",
                "K",
                "Local length mm",
                "Profile length mm",
                "Target boundary mm",
                "Solved S",
                "Boundary error mm",
            ],
            [
                [
                    profile.axis,
                    f"{profile.coverage_deg:.6g}",
                    f"{profile.k:.6g}",
                    f"{profile.local_length:.6g}",
                    f"{profile.profile_length:.6g}",
                    f"{profile.target_boundary_distance:.6g}",
                    f"{profile.solved_s:.6g}",
                    f"{profile.boundary_fit_error:.6g}",
                ]
                for profile in master_profiles
            ],
        ),
        "",
        "## Roundover Diagnostics",
        "",
        _roundover_diagnostics_table(roundover_rows),
        *(
            [
                "",
                "## Roundover Length Guidance",
                "",
                _markdown_table(
                    [
                        "Axis",
                        "Target %",
                        "Current %",
                        "Required change in length.max mm",
                        "Required S",
                        "Note",
                    ],
                    [
                        [
                            item.axis,
                            _format_optional_number(item.target_percent),
                            _format_optional_number(item.current_percent),
                            _format_optional_signed_number(item.required_length_change),
                            _format_optional_number(item.required_s),
                            item.note,
                        ]
                        for item in length_recommendations
                    ],
                ),
            ]
            if length_recommendations
            else []
        ),
        "",
        "## Area Fit",
        "",
        _markdown_table(
            ["Metric", "Authored", "Output"],
            [
                ["Weighted RMS log area error", f"{initial_area_zones.weighted_rms_log_error:.6g}", f"{best_area_zones.weighted_rms_log_error:.6g}"],
                ["Throat third RMS log area error", f"{initial_area_zones.throat_rms_log_error:.6g}", f"{best_area_zones.throat_rms_log_error:.6g}"],
                ["Middle third RMS log area error", f"{initial_area_zones.middle_rms_log_error:.6g}", f"{best_area_zones.middle_rms_log_error:.6g}"],
                ["Mouth third RMS log area error", f"{initial_area_zones.mouth_rms_log_error:.6g}", f"{best_area_zones.mouth_rms_log_error:.6g}"],
                ["Area fit score", f"{initial_fit.score:.6g}", f"{best_fit.score:.6g}"],
                ["RMS log area error", f"{initial_fit.rms_log_error:.6g}", f"{best_fit.rms_log_error:.6g}"],
                ["RMS area error", f"{initial_fit.rms_percent_error * 100.0:.6g}%", f"{best_fit.rms_percent_error * 100.0:.6g}%"],
                ["Max area error", "", f"{best_fit.max_abs_percent_error * 100.0:.6g}%"],
                ["Worst reference z", "", f"{best_fit.worst_z_ref:.6g} mm"],
            ],
        ),
        "",
        "## Smoothness",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Max log-area slope change", f"{smoothness:.6g}"],
                ["Max log-area slope change limit", f"{smoothness_limit:.6g}"],
                ["Smoothness check", "passed" if smoothness <= smoothness_limit else "warning"],
                *([] if direct_mode else [["Smoothness objective weight", f"{float(best_config['refinement']['smoothness_weight']):.6g}"]]),
            ],
        ),
        "",
        "## Radial Diagnostic S Behavior" if direct_mode else "## S Behavior",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["S min", f"{s_quality.minimum:.6g}"],
                ["S max", f"{s_quality.maximum:.6g}"],
                ["S span", f"{s_quality.span:.6g}"],
                ["Expected S span", f"{s_quality.expected_span:.6g}"],
                ["Excess S span", f"{s_quality.excess_span:.6g}"],
                ["RMS S deviation", f"{s_quality.rms_deviation:.6g}"],
                ["Max adjacent S change over p", f"{s_quality.max_adjacent_delta:.6g}"],
                *(
                    []
                    if direct_mode
                    else [
                        ["S span objective weight", f"{float(best_config['refinement']['s_span_weight']):.6g}"],
                        ["S smoothness objective weight", f"{float(best_config['refinement']['s_smoothness_weight']):.6g}"],
                    ]
                ),
            ],
        ),
        "",
        "## Radial Basis Coherence",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["RMS radial basis deviation", f"{radial_basis.rms_radius_deviation:.6g}"],
                ["Max radial basis deviation", f"{radial_basis.max_radius_deviation:.6g}"],
                ["RMS exit slope deviation", f"{radial_basis.rms_exit_slope_deviation:.6g}"],
                *(
                    []
                    if direct_mode
                    else [
                        ["Radial basis objective weight", f"{float(best_config['refinement']['radial_basis_weight']):.6g}"],
                        ["Radial exit slope objective weight", f"{float(best_config['refinement']['radial_exit_slope_weight']):.6g}"],
                    ]
                ),
            ],
        ),
        "",
        "## Morph Timing",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["z50", f"{morph_timing.z50_fraction * 100.0:.6g}% of length"],
                ["z90", f"{morph_timing.z90_fraction * 100.0:.6g}% of length"],
                ["z50 limit", f"{morph_timing.z50_limit * 100.0:.6g}% of length"],
                ["Excess z50", f"{morph_timing.excess_z50 * 100.0:.6g}% of length"],
                *(
                    []
                    if direct_mode
                    else [
                        ["Morph timing objective weight", f"{float(best_config['refinement']['morph_timing_weight']):.6g}"],
                        ["Morph rate drift objective weight", f"{float(best_config['refinement']['morph_rate_drift_weight']):.6g}"],
                    ]
                ),
            ],
        ),
        "",
        "## Profile Smoothness",
        "",
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Max H/V profile slope change", f"{profile_smoothness.max_slope_change:.6g}"],
                ["Max H/V profile slope change limit", f"{profile_smoothness.limit:.6g}"],
                ["Excess H/V profile slope change", f"{profile_smoothness.excess:.6g}"],
                ["Profile smoothness check", "passed" if profile_smoothness.excess <= 0.0 else "warning"],
                *([] if direct_mode else [["Profile smoothness objective weight", f"{float(best_config['refinement']['profile_smoothness_weight']):.6g}"]]),
            ],
        ),
        "",
        "## Bound Notes",
        "",
    ])
    bound_notes = [] if direct_mode else _bound_notes(best_config)
    if direct_mode:
        lines.append("- Bounds are ignored in slice mode; authored seed values are used directly.")
    elif bound_notes:
        lines.extend(f"- {note}" for note in bound_notes)
    else:
        lines.append("- Selected design did not land on a searched parameter bound.")
    if not direct_mode:
        lines.extend(
            [
                "",
                "## Search Summary",
                "",
                f"- Designs evaluated: {result.candidates_evaluated}",
                f"- Designs rejected by configured hard constraints: {result.candidates_rejected}",
            ]
        )
    lines.extend(["", "## Warnings And Infeasible Conditions", ""])
    if result.best.surface.issues:
        for issue in result.best.surface.issues:
            lines.append(f"- `{issue.code}`: {issue.message}")
            lines.append(f"  Likely culprit: {issue.likely_culprit}")
    else:
        lines.append("- None")
    lines.extend(["", "## Generated Artifacts", ""])
    artifact_labels = {
        "area_fit": "Area fit",
        "hv_profiles": "H/V profiles",
        "inside_surface": "Inside surface",
        "radial_plan": "Radial plan",
        "radial_profiles": "Radial profiles",
        "report": "Report",
    }
    for name in ("area_fit", "hv_profiles", "inside_surface", "radial_plan", "radial_profiles", "report"):
        path = artifacts.get(name)
        if path is not None:
            lines.append(f"- {artifact_labels[name]}: `{path}`")
    lines.append("")
    artifacts["report"].write_text("\n".join(lines), encoding="utf-8")


def _s_range(surface: SurfaceResult) -> str:
    values = [curve.solved_s for curve in surface.radial_curves if math.isfinite(curve.solved_s)]
    if not values:
        return "none"
    return f"{min(values):.6g}..{max(values):.6g}"


def _governing_s_range(profiles: Sequence[Any]) -> str:
    values = [profile.solved_s for profile in profiles if math.isfinite(profile.solved_s)]
    if not values:
        return "none"
    return f"{min(values):.6g}..{max(values):.6g}"


def _format_range(values: tuple[float, float]) -> str:
    return f"{values[0]:.6g}..{values[1]:.6g}"


def _format_optional_number(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.6g}"


def _format_optional_signed_number(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:+.6g}"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


def _roundover_diagnostics_table(rows: Sequence[RoundoverTargetRow]) -> str:
    has_targets = any(row.target_percent is not None for row in rows)
    if not has_targets:
        return _markdown_table(
            ["Axis", "Roundover contribution %"],
            [[row.axis, f"{row.actual_percent:.6g}"] for row in rows],
        )
    return _markdown_table(
        [
            "Axis",
            "Roundover contribution %",
            "Target %",
            "Tolerance %",
            "Excess miss %",
        ],
        [
            [
                row.axis,
                f"{row.actual_percent:.6g}",
                _format_optional_number(row.target_percent),
                _format_optional_number(row.tolerance_percent),
                _format_optional_number(row.excess_miss_percent),
            ]
            for row in rows
        ],
    )


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def area_zone_metrics(sections: Sequence[SectionSample]) -> AreaZoneMetrics:
    if not sections:
        return AreaZoneMetrics(0.0, 0.0, 0.0, 0.0)
    return AreaZoneMetrics(
        weighted_rms_log_error=_weighted_area_rms_log_error(sections),
        throat_rms_log_error=_zone_rms_log_error(sections, 0.0, 1.0 / 3.0),
        middle_rms_log_error=_zone_rms_log_error(sections, 1.0 / 3.0, 2.0 / 3.0),
        mouth_rms_log_error=_zone_rms_log_error(sections, 2.0 / 3.0, 1.0),
    )


def _weighted_area_rms_log_error(sections: Sequence[SectionSample]) -> float:
    total_weight = 0.0
    weighted_error = 0.0
    for section in sections:
        station = min(max(section.station, 0.0), 1.0)
        weight = 0.15 + 0.85 * (1.0 - station) ** 2
        total_weight += weight
        weighted_error += weight * section.log_area_error**2
    return math.sqrt(weighted_error / max(total_weight, 1e-12))


def _zone_rms_log_error(sections: Sequence[SectionSample], lower: float, upper: float) -> float:
    if upper >= 1.0:
        selected = [section for section in sections if lower <= section.station <= upper]
    else:
        selected = [section for section in sections if lower <= section.station < upper]
    if not selected:
        return 0.0
    return math.sqrt(sum(section.log_area_error**2 for section in selected) / len(selected))


def s_quality_metrics(config: Mapping[str, Any], surface: SurfaceResult) -> SQuality:
    values = [curve.solved_s for curve in surface.radial_curves if math.isfinite(curve.solved_s)]
    if not values:
        return SQuality(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    mean = sum(values) / len(values)
    rms = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    max_adjacent = max(
        abs(current - previous)
        for previous, current in zip(values, values[1:] + values[:1])
    )
    width = float(config["mouth"]["width"])
    height = float(config["mouth"]["height"])
    aspect_delta = abs(width - height) / max(width, height)
    coverage_h = profile_coverage(config, "horizontal")
    coverage_v = profile_coverage(config, "vertical")
    coverage_delta = abs(coverage_h - coverage_v) / max(coverage_h, coverage_v, 1e-9)
    expected = 0.1 + 0.7 * aspect_delta + 0.5 * coverage_delta
    return SQuality(
        minimum=minimum,
        maximum=maximum,
        span=span,
        expected_span=expected,
        excess_span=max(0.0, span - expected),
        rms_deviation=rms,
        max_adjacent_delta=max_adjacent,
    )


def log_area_slope_change(sections: Sequence[SectionSample]) -> float:
    if len(sections) < 3:
        return 0.0
    slopes = []
    for previous, current in zip(sections, sections[1:]):
        dz = current.z_ref - previous.z_ref
        if dz <= 0.0 or previous.actual_area <= 0.0 or current.actual_area <= 0.0:
            continue
        slopes.append((math.log(current.actual_area) - math.log(previous.actual_area)) / dz)
    if len(slopes) < 2:
        return 0.0
    return max(abs(current - previous) for previous, current in zip(slopes, slopes[1:]))


def profile_smoothness_metrics(config: Mapping[str, Any]) -> ProfileSmoothness:
    _, profiles = solve_principal_profiles(config)
    max_change = 0.0
    for profile in profiles:
        osse_points = [point for point in profile.points if point.segment == "osse"]
        slopes = []
        for previous, current in zip(osse_points, osse_points[1:]):
            dz = current.z - previous.z
            if dz > 0.0:
                slopes.append((current.radius - previous.radius) / dz)
        if len(slopes) >= 2:
            max_change = max(
                max_change,
                max(abs(current - previous) for previous, current in zip(slopes, slopes[1:])),
            )
    limit = float(config["refinement"]["max_profile_slope_change"])
    return ProfileSmoothness(
        max_slope_change=max_change,
        limit=limit,
        excess=max(0.0, max_change - limit),
    )


def radial_basis_deviation_metrics(config: Mapping[str, Any], surface: SurfaceResult) -> RadialBasisDeviation:
    curves = surface.radial_curves
    if len(curves) < 3:
        return RadialBasisDeviation(0.0, 0.0, 0.0)

    horizontal = _nearest_curve(curves, 0.0)
    vertical = _nearest_curve(curves, 90.0)
    radius_errors = []
    slope_errors = []
    fractions = [index / 16.0 for index in range(17)]
    for curve in curves:
        p = math.radians(curve.p_deg)
        for fraction in fractions:
            actual = radial_curve_distance_at_z(config, surface.derived, curve, curve.local_length * fraction)
            expected = _basis_radius_at_fraction(config, surface, horizontal, vertical, p, fraction)
            scale = max(expected, curve.boundary_distance, 1.0)
            radius_errors.append((actual - expected) / scale)
        actual_slope = _curve_slope_at_fraction(config, surface, curve, 0.98, 1.0)
        expected_slope = interpolate_principal_value(
            _curve_slope_at_fraction(config, surface, horizontal, 0.98, 1.0),
            _curve_slope_at_fraction(config, surface, vertical, 0.98, 1.0),
            p,
        )
        slope_errors.append(actual_slope - expected_slope)

    rms_radius = math.sqrt(sum(error * error for error in radius_errors) / len(radius_errors)) if radius_errors else 0.0
    max_radius = max((abs(error) for error in radius_errors), default=0.0)
    rms_slope = math.sqrt(sum(error * error for error in slope_errors) / len(slope_errors)) if slope_errors else 0.0
    return RadialBasisDeviation(
        rms_radius_deviation=rms_radius,
        max_radius_deviation=max_radius,
        rms_exit_slope_deviation=rms_slope,
    )


def _basis_radius_at_fraction(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    horizontal: RadialCurve,
    vertical: RadialCurve,
    p: float,
    fraction: float,
) -> float:
    horizontal_radius = radial_curve_distance_at_z(config, surface.derived, horizontal, horizontal.local_length * fraction)
    vertical_radius = radial_curve_distance_at_z(config, surface.derived, vertical, vertical.local_length * fraction)
    return interpolate_principal_value(horizontal_radius, vertical_radius, p)


def _curve_slope_at_fraction(
    config: Mapping[str, Any],
    surface: SurfaceResult,
    curve: RadialCurve,
    lower_fraction: float,
    upper_fraction: float,
) -> float:
    lower_z = curve.local_length * lower_fraction
    upper_z = curve.local_length * upper_fraction
    if upper_z <= lower_z:
        return 0.0
    lower_radius = radial_curve_distance_at_z(config, surface.derived, curve, lower_z)
    upper_radius = radial_curve_distance_at_z(config, surface.derived, curve, upper_z)
    return (upper_radius - lower_radius) / (upper_z - lower_z)


def morph_rate_drift_metric(authored_config: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    authored = morph_rate(authored_config)
    current = morph_rate(config)
    if current <= authored:
        return 0.0
    lower, upper = _bounds_for(authored_config, "morph_rate")
    span = max(upper - authored, authored - lower, 1e-9)
    return (current - authored) / span


def k_drift_metric(authored_config: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    values = []
    for axis, name in (("horizontal", "k_horizontal"), ("vertical", "k_vertical")):
        lower, upper = _bounds_for(authored_config, name)
        span = max(upper - lower, 1e-9)
        values.append((profile_k(config, axis) - profile_k(authored_config, axis)) / span)
    return math.sqrt(sum(value * value for value in values) / len(values))


def sag_drift_metric(authored_config: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    authored = mouth_curvature_sag(authored_config)
    current = mouth_curvature_sag(config)
    if authored is None or current is None:
        return 0.0
    lower, upper = _bounds_for(authored_config, "mouth_sag")
    span = max(upper - lower, 1e-9)
    return abs(current - authored) / span


def roundover_target_rows(config: Mapping[str, Any]) -> List[RoundoverTargetRow]:
    _, profiles = solve_principal_profiles(config)
    rows = []
    for profile in profiles:
        actual = roundover_metrics(profile).roundover_contribution_percent
        target = profile_roundover_target_percent(config, profile.axis)
        tolerance = profile_roundover_tolerance_percent(config, profile.axis)
        excess = None if target is None or tolerance is None else max(0.0, abs(actual - target) - tolerance)
        rows.append(
            RoundoverTargetRow(
                axis=profile.axis,
                target_percent=target,
                actual_percent=actual,
                tolerance_percent=tolerance,
                excess_miss_percent=excess,
            )
        )
    return rows


def roundover_target_penalty(config: Mapping[str, Any]) -> float:
    rows = [row for row in roundover_target_rows(config) if row.excess_miss_percent is not None]
    if not rows:
        return 0.0
    rms_excess_percent = math.sqrt(sum(float(row.excess_miss_percent) ** 2 for row in rows) / len(rows))
    return rms_excess_percent / 100.0


def roundover_length_recommendations(config: Mapping[str, Any]) -> List[RoundoverLengthRecommendation]:
    return [
        recommendation
        for recommendation in (
            _roundover_length_recommendation_for_axis(config, "horizontal"),
            _roundover_length_recommendation_for_axis(config, "vertical"),
        )
        if recommendation is not None
    ]


def _roundover_length_recommendation_for_axis(
    config: Mapping[str, Any],
    axis: str,
) -> RoundoverLengthRecommendation | None:
    target = profile_roundover_target_percent(config, axis)
    if target is None:
        return None
    current_length = float(config["length"]["max"])
    current_percent, _, _ = _axis_roundover_at_length(config, axis, current_length)
    if not math.isfinite(current_percent):
        return RoundoverLengthRecommendation(axis, target, current_percent, None, None, None, None, "current profile is invalid")

    low, high = _length_search_bounds(config, axis, current_length)
    low_percent, _, _ = _axis_roundover_at_length(config, axis, low)
    high_percent, _, _ = _axis_roundover_at_length(config, axis, high)
    attempts = 0
    while math.isfinite(high_percent) and high_percent > target and attempts < 8:
        high *= 2.0
        high_percent, _, _ = _axis_roundover_at_length(config, axis, high)
        attempts += 1

    if not (math.isfinite(low_percent) and math.isfinite(high_percent)):
        return RoundoverLengthRecommendation(axis, target, current_percent, None, None, None, None, "could not bracket target")

    upper_reachable = max(low_percent, high_percent)
    lower_reachable = min(low_percent, high_percent)
    if target > upper_reachable:
        return RoundoverLengthRecommendation(axis, target, current_percent, None, None, None, None, "target requires less than minimum valid length")
    if target < lower_reachable:
        return RoundoverLengthRecommendation(axis, target, current_percent, None, None, None, None, "target requires more than searched maximum length")

    left = low
    right = high
    for _ in range(80):
        middle = (left + right) / 2.0
        middle_percent, _, _ = _axis_roundover_at_length(config, axis, middle)
        if not math.isfinite(middle_percent):
            left = middle
            continue
        if middle_percent > target:
            left = middle
        else:
            right = middle
    required_length = (left + right) / 2.0
    _, required_s, _ = _axis_roundover_at_length(config, axis, required_length)
    return RoundoverLengthRecommendation(
        axis=axis,
        target_percent=target,
        current_percent=current_percent,
        required_length=required_length,
        required_length_change=required_length - current_length,
        required_s=required_s,
        valid_s=None,
        note="exact target length estimate",
    )


def _length_search_bounds(config: Mapping[str, Any], axis: str, current_length: float) -> tuple[float, float]:
    derived, profiles = solve_principal_profiles(config)
    profile = next(item for item in profiles if item.axis == axis)
    setback = current_length - profile.local_length
    low = max(setback + derived.l_conic + 1e-6, 1e-6)
    high = max(current_length * 4.0, low + 1000.0)
    return low, high


def _axis_roundover_at_length(config: Mapping[str, Any], axis: str, length_max: float) -> tuple[float, float | None, bool | None]:
    candidate = copy.deepcopy(dict(config))
    candidate["length"]["max"] = length_max
    _, profiles = solve_principal_profiles(candidate)
    profile = next(item for item in profiles if item.axis == axis)
    if profile.profile_length <= 0.0:
        return math.nan, None, None
    return (
        roundover_metrics(profile).roundover_contribution_percent,
        profile.solved_s,
        None,
    )


def morph_timing_metrics(config: Mapping[str, Any], surface: SurfaceResult | None = None) -> MorphTiming:
    z50_limit = float(config["refinement"]["morph_50_percent_max_z"])
    if surface is None:
        rate = morph_rate(config)
        z50 = _morph_progress_at_weight(rate, 0.5)
        z90 = _morph_progress_at_weight(rate, 0.9)
    else:
        z50 = _morph_section_fraction_at_weight(surface, 0.5)
        z90 = _morph_section_fraction_at_weight(surface, 0.9)
    return MorphTiming(
        z50_fraction=z50,
        z90_fraction=z90,
        z50_limit=z50_limit,
        excess_z50=max(0.0, z50 - z50_limit),
    )


def _morph_progress_at_weight(rate: float, weight: float) -> float:
    if rate <= 0.0:
        return 0.0
    return min(max(weight * rate, 0.0), 1.0)


def _morph_section_fraction_at_weight(surface: SurfaceResult, weight: float) -> float:
    if not surface.sections or surface.shared_section_length <= 0.0:
        return 0.0
    previous = surface.sections[0]
    if previous.morph_weight >= weight:
        return previous.z_ref / surface.shared_section_length
    for current in surface.sections[1:]:
        if current.morph_weight >= weight:
            span = current.morph_weight - previous.morph_weight
            fraction = 0.0 if span <= 1e-12 else (weight - previous.morph_weight) / span
            z = previous.z_ref + (current.z_ref - previous.z_ref) * fraction
            return min(max(z / surface.shared_section_length, 0.0), 1.0)
        previous = current
    return 1.0


def _bound_notes(config: Mapping[str, Any]) -> List[str]:
    notes = []
    checks = [
        ("Morph rate", morph_rate(config), _bounds_for(config, "morph_rate")),
        ("Horizontal N", profile_n(config, "horizontal"), _bounds_for(config, "n_horizontal")),
        ("Vertical N", profile_n(config, "vertical"), _bounds_for(config, "n_vertical")),
        ("Mouth sag", mouth_curvature_sag(config), _bounds_for(config, "mouth_sag")),
        ("Horizontal K", profile_k(config, "horizontal"), _bounds_for(config, "k_horizontal")),
        ("Vertical K", profile_k(config, "vertical"), _bounds_for(config, "k_vertical")),
    ]
    for label, value, bounds in checks:
        if value is None:
            continue
        lower, upper = float(bounds[0]), float(bounds[1])
        if math.isclose(lower, upper, rel_tol=0.0, abs_tol=1e-12):
            continue
        if math.isclose(value, lower, rel_tol=0.0, abs_tol=1e-9):
            notes.append(f"{label} landed on lower search bound {lower:.6g}.")
        elif math.isclose(value, upper, rel_tol=0.0, abs_tol=1e-9):
            notes.append(f"{label} landed on upper search bound {upper:.6g}.")
    return notes


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate HornCAD output artifacts.")
    parser.add_argument("project", type=Path, help="Path to a HornCAD project YAML file.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated output artifacts. Defaults to output/ beside the project file.",
    )
    parser.add_argument(
        "--workers",
        default=None,
        help="Candidate evaluation workers. Use 1 for serial or auto for CPU count.",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = generate_output(args.project, args.output_dir, workers=args.workers)
    except (OSError, yaml.YAMLError, ConfigError, ValueError) as exc:
        if isinstance(exc, OutputFeasibilityError):
            sys.stderr.write("Output feasibility check failed:\n")
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
