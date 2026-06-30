from pathlib import Path

import yaml

from horncad.config import dump_config, load_project
from horncad.refine import (
    build_search_space,
    generate_refinement_review,
    log_area_slope_change,
    main,
    morph_timing_metrics,
    profile_smoothness_metrics,
    refine_project,
    roundover_target_rows,
    s_quality_metrics,
)
from horncad.surface import generate_inside_surface
from tests.helpers import small_project_config


PROJECT = Path(__file__).resolve().parents[1] / "examples/test_project/test_project.yaml"


def _small_project_config():
    return small_project_config()


def test_refine_project_searches_candidates_and_improves_area_fit():
    config = _small_project_config()

    result = refine_project(config)

    assert result.candidates_evaluated > 1
    assert result.best.surface.area_fit.rms_log_error <= result.initial.area_fit.rms_log_error
    assert log_area_slope_change(result.best.surface.sections) >= 0.0
    assert result.search_space.difficulty > 0.0
    assert result.search_space.effective_ranges["q"][0] >= config["profiles"]["q"]["bounds"][0]
    assert result.search_space.effective_ranges["q"][1] <= config["profiles"]["q"]["bounds"][1]
    assert s_quality_metrics(result.best.config, result.best.surface).max_adjacent_delta >= 0.0
    assert profile_smoothness_metrics(result.best.config).max_slope_change >= 0.0
    assert morph_timing_metrics(result.best.config).z50_fraction >= 0.0
    assert roundover_target_rows(result.best.config)[0].excess_miss_percent >= 0.0
    assert result.best.config["profiles"]["k"]["horizontal"]["seed"] == config["profiles"]["k"]["horizontal"]["seed"]
    assert result.best.config["profiles"]["k"]["vertical"]["seed"] == config["profiles"]["k"]["vertical"]["seed"]
    assert 0.25 <= result.best.config["morph"]["rate"]["seed"] <= 4.0
    assert 2.0 <= result.best.config["profiles"]["n"]["seed"] <= 10.0
    assert 0.99 <= result.best.config["profiles"]["q"]["seed"] <= 1.0


def test_generate_refinement_review_artifacts(tmp_path):
    project = tmp_path / "test_project.yaml"
    project.write_text(dump_config(_small_project_config()), encoding="utf-8")
    output_dir = tmp_path / "refine_review"

    artifacts = generate_refinement_review(project, output_dir)

    assert {key: path.name for key, path in artifacts.items()} == {
        "area_fit": "test_project_refined_area_fit.png",
        "hv_profiles": "test_project_refined_hv_profiles.png",
        "radial_profiles": "test_project_refined_radial_profiles.png",
        "radial_plan": "test_project_refined_radial_plan.png",
        "principal_views": "test_project_refined_principal_views.png",
        "report": "test_project_refinement_report.md",
        "resolved": "test_project_refined.yaml",
    }
    assert artifacts["area_fit"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["hv_profiles"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["radial_profiles"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["radial_plan"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["principal_views"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    report = artifacts["report"].read_text(encoding="utf-8")
    assert "Internal dependent solve: S(p), recomputed for every candidate" in report
    assert "Candidate target: polar-area-weighted circular OS-SE reference" in report
    assert "Max log-area slope change" in report
    assert "Effective Search Space" in report
    assert "Objective Breakdown" in report
    assert "K drift" in report
    assert "Profile z samples" in report
    assert "S Behavior" in report
    assert "Morph Timing" in report
    assert "z50" in report
    assert "Profile Smoothness" in report
    assert "Roundover Diagnostics" in report
    assert "Roundover contribution %" in report
    assert "Target %" in report
    assert "Roundover Length Guidance" in report
    assert "Required change in length.max mm" in report
    assert "Candidates evaluated" in report
    assert "Area tolerance met" in report
    refined = yaml.safe_load(artifacts["resolved"].read_text(encoding="utf-8"))
    assert refined["profiles"]["k"]["horizontal"]["seed"] == 1.0


def test_refinement_cli_default_output_is_project_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project = project_dir / "test_project.yaml"
    project.write_text(dump_config(_small_project_config()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(project)])

    assert exit_code == 0
    assert (project_dir / "refine_review/test_project_refinement_report.md").is_file()
    assert not (tmp_path / "refine_review/test_project_refinement_report.md").exists()


def test_build_search_space_scales_with_design_and_global_bounds():
    config = _small_project_config()
    initial = generate_inside_surface(config)

    search_space = build_search_space(config, initial)

    assert search_space.aspect_delta > 0.0
    assert search_space.coverage_delta > 0.0
    assert search_space.effective_ranges["morph_rate"][0] == config["morph"]["rate"]["bounds"][0]
    assert search_space.effective_ranges["morph_rate"][1] == config["morph"]["rate"]["bounds"][1]
    assert search_space.effective_ranges["q"] == tuple(config["profiles"]["q"]["bounds"])
