from pathlib import Path

from horncad.config import dump_config, load_project
from horncad.refine import (
    _searchable_variables,
    _values_for,
    build_search_space,
    generate_output,
    area_zone_metrics,
    log_area_slope_change,
    main,
    morph_rate_drift_metric,
    morph_timing_metrics,
    profile_smoothness_metrics,
    radial_basis_deviation_metrics,
    objective_terms,
    refine_project,
    roundover_target_rows,
    s_quality_metrics,
)
from horncad.surface import generate_inside_surface
from tests.helpers import small_project_config


PROJECT = Path(__file__).resolve().parents[1] / "examples/rectangular_project/rectangular_project.yaml"


def _small_project_config():
    return small_project_config()


def test_refine_project_searches_candidates_and_keeps_valid_geometry():
    config = _small_project_config()

    result = refine_project(config)

    assert result.candidates_evaluated > 1
    assert result.best.is_valid
    assert result.best.surface.area_fit.rms_log_error >= 0.0
    assert log_area_slope_change(result.best.surface.sections) >= 0.0
    assert result.search_space.difficulty > 0.0
    assert "q" not in result.search_space.effective_ranges
    assert result.search_space.effective_ranges["n_horizontal"] == tuple(config["profiles"]["n"]["horizontal"]["bounds"])
    assert result.search_space.effective_ranges["n_vertical"] == tuple(config["profiles"]["n"]["vertical"]["bounds"])
    assert result.search_space.effective_ranges["mouth_sag"] == (
        config["mouth"]["curvature"]["sag"],
        config["mouth"]["curvature"]["sag"],
    )
    assert s_quality_metrics(result.best.config, result.best.surface).max_adjacent_delta >= 0.0
    assert profile_smoothness_metrics(result.best.config).max_slope_change >= 0.0
    assert radial_basis_deviation_metrics(result.best.config, result.best.surface).rms_radius_deviation >= 0.0
    assert morph_timing_metrics(result.best.config, result.best.surface).z50_fraction >= 0.0
    assert roundover_target_rows(result.best.config)[0].excess_miss_percent >= 0.0
    assert result.best.config["profiles"]["k"]["horizontal"]["seed"] == config["profiles"]["k"]["horizontal"]["seed"]
    assert result.best.config["profiles"]["k"]["vertical"]["seed"] == config["profiles"]["k"]["vertical"]["seed"]
    assert 0.25 <= result.best.config["morph"]["rate"]["seed"] <= 4.0
    assert 2.0 <= result.best.config["profiles"]["n"]["horizontal"]["seed"] <= 100.0
    assert 2.0 <= result.best.config["profiles"]["n"]["vertical"]["seed"] <= 100.0


