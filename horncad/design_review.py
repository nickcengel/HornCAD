"""Generate M1 design-review artifacts for a HornCAD project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence

_CACHE_DIR = Path(tempfile.gettempdir()) / "horncad-matplotlib"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml

from horncad.config import ConfigError, dump_config, load_project
from horncad.profile import (
    DerivedConfig,
    FeasibilityIssue,
    ProfileResult,
    feasibility_issues,
    solve_principal_profiles,
)


class DesignFeasibilityError(ValueError):
    """Raised when a validated project is geometrically infeasible."""

    def __init__(self, issues: Sequence[FeasibilityIssue]):
        self.issues = list(issues)
        super().__init__("\n".join(issue.message for issue in self.issues))


def generate_design_review(project_path: Path, output_dir: Path | None = None) -> Dict[str, Path]:
    project_path = Path(project_path)
    if output_dir is None:
        output_dir = project_path.parent / "design_review"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved = load_project(project_path)
    authored = _load_authored(project_path)
    derived, profiles = solve_principal_profiles(resolved)
    issues = collect_issues(resolved, derived, profiles)
    rejected = rejected_issues(resolved, issues)
    if rejected:
        raise DesignFeasibilityError(rejected)

    stem = project_path.stem

    artifacts = {
        "hv_profiles": output_dir / f"{stem}_hv_profiles.png",
        "report": output_dir / f"{stem}_report.md",
        "resolved": output_dir / f"{stem}_resolved.yaml",
    }

    _plot_combined(profiles, artifacts["hv_profiles"])
    artifacts["resolved"].write_text(dump_config(resolved), encoding="utf-8")
    _write_report(project_path, authored, resolved, derived, profiles, issues, artifacts)

    return artifacts


def collect_issues(
    config: Mapping[str, Any],
    derived: DerivedConfig,
    profiles: Sequence[ProfileResult],
) -> List[FeasibilityIssue]:
    issues = feasibility_issues(config, derived)
    for profile in profiles:
        issues.extend(profile.issues)
    return issues


def rejected_issues(config: Mapping[str, Any], issues: Sequence[FeasibilityIssue]) -> List[FeasibilityIssue]:
    reject_codes = set(config["validation"]["reject_if"])
    return [issue for issue in issues if issue.code in reject_codes]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate HornCAD design-review artifacts.")
    parser.add_argument("project", type=Path, help="Path to a HornCAD project YAML file.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated design-review artifacts. Defaults to design_review/ beside the project file.",
    )
    args = parser.parse_args(argv)

    try:
        artifacts = generate_design_review(args.project, args.output_dir)
    except (OSError, yaml.YAMLError, ConfigError, DesignFeasibilityError, ValueError) as exc:
        _print_error(exc)
        return 1

    for path in artifacts.values():
        print(path)
    return 0


def _load_authored(project_path: Path) -> Mapping[str, Any]:
    with project_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return loaded if isinstance(loaded, Mapping) else {}


def _plot_combined(profiles: Iterable[ProfileResult], path: Path) -> None:
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


def _write_report(
    project_path: Path,
    authored: Mapping[str, Any],
    resolved: Mapping[str, Any],
    derived: DerivedConfig,
    profiles: Sequence[ProfileResult],
    issues: Sequence[FeasibilityIssue],
    artifacts: Mapping[str, Path],
) -> None:
    lines: List[str] = [
        f"# HornCAD Design Review: {project_path.stem}",
        "",
        "## Project",
        "",
        f"- Source file: `{project_path}`",
        "- Validation: passed",
        "",
        "## Unit Conventions",
        "",
        f"- Length: `{resolved['units']['length']}`",
        f"- Angle: `{resolved['units']['angle']}`",
        "",
        "## Computed Values",
        "",
        f"- Conic exit radius: {derived.r_conic_exit:.6g} mm",
        f"- Mouth curvature radius: {_format_optional(derived.curvature_radius)}",
        "",
        "## Principal Profiles",
        "",
    ]

    for profile in profiles:
        lines.extend(
            [
                f"### {profile.axis.title()}",
                "",
                f"- Coverage: {profile.coverage_deg:.6g} deg",
                f"- K: {profile.k:.6g}",
                f"- Local length: {profile.local_length:.6g} mm",
                f"- OS-SE profile length: {profile.profile_length:.6g} mm",
                f"- Target boundary distance: {profile.target_boundary_distance:.6g} mm",
                f"- Solved S: {profile.solved_s:.9g}",
                f"- Final boundary distance: {profile.final_radius:.6g} mm",
                f"- Boundary fit error: {profile.boundary_fit_error:.9g} mm",
                "",
            ]
        )

    lines.extend(
        [
            "## Authored Parameters",
            "",
            "```yaml",
            yaml.safe_dump(dict(authored), sort_keys=False).rstrip(),
            "```",
            "",
            "## Resolved Parameters",
            "",
            "```yaml",
            dump_config(resolved).rstrip(),
            "```",
            "",
            "## Warnings And Infeasible Conditions",
            "",
        ]
    )

    if issues:
        for issue in issues:
            lines.extend(
                [
                    f"- `{issue.code}`: {issue.message}",
                    f"  Likely culprit: {issue.likely_culprit}",
                ]
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Generated Artifacts", ""])
    lines.extend(f"- `{name}`: `{path}`" for name, path in artifacts.items())
    lines.append("")

    artifacts["report"].write_text("\n".join(lines), encoding="utf-8")


def _format_optional(value: float | None) -> str:
    if value is None:
        return "`none`"
    return f"{value:.6g} mm"


def _print_error(exc: BaseException) -> None:
    if isinstance(exc, ConfigError):
        sys.stderr.write("Configuration validation failed:\n")
        for error in exc.errors:
            sys.stderr.write(f"  - {error}\n")
    elif isinstance(exc, DesignFeasibilityError):
        sys.stderr.write("Design feasibility check failed:\n")
        for issue in exc.issues:
            sys.stderr.write(f"  - [{issue.code}] {issue.message}\n")
            sys.stderr.write(f"    likely culprit: {issue.likely_culprit}\n")
    else:
        sys.stderr.write(f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
