import copy
from pathlib import Path

import pytest

from horncad.config import ConfigError, load_project, main, profile_roundover_target_percent, resolve_config, validate_config
from tests.helpers import (
    HORIZONTAL_COVERAGE,
    LENGTH_MAX,
    MOUTH_HEIGHT,
    MOUTH_SAG,
    MOUTH_WIDTH,
    THROAT_ANGLE,
    THROAT_DIAMETER,
    VERTICAL_COVERAGE,
    sample_project_config,
)


PROJECT = Path("examples/rectangular_project/rectangular_project.yaml")


def test_test_project_loads_and_defaults_conic_exit_angle():
    resolved = load_project(PROJECT)

    assert resolved["outputs"]["scope"] == "full"
    assert resolved["surface"]["mode"] == "slice"
    assert "coverage" in resolved["profiles"]
    assert "roundover" in resolved["profiles"]
    assert "cad" in resolved["outputs"]
    assert resolved["outputs"]["cad"]["formats"]["3d"]["stl"] is False


def test_resolve_config_does_not_mutate_authored_mapping():
    authored = {
        "throat": {"diameter": THROAT_DIAMETER, "angle": THROAT_ANGLE},
        "mouth": {
            "width": MOUTH_WIDTH,
            "height": MOUTH_HEIGHT,
            "shape": {"type": "ellipse"},
            "curvature": {"type": "flat"},
        },
        "length": {"max": LENGTH_MAX},
        "profiles": {
            "coverage": {"horizontal": HORIZONTAL_COVERAGE, "vertical": VERTICAL_COVERAGE},
        },
    }
    original = copy.deepcopy(authored)

    resolved = resolve_config(authored)

    assert authored == original
    assert resolved["throat"]["conic_extension"]["length"] == 0.0
    assert resolved["throat"]["conic_extension"]["exit_angle"] == THROAT_ANGLE
    assert resolved["profiles"]["roundover"] == {}
    assert profile_roundover_target_percent(resolved, "horizontal") is None


def test_resolve_config_derives_missing_mouth_height_from_width():
    authored = sample_project_config()
    authored["mouth"]["height"] = None

    resolved = resolve_config(authored)

    assert resolved["mouth"]["width"] == MOUTH_WIDTH
    assert resolved["mouth"]["height"] is not None
    assert resolved["mouth"]["height"] > 0.0
    validate_config(resolved)


def test_resolve_config_derives_missing_mouth_width_from_height():
    authored = sample_project_config()
    authored["mouth"]["width"] = None

    resolved = resolve_config(authored)

    assert resolved["mouth"]["height"] == MOUTH_HEIGHT
    assert resolved["mouth"]["width"] is not None
    assert resolved["mouth"]["width"] > 0.0
    validate_config(resolved)


def test_missing_mouth_dimension_rejects_unsupported_sphere_case():
    resolved = sample_project_config()
    resolved["mouth"]["width"] = None
    resolved["mouth"]["curvature"] = {"type": "sphere", "sag": MOUTH_SAG, "radius": None}

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolve_config(resolved))

    assert (
        "mouth.width could not be derived from the specified principal dimension and H/V profile settings"
        in exc_info.value.errors
    )


def test_invalid_values_produce_clear_errors():
    resolved = sample_project_config()
    resolved["profiles"]["k"]["horizontal"]["seed"] = 11.0
    resolved["profiles"]["n"]["horizontal"]["seed"] = 101.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "profiles.k.horizontal.seed must be at most 10" in exc_info.value.errors
    assert "profiles.n.horizontal.seed must be at most 100" in exc_info.value.errors


def test_invalid_output_scope_produces_clear_error():
    resolved = sample_project_config()
    resolved["outputs"]["scope"] = "eighth"

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "outputs.scope must be one of ['full', 'half', 'quarter']" in exc_info.value.errors


def test_invalid_surface_mode_produces_clear_error():
    resolved = sample_project_config()
    resolved["surface"]["mode"] = "hybrid"

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "surface.mode must be one of ['profile', 'slice']" in exc_info.value.errors


def test_invalid_refinement_values_produce_clear_errors():
    resolved = sample_project_config()
    resolved["morph"]["rate"]["bounds"] = [0.0, 9.0]
    resolved["profiles"]["n"]["horizontal"]["seed"] = 101.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "morph.rate.bounds must be greater than 0" in exc_info.value.errors
    assert "morph.rate.bounds must be at most 4" in exc_info.value.errors
    assert "profiles.n.horizontal.seed must be at most 100" in exc_info.value.errors


def test_legacy_shared_n_normalizes_to_axis_specs():
    authored = sample_project_config()
    authored["profiles"]["n"] = {"seed": 7.0, "bounds": [2.0, 100.0]}

    resolved = resolve_config(authored)

    assert resolved["profiles"]["n"]["horizontal"] == {"seed": 7.0, "bounds": [2.0, 100.0]}
    assert resolved["profiles"]["n"]["vertical"] == {"seed": 7.0, "bounds": [2.0, 100.0]}


def test_cylinder_curvature_requires_exactly_one_sag_or_radius():
    resolved = sample_project_config()
    resolved["mouth"]["curvature"]["sag"] = MOUTH_SAG
    resolved["mouth"]["curvature"]["radius"] = 500.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.curvature must specify exactly one of sag or radius for cylinder/sphere" in exc_info.value.errors


def test_sag_bounds_require_sag_and_contain_seed():
    resolved = sample_project_config()
    resolved["mouth"]["curvature"]["sag_bounds"] = [25.0, 40.0]

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.curvature.sag must be within mouth.curvature.sag_bounds" in exc_info.value.errors

    resolved = sample_project_config()
    resolved["mouth"]["curvature"] = {"type": "cylinder", "sag": None, "sag_bounds": [10.0, 40.0], "radius": 500.0}

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.curvature.sag_bounds requires mouth.curvature.sag" in exc_info.value.errors


def test_corner_radius_must_fit_inside_rectangle():
    resolved = sample_project_config()
    resolved["mouth"]["shape"]["corner_radius"] = 200.0

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert f"mouth.shape.corner_radius must be at most {MOUTH_HEIGHT / 2:g}" in exc_info.value.errors


def test_ellipse_rejects_corner_radius():
    resolved = sample_project_config()
    resolved["mouth"]["shape"] = {"type": "ellipse", "shape_power": 2.0, "corner_radius": 10.0}

    with pytest.raises(ConfigError) as exc_info:
        validate_config(resolved)

    assert "mouth.shape.corner_radius must be null when mouth.shape.type is ellipse" in exc_info.value.errors


def test_cli_writes_resolved_config_to_stdout(capsys):
    exit_code = main([str(PROJECT)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units:" in captured.out
    assert "scope: full" in captured.out
    assert captured.err == ""
