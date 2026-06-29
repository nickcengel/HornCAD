"""M3 area-aware refinement search."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import yaml

from horncad.config import ConfigError, dump_config, load_project
from horncad.profile import FeasibilityIssue, solve_principal_profiles
from horncad.surface import (
    RadialCurve,
    SectionSample,
    SurfaceResult,
    generate_inside_surface,
    plotted_target_area_normalizer,
    radial_curve_distance_at_z,
    rejected_issues,
)


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


def generate_refinement_review(project_path: Path, output_dir: Path | None = None) -> Dict[str, Path]:
    project_path = Path(project_path)
    if output_dir is None:
        output_dir = project_path.parent / "refine_review"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_project(project_path)
    result = refine_project(config)

    stem = project_path.stem
    artifacts = {
        "area_fit": output_dir / f"{stem}_refined_area_fit.png",
        "hv_profiles": output_dir / f"{stem}_refined_hv_profiles.png",
        "radial_profiles": output_dir / f"{stem}_refined_radial_profiles.png",
        "report": output_dir / f"{stem}_refinement_report.md",
        "resolved": output_dir / f"{stem}_refined.yaml",
    }

    _plot_refinement_area_fit(
        result.initial.sections,
        result.best.surface.sections,
        artifacts["area_fit"],
    )
    _plot_hv_profiles(result.best.config, artifacts["hv_profiles"])
    _plot_radial_profiles(result.best.config, result.best.surface, artifacts["radial_profiles"])
    artifacts["resolved"].write_text(dump_config(result.best.config), encoding="utf-8")
    _write_refinement_report(project_path, result, artifacts)
    return artifacts


def refine_project(config: Mapping[str, Any]) -> RefinementResult:
    authored_config = copy.deepcopy(dict(config))
    initial = generate_inside_surface(authored_config)
    search_space = build_search_space(authored_config, initial)
    candidates: List[CandidateResult] = []
    stage_summaries: List[str] = []

    for stage_name, variable_names in _search_stages(authored_config):
        stage_candidates = []
        for candidate_config in _candidate_configs(authored_config, variable_names, search_space):
            surface = generate_inside_surface(candidate_config)
            rejected = rejected_issues(candidate_config, surface.issues)
            candidate = CandidateResult(
                stage=stage_name,
                config=candidate_config,
                surface=surface,
                rejected=rejected,
                objective=_objective(candidate_config, surface, rejected),
            )
            candidates.append(candidate)
            stage_candidates.append(candidate)
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
                objective=_objective(authored_config, surface, rejected_issues(authored_config, surface.issues)),
            )
        )
        stage_summaries.append("authored: evaluated 1 candidate")

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
    )


def _search_stages(config: Mapping[str, Any]) -> List[tuple[str, List[str]]]:
    enabled = set(config["refinement"]["solve"])
    stages: List[tuple[str, List[str]]] = [("authored", [])]
    if "morph_rate" in enabled:
        stages.append(("morph_rate", ["morph_rate"]))
    if {"morph_rate", "n"}.issubset(enabled):
        stages.append(("morph_rate+n", ["morph_rate", "n"]))
    if {"morph_rate", "n", "q"}.issubset(enabled):
        stages.append(("morph_rate+n+q", ["morph_rate", "n", "q"]))
    return stages


def build_search_space(config: Mapping[str, Any], initial: SurfaceResult) -> SearchSpace:
    width = float(config["mouth"]["width"])
    height = float(config["mouth"]["height"])
    aspect_delta = abs(width - height) / max(width, height)

    coverage_h = float(config["profiles"]["horizontal"]["coverage"])
    coverage_v = float(config["profiles"]["vertical"]["coverage"])
    coverage_delta = abs(coverage_h - coverage_v) / max(coverage_h, coverage_v, 1e-9)

    initial_error = min(initial.area_fit.rms_log_error, 1.0)
    difficulty = max(aspect_delta, coverage_delta, initial_error)

    ranges = {
        "morph_rate": _effective_range(
            config["refinement"]["morph_rate_bounds"],
            _current_value(config, "morph_rate"),
            1.0 + 14.0 * difficulty,
        ),
        "n": _effective_range(
            config["refinement"]["n_bounds"],
            _current_value(config, "n"),
            0.75 + 5.0 * difficulty,
        ),
        "q": _effective_range(
            config["refinement"]["q_bounds"],
            _current_value(config, "q"),
            0.001 + 0.012 * difficulty,
        ),
    }
    lower_s, upper_s = [float(value) for value in config["osse"]["s_bounds"]]
    expected_s_span = min(upper_s - lower_s, 0.1 + 0.7 * aspect_delta + 0.5 * coverage_delta)
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
    ns = _values_for(config, "n", variable_names, search_space)
    qs = _values_for(config, "q", variable_names, search_space)
    for rate in rates:
        for n in ns:
            for q in qs:
                candidate = copy.deepcopy(dict(config))
                candidate["morph"]["rate"] = rate
                candidate["osse"]["n"] = n
                candidate["osse"]["q"] = q
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
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 13)
    if name == "n":
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 7)
    if name == "q":
        return _grid(search_space.effective_ranges[name], _current_value(config, name), 5)
    raise ValueError(f"unknown refinement variable: {name}")


def _current_value(config: Mapping[str, Any], name: str) -> float:
    if name == "morph_rate":
        return float(config["morph"]["rate"])
    if name == "n":
        return float(config["osse"]["n"])
    if name == "q":
        return float(config["osse"]["q"])
    raise ValueError(f"unknown refinement variable: {name}")


def _grid(bounds: Sequence[float], current: float, count: int) -> List[float]:
    lower, upper = float(bounds[0]), float(bounds[1])
    if count <= 1 or lower == upper:
        return [lower]
    values = [lower + (upper - lower) * index / (count - 1) for index in range(count)]
    values.extend([current, lower, upper])
    return sorted({round(value, 10) for value in values if lower <= value <= upper})


def _objective(config: Mapping[str, Any], surface: SurfaceResult, rejected: Sequence[FeasibilityIssue]) -> float:
    if rejected:
        return 1000.0 + len(rejected) + surface.area_fit.rms_log_error
    smoothness_weight = float(config["refinement"]["smoothness_weight"])
    s_quality = s_quality_metrics(config, surface)
    profile_smoothness = profile_smoothness_metrics(config)
    return (
        surface.area_fit.rms_log_error
        + _s_bound_pressure(config, surface)
        + smoothness_weight * log_area_slope_change(surface.sections)
        + float(config["refinement"]["s_span_weight"]) * s_quality.excess_span
        + float(config["refinement"]["s_smoothness_weight"]) * s_quality.max_adjacent_delta
        + float(config["refinement"]["profile_smoothness_weight"]) * profile_smoothness.excess
    )


def _s_bound_pressure(config: Mapping[str, Any], surface: SurfaceResult) -> float:
    lower, upper = [float(value) for value in config["osse"]["s_bounds"]]
    span = max(upper - lower, 1e-9)
    pressures = []
    for curve in surface.radial_curves:
        distance_to_bound = min(curve.solved_s - lower, upper - curve.solved_s) / span
        pressures.append(max(0.0, 0.2 - distance_to_bound))
    return 0.01 * sum(pressures) / max(len(pressures), 1)


def _stage_summary(stage_name: str, candidates: Sequence[CandidateResult], best: CandidateResult) -> str:
    valid_count = sum(1 for candidate in candidates if candidate.is_valid)
    return (
        f"{stage_name}: evaluated {len(candidates)} candidates, {valid_count} valid, "
        f"best RMS log area error {best.surface.area_fit.rms_log_error:.6g}"
    )


def _plot_refinement_area_fit(
    initial_sections: Sequence[SectionSample],
    refined_sections: Sequence[SectionSample],
    path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    scale = plotted_target_area_normalizer(refined_sections)
    ax.plot(
        [section.z_ref for section in initial_sections],
        [section.actual_area / scale for section in initial_sections],
        label="initial area",
    )
    ax.plot(
        [section.z_ref for section in refined_sections],
        [section.actual_area / scale for section in refined_sections],
        label="refined area",
    )
    ax.plot(
        [section.z_ref for section in refined_sections],
        [section.target_area / scale for section in refined_sections],
        label="target area",
    )
    ax.set_title("M3 Area Refinement")
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

    _, profiles = solve_principal_profiles(config)
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    for profile in profiles:
        ax.plot(
            [point.z for point in profile.points],
            [point.radius for point in profile.points],
            linewidth=2.0,
            label=f"{profile.axis} profile",
        )
    ax.set_title("Horizontal / Vertical Profiles")
    ax.set_xlabel("z (mm)")
    ax.set_ylabel("radius (mm)")
    ax.grid(True, linewidth=0.4, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_radial_profiles(config: Mapping[str, Any], surface: SurfaceResult, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curves = _representative_first_quadrant_curves(surface, count=9)
    transition_angle = _transition_center_angle_deg(surface)
    key_curves = {
        _nearest_curve(curves, 0.0).p_deg: "horizontal",
        _nearest_curve(curves, transition_angle).p_deg: "transition",
        _nearest_curve(curves, 90.0).p_deg: "vertical",
    }
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=140)
    for curve in curves:
        z_values = [
            curve.local_length * index / max(int(config["resolution"]["length_segments"]), 1)
            for index in range(int(config["resolution"]["length_segments"]) + 1)
        ]
        radii = [radial_curve_distance_at_z(config, surface.derived, curve, z) for z in z_values]
        key_label = key_curves.get(curve.p_deg)
        if key_label is not None:
            ax.plot(
                z_values,
                radii,
                color="black",
                linewidth=2.8,
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


def _representative_first_quadrant_curves(surface: SurfaceResult, count: int) -> List[RadialCurve]:
    first_quadrant = [curve for curve in surface.radial_curves if 0.0 <= curve.p_deg <= 90.0]
    if len(first_quadrant) <= count:
        return first_quadrant
    transition_angle = _transition_center_angle_deg(surface)
    selected = [
        _nearest_curve(first_quadrant, 0.0),
        _nearest_curve(first_quadrant, transition_angle),
        _nearest_curve(first_quadrant, 90.0),
    ]
    for index in range(count):
        target_index = round(index * (len(first_quadrant) - 1) / (count - 1))
        selected.append(first_quadrant[target_index])
    return sorted({curve.p_deg: curve for curve in selected}.values(), key=lambda curve: curve.p_deg)


def _transition_center_angle_deg(surface: SurfaceResult) -> float:
    return math.degrees(math.atan2(surface.derived.mouth_half_height, surface.derived.mouth_half_width))


def _nearest_curve(curves: Sequence[RadialCurve], p_deg: float) -> RadialCurve:
    return min(curves, key=lambda curve: abs(curve.p_deg - p_deg))


def _write_refinement_report(
    project_path: Path,
    result: RefinementResult,
    artifacts: Mapping[str, Path],
) -> None:
    initial_fit = result.initial.area_fit
    best_fit = result.best.surface.area_fit
    best_config = result.best.config
    tolerance = float(best_config["refinement"]["area_rms_log_tolerance"])
    smoothness = log_area_slope_change(result.best.surface.sections)
    smoothness_limit = float(best_config["refinement"]["max_log_area_slope_change"])
    s_quality = s_quality_metrics(best_config, result.best.surface)
    profile_smoothness = profile_smoothness_metrics(best_config)
    lines = [
        f"# HornCAD M3 Refinement Review: {project_path.stem}",
        "",
        "## Solver Model",
        "",
        "- Hard constraint: mouth boundary fit",
        "- Fixed authored value: K",
        "- Dependent solve: S(p), recomputed for every candidate",
        "- Candidate target: mean H/V circular OS-SE reference using that candidate's Q and N",
        "- Optimization objective: minimize RMS log area error over closed constant-z sections",
        "- Candidate variables: " + ", ".join(best_config["refinement"]["solve"]),
        "",
        "## Effective Search Space",
        "",
        f"- Mouth aspect delta: {result.search_space.aspect_delta:.6g}",
        f"- Coverage delta: {result.search_space.coverage_delta:.6g}",
        f"- Initial RMS log area error used for scaling: {result.search_space.initial_rms_log_area_error:.6g}",
        f"- Search difficulty: {result.search_space.difficulty:.6g}",
        f"- Morph rate range: {_format_range(result.search_space.effective_ranges['morph_rate'])}",
        f"- N range: {_format_range(result.search_space.effective_ranges['n'])}",
        f"- Q range: {_format_range(result.search_space.effective_ranges['q'])}",
        "",
        "## Best Candidate",
        "",
        f"- Stage: {result.best.stage}",
        f"- Valid under reject_if: {'yes' if result.best.is_valid else 'no'}",
        f"- Morph rate: {float(best_config['morph']['rate']):.6g}",
        f"- N: {float(best_config['osse']['n']):.6g}",
        f"- Q: {float(best_config['osse']['q']):.6g}",
        f"- S range: {_s_range(result.best.surface)}",
        f"- Shared section length: {result.best.surface.shared_section_length:.6g} mm",
        f"- Area RMS log tolerance: {tolerance:.6g}",
        f"- Area tolerance met: {'yes' if best_fit.rms_log_error <= tolerance else 'no'}",
        "",
        "## Area Fit",
        "",
        f"- Initial area fit score: {initial_fit.score:.6g}",
        f"- Refined area fit score: {best_fit.score:.6g}",
        f"- Initial RMS log area error: {initial_fit.rms_log_error:.6g}",
        f"- Refined RMS log area error: {best_fit.rms_log_error:.6g}",
        f"- Initial RMS area error: {initial_fit.rms_percent_error * 100.0:.6g}%",
        f"- Refined RMS area error: {best_fit.rms_percent_error * 100.0:.6g}%",
        f"- Refined max area error: {best_fit.max_abs_percent_error * 100.0:.6g}%",
        f"- Refined worst reference z: {best_fit.worst_z_ref:.6g} mm",
        "",
        "## Smoothness",
        "",
        f"- Max log-area slope change: {smoothness:.6g}",
        f"- Max log-area slope change limit: {smoothness_limit:.6g}",
        f"- Smoothness check: {'passed' if smoothness <= smoothness_limit else 'warning'}",
        f"- Smoothness objective weight: {float(best_config['refinement']['smoothness_weight']):.6g}",
        "",
        "## S Behavior",
        "",
        f"- S min: {s_quality.minimum:.6g}",
        f"- S max: {s_quality.maximum:.6g}",
        f"- S span: {s_quality.span:.6g}",
        f"- Expected S span: {s_quality.expected_span:.6g}",
        f"- Excess S span: {s_quality.excess_span:.6g}",
        f"- RMS S deviation: {s_quality.rms_deviation:.6g}",
        f"- Max adjacent S change over p: {s_quality.max_adjacent_delta:.6g}",
        f"- S span objective weight: {float(best_config['refinement']['s_span_weight']):.6g}",
        f"- S smoothness objective weight: {float(best_config['refinement']['s_smoothness_weight']):.6g}",
        "",
        "## Profile Smoothness",
        "",
        f"- Max H/V profile slope change: {profile_smoothness.max_slope_change:.6g}",
        f"- Max H/V profile slope change limit: {profile_smoothness.limit:.6g}",
        f"- Excess H/V profile slope change: {profile_smoothness.excess:.6g}",
        f"- Profile smoothness check: {'passed' if profile_smoothness.excess <= 0.0 else 'warning'}",
        f"- Profile smoothness objective weight: {float(best_config['refinement']['profile_smoothness_weight']):.6g}",
        "",
        "## Bound Notes",
        "",
    ]
    bound_notes = _bound_notes(best_config)
    if bound_notes:
        lines.extend(f"- {note}" for note in bound_notes)
    else:
        lines.append("- Best candidate did not land on a searched parameter bound.")
    lines.extend(
        [
            "",
            "## Search Summary",
            "",
            f"- Candidates evaluated: {result.candidates_evaluated}",
            f"- Candidates rejected by configured hard constraints: {result.candidates_rejected}",
        ]
    )
    lines.extend(f"- {summary}" for summary in result.stage_summaries)
    lines.extend(["", "## Warnings And Infeasible Conditions", ""])
    if result.best.surface.issues:
        for issue in result.best.surface.issues:
            lines.append(f"- `{issue.code}`: {issue.message}")
            lines.append(f"  Likely culprit: {issue.likely_culprit}")
    else:
        lines.append("- None")
    lines.extend(["", "## Generated Artifacts", ""])
    lines.extend(f"- `{name}`: `{path}`" for name, path in artifacts.items())
    lines.append("")
    artifacts["report"].write_text("\n".join(lines), encoding="utf-8")


def _s_range(surface: SurfaceResult) -> str:
    values = [curve.solved_s for curve in surface.radial_curves if math.isfinite(curve.solved_s)]
    if not values:
        return "none"
    return f"{min(values):.6g}..{max(values):.6g}"


def _format_range(values: tuple[float, float]) -> str:
    return f"{values[0]:.6g}..{values[1]:.6g}"


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
    coverage_h = float(config["profiles"]["horizontal"]["coverage"])
    coverage_v = float(config["profiles"]["vertical"]["coverage"])
    coverage_delta = abs(coverage_h - coverage_v) / max(coverage_h, coverage_v, 1e-9)
    lower_s, upper_s = [float(value) for value in config["osse"]["s_bounds"]]
    expected = min(upper_s - lower_s, 0.1 + 0.7 * aspect_delta + 0.5 * coverage_delta)
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


def _bound_notes(config: Mapping[str, Any]) -> List[str]:
    notes = []
    checks = [
        ("Morph rate", float(config["morph"]["rate"]), config["refinement"]["morph_rate_bounds"]),
        ("N", float(config["osse"]["n"]), config["refinement"]["n_bounds"]),
        ("Q", float(config["osse"]["q"]), config["refinement"]["q_bounds"]),
    ]
    for label, value, bounds in checks:
        lower, upper = float(bounds[0]), float(bounds[1])
        if math.isclose(value, lower, rel_tol=0.0, abs_tol=1e-9):
            notes.append(f"{label} landed on lower search bound {lower:.6g}.")
        elif math.isclose(value, upper, rel_tol=0.0, abs_tol=1e-9):
            notes.append(f"{label} landed on upper search bound {upper:.6g}.")
    return notes


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate HornCAD M3 area-refinement artifacts.")
    parser.add_argument("project", type=Path, help="Path to a HornCAD project YAML file.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated refinement artifacts. Defaults to refine_review/ beside the project file.",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = generate_refinement_review(args.project, args.output_dir)
    except (OSError, yaml.YAMLError, ConfigError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    for path in artifacts.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
