import copy
from pathlib import Path

import pytest

from horncad.config import ConfigError, load_project, main, resolve_config, validate_config


PROJECT = Path("examples/test_project/test_project.yaml")


def test_test_project_loads_and_defaults_conic_exit_angle():
    resolved = load_project(PROJECT)

    assert resolved["throat"]["diameter"] == 25.4
    assert resolved["throat"]["conic_extension"]["exit_angle"] == 14.0
    assert resolved["outputs"]["design_review"]["report"] is True
    assert resolved["outputs"]["scope"] == "full"
    assert resolved["osse"]["q"] == 0.995
    assert resolved["refinement"]["solve"] == ["morph_rate", "n", "q"]
    assert resolved["refinement"]["morph_rate_bounds"] == [0.25, 8.0]
    assert resolved["refinement"]["smoothness_weight"] == 2.0
    assert resolved["refinement"]["s_span_weight"] == 0.2
    assert resolved["refinement"]["s_smoothness_weight"] == 0.2
    assert resolved["refinement"]["max_profile_slope_change"] == 2.0
    assert resolved["refinement"]["profile_smoothness_weight"] == 0.5
    assert "design_review" in resolved["outputs"]
    assert "cad" in resolved["outputs"]


def test_resolve_config_does_not_mutate_authored_mapping():
    authored = {
        "throat": {"diameter": 25.4, "angle": 10.0},
        "mouth": {
            "width": 380.0,
            "height": 235.0,
            "shape": {"type": "ellipse"},
            "curvature": {"type": "flat"},
        },
        "length": {"max": 150.0},
        "profiles": {
            "horizontal": {"coverage": 50.0, "k": 1.0},
            "vertical": {"coverage": 31.0, "k": 1.0},
        },
    }
    original = copy.deepcopy(authored)

    resolved = resolve_config(authored)

    assert authored == original
    assert resolved["throat"]["conic_extension"]["length"] == 0.0
    assert resolved["throat"]["conic_extension"]["exit_angle"] == 10.0


def test_resolve_config_derives_missing_mouth_height_from_width():
    authored = load_project(PROJECT)
    authored["mouth"]["height"] = None

    resolved = resolve_config(authored)

    assert resolved["mouth"]["width"] == 380.0
    assert resolved["mouth"]["height"] is not None
    assert resolved["mouth"]["height"] > 0.0
    validate_config(resolved)


def test_resolve_config_derives_missing_mouth_width_from_height():
    authored = load_project(PROJECT)
    authored["mouth"]["width"] = None

    resolved = resolve_config(authored)

    assert resolved["mouth"]["height"] == 235.0
    assert resolved["mouth"]["width"] is not None
    assert resolved["mouth"]["width"] > 0.0
    validate_config(resolved)


def test_missing_mouth_dimension_rejects_unsupported_sphere_case():
    resolved = load_project(PROJECT)
    resolved["mouth"]["width"] = None
    resolved["mouth"]["curvature"] = {"type": "sphere", "sag": 30.0, "radius": None}

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolve_config(resolved))

    assert (
        "mouth.width could not be derived from the specified principal dimension and H/V profile settings"
        in exc_info.value.errors
    )


def test_invalid_values_produce_clear_errors():
    resolved = load_project(PROJECT)
    resolved["profiles"]["horizontal"]["k"] = 11.0
    resolved["osse"]["q"] = 0.5

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "profiles.horizontal.k must be at most 10" in exc_info.value.errors
    assert "osse.q must be at least 0.99" in exc_info.value.errors


def test_invalid_output_scope_produces_clear_error():
    resolved = load_project(PROJECT)
    resolved["outputs"]["scope"] = "eighth"

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "outputs.scope must be one of ['full', 'half', 'quarter']" in exc_info.value.errors


def test_invalid_refinement_values_produce_clear_errors():
    resolved = load_project(PROJECT)
    resolved["refinement"]["solve"] = ["morph_rate", "k"]
    resolved["refinement"]["morph_rate_bounds"] = [0.0, 9.0]

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "refinement.solve entries must be one of ['morph_rate', 'n', 'q']" in exc_info.value.errors
    assert "refinement.morph_rate_bounds must be greater than 0" in exc_info.value.errors
    assert "refinement.morph_rate_bounds must be at most 8" in exc_info.value.errors


def test_cylinder_curvature_requires_exactly_one_sag_or_radius():
    resolved = load_project(PROJECT)
    resolved["mouth"]["curvature"]["sag"] = 30.0
    resolved["mouth"]["curvature"]["radius"] = 500.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.curvature must specify exactly one of sag or radius for cylinder/sphere" in exc_info.value.errors


def test_corner_radius_must_fit_inside_rectangle():
    resolved = load_project(PROJECT)
    resolved["mouth"]["shape"]["corner_radius"] = 200.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.shape.corner_radius must be at most 117.5" in exc_info.value.errors


def test_ellipse_rejects_corner_radius():
    resolved = load_project(PROJECT)
    resolved["mouth"]["shape"] = {"type": "ellipse", "shape_power": 2.0, "corner_radius": 10.0}

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.shape.corner_radius must be null when mouth.shape.type is ellipse" in exc_info.value.errors


def test_cli_writes_resolved_config_to_stdout(capsys):
    exit_code = main([str(PROJECT)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units:" in captured.out
    assert "design_review:" in captured.out
    assert captured.err == ""
