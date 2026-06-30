import math
from pathlib import Path

from horncad.config import load_project
from horncad.profile import derive_config
from horncad.surface import (
    corner_anchor_angles,
    generate_inside_surface,
    generate_surface_review,
    main,
    mouth_area,
    equivalent_round_reference_values,
    plotted_target_area_normalizer,
    rounded_rectangle_area,
    rounded_rectangle_boundary_distance,
    radial_sample_angles,
    snap_cardinal_angles,
    superellipse_boundary_distance,
)
from tests.helpers import (
    ANGULAR_SEGMENTS,
    LENGTH_MAX,
    MOUTH_HEIGHT,
    MOUTH_SAG,
    MOUTH_WIDTH,
    sample_project_config,
)


PROJECT = Path(__file__).resolve().parents[1] / "examples/test_project/test_project.yaml"


def test_generate_inside_surface_has_radial_curves_sections_and_area_fit():
    config = sample_project_config()

    result = generate_inside_surface(config)

    assert len(result.radial_curves) == config["resolution"]["angular_segments"]
    assert len(result.sections) == config["resolution"]["length_segments"] + 1
    expected_shared_length = LENGTH_MAX - MOUTH_SAG
    assert result.shared_section_length == expected_shared_length
    assert result.sections[-1].z_ref == expected_shared_length
    assert abs(result.radial_curves[0].boundary_x - MOUTH_WIDTH / 2.0) < 1e-6
    assert abs(result.radial_curves[ANGULAR_SEGMENTS // 4].boundary_y - MOUTH_HEIGHT / 2.0) < 1e-6
    assert 0.0 < result.area_fit.score <= 1.0
    assert result.area_fit.rms_percent_error >= 0.0
    assert result.area_fit.max_abs_percent_error >= result.area_fit.rms_percent_error
    assert result.issues == []


def test_section_sampling_is_adaptive_along_z():
    config = sample_project_config()
    result = generate_inside_surface(config)

    intervals = [
        result.sections[index + 1].z_ref - result.sections[index].z_ref
        for index in range(len(result.sections) - 1)
    ]
    assert min(intervals) < max(intervals)


def test_radial_curve_sampling_is_adaptive_around_p():
    config = sample_project_config()
    result = generate_inside_surface(config)

    angles = [math.radians(curve.p_deg) for curve in result.radial_curves]
    intervals = [
        (angles[(index + 1) % len(angles)] - angles[index]) % (2.0 * math.pi)
        for index in range(len(angles))
    ]
    assert min(intervals) < max(intervals)


def test_radial_curve_sampling_includes_exact_horizontal_and_vertical_axes():
    config = sample_project_config()
    derived = derive_config(config)

    angles = radial_sample_angles(config, derived)

    assert 0.0 in angles
    assert math.pi / 2.0 in angles
    assert math.pi in angles
    assert 3.0 * math.pi / 2.0 in angles
    assert snap_cardinal_angles([math.pi / 2.0 + 1e-12]) == [math.pi / 2.0]


def test_rounded_rectangle_sampling_includes_corner_anchor_profiles():
    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rectangle", "shape_power": 6.0, "corner_radius": 4.0}
    derived = derive_config(config)

    anchors = corner_anchor_angles(config, derived)
    angles = radial_sample_angles(config, derived)

    assert len(anchors) == 5
    assert len(angles) == config["resolution"]["angular_segments"]
    assert all(any(abs(angle - anchor) < 1e-12 for angle in angles) for anchor in anchors)
    assert anchors == sorted(anchors)


def test_plotted_target_area_normalizer_uses_final_plotted_target():
    config = sample_project_config()
    result = generate_inside_surface(config)

    assert plotted_target_area_normalizer(result.sections) == result.sections[-1].target_area


def test_equivalent_round_reference_uses_polar_area_weighting():
    config = sample_project_config()
    derived = derive_config(config)

    reference = equivalent_round_reference_values(config, derived)

    simple_mean = (
        config["profiles"]["coverage"]["horizontal"]
        + config["profiles"]["coverage"]["vertical"]
    ) / 2.0
    assert reference.coverage_deg > simple_mean
    assert reference.coverage_deg < config["profiles"]["coverage"]["horizontal"]


def test_exact_rectangle_boundary_has_flat_sides():
    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rectangle", "shape_power": 6.0, "corner_radius": None}
    derived = derive_config(config)

    for degrees in (0.0, 15.0):
        distance = superellipse_boundary_distance(config, derived, math.radians(degrees))
        x = distance * math.cos(math.radians(degrees))
        assert abs(x - MOUTH_WIDTH / 2.0) < 1e-6


def test_exact_rounded_rectangle_boundary_and_area():
    corner_radius = 20.0
    assert rounded_rectangle_area(MOUTH_WIDTH, MOUTH_HEIGHT, corner_radius) == (
        MOUTH_WIDTH * MOUTH_HEIGHT - (4.0 - math.pi) * corner_radius**2
    )

    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rounded_rectangle", "shape_power": 6.0, "corner_radius": corner_radius}
    derived = derive_config(config)

    half_width = MOUTH_WIDTH / 2.0
    half_height = MOUTH_HEIGHT / 2.0
    assert mouth_area(config, derived) == rounded_rectangle_area(MOUTH_WIDTH, MOUTH_HEIGHT, corner_radius)
    assert abs(rounded_rectangle_boundary_distance(half_width, half_height, corner_radius, 0.0) - half_width) < 1e-6
    assert rounded_rectangle_boundary_distance(half_width, half_height, corner_radius, math.radians(30.0)) < (
        half_width / math.cos(math.radians(30.0))
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
    assert "polar-area-weighted circular OS-SE reference" in report
    assert "closed constant-z sections" in report
    assert "Shared section length:" in report
    assert "Output scope: full" in report
    assert "Radial curves:" in report
    assert "Section samples:" in report


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
