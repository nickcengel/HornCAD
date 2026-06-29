import math
from pathlib import Path

from horncad.config import load_project
from horncad.profile import derive_config
from horncad.surface import (
    generate_inside_surface,
    generate_surface_review,
    main,
    mouth_area,
    plotted_target_area_normalizer,
    rounded_rectangle_area,
    rounded_rectangle_boundary_distance,
    superellipse_boundary_distance,
)


PROJECT = Path(__file__).resolve().parents[1] / "examples/test_project/test_project.yaml"


def test_generate_inside_surface_has_radial_curves_sections_and_area_fit():
    config = load_project(PROJECT)

    result = generate_inside_surface(config)

    assert len(result.radial_curves) == config["resolution"]["angular_segments"]
    assert len(result.sections) == config["resolution"]["length_segments"] + 1
    assert result.shared_section_length == 120.0
    assert result.sections[-1].z_ref == 120.0
    assert abs(result.radial_curves[0].boundary_x - 190.0) < 1e-6
    assert abs(result.radial_curves[24].boundary_y - 117.5) < 1e-6
    assert 0.0 < result.area_fit.score <= 1.0
    assert result.area_fit.rms_percent_error >= 0.0
    assert result.area_fit.max_abs_percent_error >= result.area_fit.rms_percent_error
    assert result.issues == []


def test_plotted_target_area_normalizer_uses_final_plotted_target():
    config = load_project(PROJECT)
    result = generate_inside_surface(config)

    assert plotted_target_area_normalizer(result.sections) == result.sections[-1].target_area


def test_exact_rectangle_boundary_has_flat_sides():
    config = load_project(PROJECT)
    config["mouth"]["shape"] = {"type": "rectangle", "shape_power": 6.0, "corner_radius": None}
    derived = derive_config(config)

    for degrees in (0.0, 15.0):
        distance = superellipse_boundary_distance(config, derived, math.radians(degrees))
        x = distance * math.cos(math.radians(degrees))
        assert abs(x - 190.0) < 1e-6


def test_exact_rounded_rectangle_boundary_and_area():
    assert rounded_rectangle_area(380.0, 235.0, 20.0) == 380.0 * 235.0 - (4.0 - math.pi) * 400.0

    config = load_project(PROJECT)
    config["mouth"]["shape"] = {"type": "rounded_rectangle", "shape_power": 6.0, "corner_radius": 20.0}
    derived = derive_config(config)

    assert mouth_area(config, derived) == rounded_rectangle_area(380.0, 235.0, 20.0)
    assert abs(rounded_rectangle_boundary_distance(190.0, 117.5, 20.0, 0.0) - 190.0) < 1e-6
    assert rounded_rectangle_boundary_distance(190.0, 117.5, 20.0, math.radians(30.0)) < (
        190.0 / math.cos(math.radians(30.0))
    )


def test_generate_surface_review_artifacts(tmp_path):
    output_dir = tmp_path / "surface_review"

    artifacts = generate_surface_review(PROJECT, output_dir)

    assert {key: path.name for key, path in artifacts.items()} == {
        "area_fit": "test_project_area_fit.png",
        "report": "test_project_surface_report.md",
        "resolved": "test_project_resolved.yaml",
    }
    assert artifacts["area_fit"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    report = artifacts["report"].read_text(encoding="utf-8")
    assert "Area fit score" in report
    assert "mean H/V circular OS-SE reference" in report
    assert "closed constant-z sections" in report
    assert "Shared section length: 120" in report
    assert "Output scope: full" in report
    assert "Radial curves: 96" in report
    assert "Section samples: 101" in report


def test_surface_review_cli_default_output_is_project_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "nested"
    project_dir.mkdir()
    project = project_dir / "test_project.yaml"
    project.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main([str(project)])

    assert exit_code == 0
    assert (project_dir / "surface_review/test_project_surface_report.md").is_file()
    assert not (tmp_path / "surface_review/test_project_surface_report.md").exists()
