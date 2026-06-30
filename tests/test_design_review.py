import copy
from pathlib import Path

import pytest
import yaml

from horncad.design_review import DesignFeasibilityError, generate_design_review, main
from horncad.config import load_project
from horncad.profile import derive_config, feasibility_issues, solve_principal_profiles
from tests.helpers import (
    CONIC_EXTENSION_LENGTH,
    LENGTH_MAX,
    MOUTH_SAG,
    THROAT_DIAMETER,
    sample_project_config,
)


PROJECT = Path(__file__).resolve().parents[1] / "examples/test_project/test_project.yaml"


def test_principal_profile_solver_fits_fixture_boundaries():
    config = sample_project_config()

    derived, profiles = solve_principal_profiles(config)

    assert derived.r0 == THROAT_DIAMETER / 2.0
    assert len(profiles) == 2
    assert profiles[0].axis == "horizontal"
    assert profiles[1].axis == "vertical"
    assert profiles[0].profile_length == LENGTH_MAX - MOUTH_SAG - CONIC_EXTENSION_LENGTH
    assert profiles[1].profile_length == LENGTH_MAX - CONIC_EXTENSION_LENGTH
    lower_s, upper_s = config["refinement"]["s_bounds"]
    assert lower_s <= profiles[0].solved_s <= upper_s
    assert lower_s <= profiles[1].solved_s <= upper_s
    assert abs(profiles[0].boundary_fit_error) < 1e-6
    assert abs(profiles[1].boundary_fit_error) < 1e-6


def test_principal_profile_sampling_is_adaptive():
    config = sample_project_config()

    _, profiles = solve_principal_profiles(config)

    for profile in profiles:
        osse_points = [point for point in profile.points if point.segment == "osse"]
        intervals = [
            osse_points[index + 1].z - osse_points[index].z
            for index in range(len(osse_points) - 1)
        ]
        assert min(intervals) < max(intervals)


def test_generate_design_review_artifacts(tmp_path):
    output_dir = tmp_path / "design_review"

    artifacts = generate_design_review(PROJECT, output_dir)

    expected_names = {
        "hv_profiles": "test_project_hv_profiles.png",
        "report": "test_project_report.md",
        "resolved": "test_project_resolved.yaml",
    }
    assert {key: path.name for key, path in artifacts.items()} == expected_names

    assert artifacts["hv_profiles"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not (output_dir / "test_project_h_profile.png").exists()
    assert not (output_dir / "test_project_v_profile.png").exists()
    assert not (output_dir / "test_project_profile_data.csv").exists()

    report = artifacts["report"].read_text(encoding="utf-8")
    assert "Computed Values" in report
    assert "Conic extension length" not in report.split("## Principal Profiles", 1)[0]
    assert "half angle" not in report.split("## Principal Profiles", 1)[0]
    assert "Mouth half width" not in report.split("## Principal Profiles", 1)[0]
    assert "Solved S" in report
    assert "Boundary fit error" in report
    assert "Validation: passed" in report
    assert "test_project_hv_profiles.png" in report

    resolved = artifacts["resolved"].read_text(encoding="utf-8")
    assert "design_review:" in resolved
    assert "cad:" in resolved


def test_generate_design_review_rejects_solved_s_outside_bounds(tmp_path):
    config = sample_project_config()
    config["mouth"]["width"] = 1600.0
    project = tmp_path / "too_wide.yaml"
    project.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(DesignFeasibilityError) as exc_info:
        generate_design_review(project, tmp_path / "design_review")

    assert exc_info.value.issues[0].code == "solved_s_outside_bounds"
    assert "target boundary distance" in exc_info.value.issues[0].likely_culprit


def test_cli_reports_likely_culprit_for_infeasible_design(tmp_path, capsys):
    config = sample_project_config()
    config["mouth"]["width"] = 1600.0
    project = tmp_path / "too_wide.yaml"
    project.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    exit_code = main([str(project), "--output-dir", str(tmp_path / "design_review")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Design feasibility check failed" in captured.err
    assert "[solved_s_outside_bounds]" in captured.err
    assert "likely culprit:" in captured.err


def test_curvature_radius_too_small_is_structured_issue():
    config = sample_project_config()
    config = copy.deepcopy(config)
    config["mouth"]["curvature"] = {"type": "cylinder", "sag": None, "radius": 100.0}

    derived = derive_config(config)
    issues = feasibility_issues(config, derived)

    assert issues[0].code == "mouth_curvature_radius_too_small"
    assert "Increase mouth.curvature.radius" in issues[0].likely_culprit


def test_design_review_cli_generates_default_artifacts(tmp_path, monkeypatch, capsys):
    project = tmp_path / "test_project.yaml"
    project.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(project)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "design_review/test_project_report.md" in captured.out
    assert (tmp_path / "design_review/test_project_report.md").is_file()


def test_design_review_cli_default_output_is_project_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project = project_dir / "test_project.yaml"
    project.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(project)])

    assert exit_code == 0
    assert (project_dir / "design_review/test_project_report.md").is_file()
    assert not (tmp_path / "design_review/test_project_report.md").exists()