def test_generate_output_artifacts(tmp_path):
    project = tmp_path / "test_project.yaml"
    config = _small_project_config()
    config["outputs"]["cad"]["formats"]["3d"]["stl"] = True
    project.write_text(dump_config(config), encoding="utf-8")
    output_dir = tmp_path / "output"

    artifacts = generate_output(project, output_dir)

    assert {key: path.name for key, path in artifacts.items()} == {
        "area_fit": "test_project_area_fit.png",
        "hv_profiles": "test_project_hv_profiles.png",
        "inside_surface": "test_project_inside_surface.stl",
        "radial_plan": "test_project_radial_plan.png",
        "radial_profiles": "test_project_radial_profiles.png",
        "report": "test_project_report.md",
    }
    assert artifacts["area_fit"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["hv_profiles"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["radial_profiles"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["radial_plan"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert artifacts["inside_surface"].read_text(encoding="ascii").startswith("solid test_project_inside_surface\n")
    report = artifacts["report"].read_text(encoding="utf-8")
    assert "# HornCAD Output" in report
    assert "Surface mode: slice" in report
    assert "Output surface: H/V basis profiles lofted through superellipse slices" in report
    assert "Internal dependent solve: S(p), solved from authored profile values" in report
    assert "Fixed Q: 0.995" in report
    assert "Area reference: polar-area-weighted circular OS-SE reference" in report
    assert "Max log-area slope change" in report
    assert "Effective Search Space" not in report
    assert "Objective Breakdown" not in report
    assert "weighted area rms log" not in report
    assert "Weighted RMS log area error" in report
    assert "Throat third RMS log area error" in report
    assert "Profile z samples" in report
    assert "Radial Diagnostic S Behavior" in report
    assert "H/V S range" in report
    assert "Radial Basis Coherence" in report
    assert "radial basis deviation" in report
    assert "RMS exit slope deviation" in report
    assert "Morph Timing" in report
    assert "z50" in report
    assert "Profile Smoothness" in report
    assert "Roundover Diagnostics" in report
    assert "Roundover contribution %" in report
    assert "Target %" in report
    assert "Roundover Length Guidance" in report
    assert "Required change in length.max mm" in report
    assert "Designs evaluated" not in report
    assert "Area tolerance met" in report
    assert "Inside surface shape power" in report
    assert "Bounds are ignored in slice mode" in report
    assert "principal_views" not in artifacts
    assert "resolved" not in artifacts


def test_generate_output_profile_mode_uses_search_path(tmp_path):
    project = tmp_path / "test_project.yaml"
    config = _small_project_config()
    config["surface"]["mode"] = "profile"
    config["outputs"]["cad"]["formats"]["3d"]["stl"] = True
    project.write_text(dump_config(config), encoding="utf-8")

    artifacts = generate_output(project, tmp_path / "output", workers=1)

    report = artifacts["report"].read_text(encoding="utf-8")
    assert "Surface mode: profile" in report
    assert "Output surface: radial profile family generated by candidate search" in report
    assert "Effective Search Space" in report
    assert "Objective Breakdown" in report
    assert "Designs evaluated" in report


def test_generate_output_slice_mode_keeps_non_governing_radial_issues_as_warnings(tmp_path):
    project = tmp_path / "test_project.yaml"
    config = _small_project_config()
    config["profiles"]["k"]["horizontal"]["seed"] = 4.0
    config["profiles"]["k"]["horizontal"]["bounds"] = [1.0, 4.0]
    config["profiles"]["n"]["horizontal"]["seed"] = 60.0
    config["outputs"]["cad"]["formats"]["3d"]["stl"] = True
    project.write_text(dump_config(config), encoding="utf-8")

    artifacts = generate_output(project, tmp_path / "output")

    report = artifacts["report"].read_text(encoding="utf-8")
    assert "Surface mode: slice" in report
    assert "Warnings And Infeasible Conditions" in report


def test_output_cli_default_output_is_project_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project = project_dir / "test_project.yaml"
    project.write_text(dump_config(_small_project_config()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(project)])

    assert exit_code == 0
    assert (project_dir / "output/test_project_report.md").is_file()
    assert not (tmp_path / "output/test_project_report.md").exists()


def test_build_search_space_scales_with_design_and_global_bounds():
    config = _small_project_config()
    initial = generate_inside_surface(config)

    search_space = build_search_space(config, initial)

    assert search_space.aspect_delta > 0.0
    assert search_space.coverage_delta > 0.0
    assert search_space.effective_ranges["morph_rate"][0] == config["morph"]["rate"]["bounds"][0]
    assert search_space.effective_ranges["morph_rate"][1] == config["morph"]["rate"]["bounds"][1]
    assert "q" not in search_space.effective_ranges
    assert search_space.effective_ranges["n_horizontal"] == tuple(config["profiles"]["n"]["horizontal"]["bounds"])
    assert search_space.effective_ranges["n_vertical"] == tuple(config["profiles"]["n"]["vertical"]["bounds"])


def test_n_search_uses_wide_log_grid():
    config = _small_project_config()
    initial = generate_inside_surface(config)
    search_space = build_search_space(config, initial)

    values = _values_for(config, "n_horizontal", ["n_horizontal"], search_space)

    assert values[0] == 2.0
    assert values[-1] == 100.0
    assert any(value > 20.0 for value in values)
    assert len(values) <= 6


def test_variable_grids_are_capped_at_six_values():
    config = _small_project_config()
    initial = generate_inside_surface(config)
    search_space = build_search_space(config, initial)

    for name in ("morph_rate", "n_horizontal", "n_vertical", "k_horizontal", "k_vertical"):
        assert len(_values_for(config, name, [name], search_space)) <= 6


def test_morph_rate_drift_penalizes_only_above_seed():
    config = _small_project_config()
    same = _small_project_config()
    lower = _small_project_config()
    lower["morph"]["rate"]["seed"] = 1.0
    higher = _small_project_config()
    higher["morph"]["rate"]["seed"] = 4.0

    assert morph_rate_drift_metric(config, same) == 0.0
    assert morph_rate_drift_metric(config, lower) == 0.0
    assert morph_rate_drift_metric(config, higher) > 0.0


def test_area_terms_are_report_only_not_objective_terms():
    config = _small_project_config()
    surface = generate_inside_surface(config)
    baseline = area_zone_metrics(surface.sections).weighted_rms_log_error
    terms = objective_terms(
        config,
        surface,
        config,
        baseline - 0.01,
    )

    assert "weighted area rms log" not in {term.name for term in terms}
    assert "area regression" not in {term.name for term in terms}
    assert "area smoothness" not in {term.name for term in terms}
    assert "radial basis deviation" in {term.name for term in terms}
    assert "radial exit slope deviation" in {term.name for term in terms}


def test_area_zone_metrics_weight_throat_more_than_mouth():
    config = _small_project_config()
    surface = generate_inside_surface(config)

    metrics = area_zone_metrics(surface.sections)

    assert metrics.weighted_rms_log_error >= 0.0
    assert metrics.throat_rms_log_error >= 0.0
    assert metrics.middle_rms_log_error >= 0.0
    assert metrics.mouth_rms_log_error >= 0.0


def test_sag_search_is_enabled_only_by_sag_bounds():
    config = _small_project_config()

    assert "mouth_sag" not in _searchable_variables(config)

    config["mouth"]["curvature"]["sag_bounds"] = [10.0, 40.0]
    initial = generate_inside_surface(config)
    search_space = build_search_space(config, initial)

    assert "mouth_sag" in _searchable_variables(config)
    assert search_space.effective_ranges["mouth_sag"] == (10.0, 40.0)
    assert len(_values_for(config, "mouth_sag", ["mouth_sag"], search_space)) <= 6
