"""Project configuration loading, defaults, and validation."""

from __future__ import annotations

import argparse
import copy
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import yaml


ConfigDict = Dict[str, Any]


class ConfigError(ValueError):
    """Raised when a project configuration cannot be loaded or validated."""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


DEFAULT_CONFIG: ConfigDict = {
    "units": {
        "length": "mm",
        "angle": "degrees",
    },
    "throat": {
        "conic_extension": {
            "length": 0.0,
            "exit_angle": None,
        },
    },
    "mouth": {
        "shape": {
            "shape_power": 6.0,
            "corner_radius": None,
        },
        "curvature": {
            "sag": None,
            "sag_bounds": None,
            "radius": None,
        },
    },
    "profiles": {
        "coverage": {
            "horizontal": None,
            "vertical": None,
        },
        "roundover": {},
        "k": {
            "horizontal": {
                "seed": 1.0,
                "bounds": [1.0, 1.0],
            },
            "vertical": {
                "seed": 1.0,
                "bounds": [1.0, 1.0],
            },
        },
        "n": {
            "horizontal": {
                "seed": 3.0,
                "bounds": [2.0, 100.0],
            },
            "vertical": {
                "seed": 3.0,
                "bounds": [2.0, 100.0],
            },
        },
    },
    "morph": {
        "start": 0.0,
        "rate": {
            "seed": 2.0,
            "bounds": [0.25, 4.0],
        },
    },
    "surface": {
        "mode": "slice",
    },
    "refinement": {
        "area_rms_log_tolerance": 0.05,
        "smoothness_weight": 2.0,
        "max_log_area_slope_change": 0.01,
        "morph_timing_weight": 0.05,
        "morph_50_percent_max_z": 0.85,
        "morph_rate_drift_weight": 0.2,
        "k_drift_weight": 0.1,
        "sag_drift_weight": 0.1,
        "s_span_weight": 0.2,
        "s_smoothness_weight": 0.2,
        "radial_basis_weight": 1.0,
        "radial_exit_slope_weight": 0.5,
        "max_profile_slope_change": 2.0,
        "profile_smoothness_weight": 0.5,
    },
    "resolution": {
        "angular_segments": 96,
        "length_segments": 100,
    },
    "validation": {
        "reject_if": [],
        "warn_if": [],
    },
    "outputs": {
        "scope": "full",
        "cad": {
            "wall_thickness": 0.0,
            "formats": {
                "3d": {
                    "stl": False,
                },
            },
        },
    },
}

ALLOWED_UNITS = {
    "length": {"mm"},
    "angle": {"degrees"},
}
ALLOWED_MOUTH_SHAPES = {"ellipse", "rounded_rectangle", "rectangle"}
ALLOWED_CURVATURE_TYPES = {"flat", "cylinder", "sphere"}
ALLOWED_OUTPUT_SCOPES = {"quarter", "half", "full"}
ALLOWED_SURFACE_MODES = {"slice", "profile"}


def load_project(path: Path) -> ConfigDict:
    """Load, default, and validate a HornCAD project file."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ConfigError(["project file must contain a YAML mapping at the root"])

    resolved = resolve_config(loaded)
    validate_config(resolved)
    return resolved


def resolve_config(config: Mapping[str, Any]) -> ConfigDict:
    """Return a resolved configuration without mutating the authored mapping."""

    resolved = copy.deepcopy(DEFAULT_CONFIG)
    _deep_merge(resolved, copy.deepcopy(dict(config)))

    conic = resolved.setdefault("throat", {}).setdefault("conic_extension", {})
    if conic.get("exit_angle") is None and _has_path(resolved, ["throat", "angle"]):
        conic["exit_angle"] = resolved["throat"]["angle"]

    _normalize_roundover_specs(resolved)
    _normalize_axis_n_specs(resolved)
    _resolve_missing_mouth_dimension(resolved)

    return resolved


def validate_config(config: Mapping[str, Any]) -> None:
    errors: List[str] = []

    _require_mapping(config, [], errors)
    _require_enum(config, ["units", "length"], ALLOWED_UNITS["length"], errors)
    _require_enum(config, ["units", "angle"], ALLOWED_UNITS["angle"], errors)

    _require_number(config, ["throat", "diameter"], errors, minimum=0.0, exclusive_minimum=True)
    _require_number(config, ["throat", "angle"], errors, minimum=0.0, maximum=90.0)
    _require_number(
        config,
        ["throat", "conic_extension", "length"],
        errors,
        minimum=0.0,
    )
    _require_number(
        config,
        ["throat", "conic_extension", "exit_angle"],
        errors,
        minimum=0.0,
        maximum=90.0,
    )

    _validate_mouth_dimensions(config, errors)
    _require_enum(config, ["mouth", "shape", "type"], ALLOWED_MOUTH_SHAPES, errors)
    _optional_number(config, ["mouth", "shape", "shape_power"], errors, minimum=0.0, exclusive_minimum=True)
    _optional_number(config, ["mouth", "shape", "corner_radius"], errors, minimum=0.0)
    _validate_corner_radius(config, errors)
    _require_enum(config, ["mouth", "curvature", "type"], ALLOWED_CURVATURE_TYPES, errors)
    _optional_number(config, ["mouth", "curvature", "sag"], errors, minimum=0.0)
    _optional_number_bounds(config, ["mouth", "curvature", "sag_bounds"], errors, minimum=0.0)
    _optional_number(config, ["mouth", "curvature", "radius"], errors, minimum=0.0, exclusive_minimum=True)
    _validate_curvature(config, errors)

    _require_number(config, ["length", "max"], errors, minimum=0.0, exclusive_minimum=True)

    for axis in ("horizontal", "vertical"):
        _require_number(config, ["profiles", "coverage", axis], errors, minimum=0.0, maximum=180.0)
        _validate_roundover_spec(config, axis, errors)
        _validate_seeded_bounds(
            config,
            ["profiles", "k", axis],
            errors,
            minimum=0.0,
            maximum=10.0,
        )
    for axis in ("horizontal", "vertical"):
        _validate_seeded_bounds(config, ["profiles", "n", axis], errors, minimum=2.0, maximum=100.0)

    _require_number(config, ["morph", "start"], errors, minimum=0.0)
    _validate_seeded_bounds(
        config,
        ["morph", "rate"],
        errors,
        minimum=0.0,
        maximum=4.0,
        exclusive_minimum=True,
    )
    _require_enum(config, ["surface", "mode"], ALLOWED_SURFACE_MODES, errors)
    _require_number(config, ["refinement", "area_rms_log_tolerance"], errors, minimum=0.0)
    _require_number(config, ["refinement", "smoothness_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "max_log_area_slope_change"], errors, minimum=0.0)
    _require_number(config, ["refinement", "morph_timing_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "morph_50_percent_max_z"], errors, minimum=0.0, maximum=1.0)
    _require_number(config, ["refinement", "morph_rate_drift_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "k_drift_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "sag_drift_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "s_span_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "s_smoothness_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "radial_basis_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "radial_exit_slope_weight"], errors, minimum=0.0)
    _require_number(config, ["refinement", "max_profile_slope_change"], errors, minimum=0.0)
    _require_number(config, ["refinement", "profile_smoothness_weight"], errors, minimum=0.0)

    _require_integer(config, ["resolution", "angular_segments"], errors, minimum=1)
    _require_integer(config, ["resolution", "length_segments"], errors, minimum=1)

    _require_list(config, ["validation", "reject_if"], errors)
    _require_list(config, ["validation", "warn_if"], errors)
    _require_enum(config, ["outputs", "scope"], ALLOWED_OUTPUT_SCOPES, errors)
    _require_number(config, ["outputs", "cad", "wall_thickness"], errors, minimum=0.0)
    _require_bool(config, ["outputs", "cad", "formats", "3d", "stl"], errors)

    if errors:
        raise ConfigError(errors)


def dump_config(config: Mapping[str, Any]) -> str:
    """Serialize a resolved configuration as stable YAML."""

    return yaml.safe_dump(dict(config), sort_keys=False)


def profile_coverage(config: Mapping[str, Any], axis: str) -> float:
    return float(config["profiles"]["coverage"][axis])


def profile_k(config: Mapping[str, Any], axis: str) -> float:
    return float(config["profiles"]["k"][axis]["seed"])


def profile_q(config: Mapping[str, Any]) -> float:
    return 0.995


def profile_n(config: Mapping[str, Any], axis: str | None = None) -> float:
    n_config = config["profiles"]["n"]
    if axis is None:
        return (profile_n(config, "horizontal") + profile_n(config, "vertical")) / 2.0
    if "seed" in n_config:
        return float(n_config["seed"])
    return float(n_config[axis]["seed"])


def profile_roundover_target_percent(config: Mapping[str, Any], axis: str) -> float | None:
    spec = config.get("profiles", {}).get("roundover", {}).get(axis)
    if not isinstance(spec, Mapping):
        return None
    if "target_percent" in spec:
        return float(spec["target_percent"])
    return float(spec["seed"])


def profile_roundover_tolerance_percent(config: Mapping[str, Any], axis: str) -> float | None:
    spec = config.get("profiles", {}).get("roundover", {}).get(axis)
    if not isinstance(spec, Mapping):
        return None
    if "tolerance_percent" in spec:
        return float(spec["tolerance_percent"])
    seed = float(spec["seed"])
    lower, upper = spec["bounds"]
    return max(seed - float(lower), float(upper) - seed)


def morph_rate(config: Mapping[str, Any]) -> float:
    return float(config["morph"]["rate"]["seed"])


def surface_mode(config: Mapping[str, Any]) -> str:
    return str(config.get("surface", {}).get("mode", "slice"))


def mouth_curvature_sag(config: Mapping[str, Any]) -> float | None:
    sag = config["mouth"]["curvature"].get("sag")
    return float(sag) if sag is not None else None


def seeded_bounds(config: Mapping[str, Any], path: Sequence[str]) -> tuple[float, float]:
    value = _get(config, list(path) + ["bounds"])
    return float(value[0]), float(value[1])


def seeded_value(config: Mapping[str, Any], path: Sequence[str]) -> float:
    return float(_get(config, list(path) + ["seed"]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load and validate a HornCAD project file.")
    parser.add_argument("project", type=Path, help="Path to a HornCAD project YAML file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional path for the resolved YAML. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    try:
        resolved = load_project(args.project)
    except (OSError, yaml.YAMLError, ConfigError) as exc:
        _print_error(exc)
        return 1

    rendered = dump_config(resolved)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    return 0


def _deep_merge(target: ConfigDict, source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _normalize_roundover_specs(config: ConfigDict) -> None:
    roundover = config.get("profiles", {}).get("roundover", {})
    if not isinstance(roundover, dict):
        return
    for axis in ("horizontal", "vertical"):
        spec = roundover.get(axis)
        if not isinstance(spec, dict):
            continue
        if "target_percent" not in spec and "tolerance_percent" not in spec:
            continue
        target = spec.pop("target_percent", None)
        tolerance = spec.pop("tolerance_percent", None)
        if _is_number(target):
            spec["seed"] = float(target)
            if _is_number(tolerance):
                tol = float(tolerance)
                spec["bounds"] = [max(0.0, float(target) - tol), min(100.0, float(target) + tol)]


def _normalize_axis_n_specs(config: ConfigDict) -> None:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        return
    n_config = profiles.get("n")
    if not isinstance(n_config, dict) or "seed" not in n_config:
        return
    seed = n_config.get("seed")
    bounds = n_config.get("bounds")
    profiles["n"] = {
        "horizontal": {"seed": seed, "bounds": copy.deepcopy(bounds)},
        "vertical": {"seed": seed, "bounds": copy.deepcopy(bounds)},
    }


def _has_path(config: Mapping[str, Any], path: Sequence[str]) -> bool:
    current: Any = config
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _get(config: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = config
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _path(path: Iterable[str]) -> str:
    return ".".join(path)


def _require_mapping(config: Mapping[str, Any], path: Sequence[str], errors: List[str]) -> None:
    value = _get(config, path) if path else config
    if not isinstance(value, Mapping):
        errors.append(f"{_path(path) or 'project'} must be a mapping")


def _require_enum(config: Mapping[str, Any], path: Sequence[str], allowed: set, errors: List[str]) -> None:
    value = _get(config, path)
    if value not in allowed:
        errors.append(f"{_path(path)} must be one of {sorted(allowed)}")


def _require_number(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    exclusive_minimum: bool = False,
) -> None:
    value = _get(config, path)
    if not _is_number(value):
        errors.append(f"{_path(path)} must be a number")
        return
    _check_number_bounds(float(value), path, errors, minimum, maximum, exclusive_minimum)


def _optional_number(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    exclusive_minimum: bool = False,
) -> None:
    value = _get(config, path)
    if value is None:
        return
    if not _is_number(value):
        errors.append(f"{_path(path)} must be a number or null")
        return
    _check_number_bounds(float(value), path, errors, minimum, maximum, exclusive_minimum)


def _check_number_bounds(
    value: float,
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float],
    maximum: Optional[float],
    exclusive_minimum: bool,
) -> None:
    name = _path(path)
    if minimum is not None:
        if exclusive_minimum and value <= minimum:
            errors.append(f"{name} must be greater than {minimum:g}")
        elif not exclusive_minimum and value < minimum:
            errors.append(f"{name} must be at least {minimum:g}")
    if maximum is not None and value > maximum:
        errors.append(f"{name} must be at most {maximum:g}")


def _require_integer(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[int] = None,
) -> None:
    value = _get(config, path)
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{_path(path)} must be an integer")
        return
    if minimum is not None and value < minimum:
        errors.append(f"{_path(path)} must be at least {minimum}")


def _require_bool(config: Mapping[str, Any], path: Sequence[str], errors: List[str]) -> None:
    if not isinstance(_get(config, path), bool):
        errors.append(f"{_path(path)} must be true or false")


def _require_list(config: Mapping[str, Any], path: Sequence[str], errors: List[str]) -> None:
    if not isinstance(_get(config, path), list):
        errors.append(f"{_path(path)} must be a list")


def _validate_curvature(config: Mapping[str, Any], errors: List[str]) -> None:
    curvature_type = _get(config, ["mouth", "curvature", "type"])
    sag = _get(config, ["mouth", "curvature", "sag"])
    sag_bounds = _get(config, ["mouth", "curvature", "sag_bounds"])
    radius = _get(config, ["mouth", "curvature", "radius"])
    supplied = [value is not None for value in (sag, radius)].count(True)

    if curvature_type == "flat" and supplied:
        errors.append("mouth.curvature.sag and mouth.curvature.radius must be null when type is flat")
    elif curvature_type in {"cylinder", "sphere"} and supplied != 1:
        errors.append("mouth.curvature must specify exactly one of sag or radius for cylinder/sphere")
    if sag_bounds is not None and sag is None:
        errors.append("mouth.curvature.sag_bounds requires mouth.curvature.sag")
    if (
        isinstance(sag_bounds, list)
        and len(sag_bounds) == 2
        and all(_is_number(item) for item in sag_bounds)
        and _is_number(sag)
    ):
        lower, upper = float(sag_bounds[0]), float(sag_bounds[1])
        if not lower <= float(sag) <= upper:
            errors.append("mouth.curvature.sag must be within mouth.curvature.sag_bounds")


def _validate_roundover_spec(config: Mapping[str, Any], axis: str, errors: List[str]) -> None:
    path = ["profiles", "roundover", axis]
    roundover = config.get("profiles", {}).get("roundover", {})
    if axis not in roundover:
        return
    value = _get(config, path)
    if not isinstance(value, Mapping):
        errors.append(f"{_path(path)} must be a mapping")
        return
    has_seeded_bounds = "seed" in value or "bounds" in value
    has_legacy_target = "target_percent" in value or "tolerance_percent" in value
    if has_legacy_target:
        _require_number(config, path + ["target_percent"], errors, minimum=0.0, maximum=100.0)
        _require_number(config, path + ["tolerance_percent"], errors, minimum=0.0, maximum=100.0)
    if has_seeded_bounds:
        _validate_seeded_bounds(config, path, errors, minimum=0.0, maximum=100.0)
    if not has_seeded_bounds and not has_legacy_target:
        errors.append(f"{_path(path)} must define seed/bounds or target_percent/tolerance_percent")


def _validate_mouth_dimensions(config: Mapping[str, Any], errors: List[str]) -> None:
    width = _get(config, ["mouth", "width"])
    height = _get(config, ["mouth", "height"])
    supplied = [value is not None for value in (width, height)].count(True)
    if supplied == 0:
        errors.append("mouth must specify at least one of width or height")
        return
    if supplied == 1:
        missing = "width" if width is None else "height"
        errors.append(
            f"mouth.{missing} could not be derived from the specified principal dimension and H/V profile settings"
        )
        return
    _optional_number(config, ["mouth", "width"], errors, minimum=0.0, exclusive_minimum=True)
    _optional_number(config, ["mouth", "height"], errors, minimum=0.0, exclusive_minimum=True)


def _validate_corner_radius(config: Mapping[str, Any], errors: List[str]) -> None:
    shape_type = _get(config, ["mouth", "shape", "type"])
    corner_radius = _get(config, ["mouth", "shape", "corner_radius"])
    if corner_radius is None or not _is_number(corner_radius):
        return
    if shape_type == "ellipse":
        errors.append("mouth.shape.corner_radius must be null when mouth.shape.type is ellipse")
        return
    width = _get(config, ["mouth", "width"])
    height = _get(config, ["mouth", "height"])
    if not _is_number(width) or not _is_number(height):
        return
    maximum = min(float(width), float(height)) / 2.0
    if float(corner_radius) > maximum:
        errors.append(f"mouth.shape.corner_radius must be at most {maximum:g}")


def _resolve_missing_mouth_dimension(config: ConfigDict) -> None:
    mouth = config.get("mouth", {})
    if not isinstance(mouth, dict):
        return
    width = mouth.get("width")
    height = mouth.get("height")
    if (width is None) == (height is None):
        return
    if not _can_derive_mouth_dimension(config):
        return

    if width is None:
        known_axis = "vertical"
        missing_axis = "horizontal"
        known_target = float(height) / 2.0
    else:
        known_axis = "horizontal"
        missing_axis = "vertical"
        known_target = float(width) / 2.0

    solved_s = _solve_s_for_axis(config, known_axis, known_target)
    missing_target = _axis_boundary_distance_from_s(config, missing_axis, solved_s)
    if math.isfinite(missing_target) and missing_target > 0.0:
        mouth["width" if width is None else "height"] = missing_target * 2.0


def _can_derive_mouth_dimension(config: Mapping[str, Any]) -> bool:
    required_paths = [
        ["throat", "diameter"],
        ["throat", "angle"],
        ["throat", "conic_extension", "length"],
        ["throat", "conic_extension", "exit_angle"],
        ["length", "max"],
        ["profiles", "coverage", "horizontal"],
        ["profiles", "coverage", "vertical"],
        ["profiles", "k", "horizontal", "seed"],
        ["profiles", "k", "vertical", "seed"],
        ["profiles", "n", "horizontal", "seed"],
        ["profiles", "n", "vertical", "seed"],
    ]
    return all(_is_number(_get(config, path)) for path in required_paths)


def _solve_s_for_axis(config: Mapping[str, Any], axis: str, target_boundary_distance: float) -> float:
    profile_length = _axis_profile_length(config, axis, target_boundary_distance)
    if profile_length <= 0.0:
        return 0.0
    q = profile_q(config)
    n = profile_n(config, axis)
    base = _osse_radius_for_config(config, axis, profile_length, 0.0)
    unit = _termination_radius(profile_length, profile_length, 1.0, q, n)
    if unit == 0.0:
        return 0.0
    return (target_boundary_distance - base) / unit


def _axis_boundary_distance_from_s(config: Mapping[str, Any], axis: str, s: float) -> float:
    profile_length = _axis_profile_length(config, axis, None)
    if profile_length <= 0.0:
        return 0.0
    return _osse_radius_for_config(config, axis, profile_length, s)


def _axis_profile_length(config: Mapping[str, Any], axis: str, target_boundary_distance: float | None) -> float:
    length_max = float(config["length"]["max"])
    l_conic = float(config["throat"]["conic_extension"]["length"])
    curvature = config["mouth"]["curvature"]
    setback = 0.0
    if curvature["type"] == "cylinder" and axis == "horizontal":
        if curvature.get("sag") is not None:
            setback = float(curvature["sag"])
        elif target_boundary_distance is not None and curvature.get("radius") is not None:
            setback = _setback_from_radius(target_boundary_distance, float(curvature["radius"]))
    elif curvature["type"] == "sphere":
        # Missing dimensions make sphere sag/radius derivation implicit. Leave
        # full sphere support for a later solver pass.
        return math.nan
    return length_max - setback - l_conic


def _osse_radius_for_config(config: Mapping[str, Any], axis: str, z: float, s: float) -> float:
    throat = config["throat"]
    r0 = float(throat["diameter"]) / 2.0
    l_conic = float(throat["conic_extension"]["length"])
    alpha0_deg = float(throat["angle"])
    alpha_exit_deg = alpha0_deg if l_conic == 0.0 else float(throat["conic_extension"]["exit_angle"])
    r_conic_exit = r0 + l_conic * math.tan(math.radians(alpha_exit_deg))
    return _osse_radius(
        z,
        z,
        r_conic_exit,
        alpha_exit_deg,
        profile_coverage(config, axis),
        profile_k(config, axis),
        s,
        profile_q(config),
        profile_n(config, axis),
    )


def _osse_radius(
    z: float,
    length: float,
    r0: float,
    alpha0_deg: float,
    alpha_deg: float,
    k: float,
    s: float,
    q: float,
    n: float,
) -> float:
    alpha0 = math.radians(alpha0_deg)
    alpha = math.radians(alpha_deg)
    gos = math.sqrt(
        k * k * r0 * r0
        + 2.0 * k * r0 * z * math.tan(alpha0)
        + z * z * math.tan(alpha) * math.tan(alpha)
    ) + r0 * (1.0 - k)
    return gos + _termination_radius(z, length, s, q, n)


def _termination_radius(z: float, length: float, s: float, q: float, n: float) -> float:
    if s == 0.0 or length <= 0.0:
        return 0.0
    term_inner = max(1.0 - (q * z / length) ** n, 0.0)
    return (s * length / q) * (1.0 - term_inner ** (1.0 / n))


def _setback_from_radius(distance: float, radius: float) -> float:
    if math.isinf(radius):
        return 0.0
    if radius < distance:
        return math.nan
    return radius - math.sqrt(radius * radius - distance * distance)



def _validate_seeded_bounds(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float],
    maximum: Optional[float],
    exclusive_minimum: bool = False,
) -> None:
    name = _path(path)
    value = _get(config, path)
    if not isinstance(value, Mapping):
        errors.append(f"{name} must be a mapping with seed and bounds")
        return
    _require_number(config, list(path) + ["seed"], errors, minimum, maximum, exclusive_minimum)
    _validate_number_bounds(config, list(path) + ["bounds"], errors, minimum, maximum, exclusive_minimum)
    seed = _get(config, list(path) + ["seed"])
    bounds = _get(config, list(path) + ["bounds"])
    if _is_number(seed) and isinstance(bounds, list) and len(bounds) == 2 and all(_is_number(item) for item in bounds):
        lower, upper = float(bounds[0]), float(bounds[1])
        if not lower <= float(seed) <= upper:
            errors.append(f"{name}.seed must be within {name}.bounds")


def _validate_number_bounds(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float],
    maximum: Optional[float],
    exclusive_minimum: bool = False,
) -> None:
    value = _get(config, path)
    name = _path(path)
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(item) for item in value):
        errors.append(f"{name} must be a two-number list")
        return
    lower, upper = float(value[0]), float(value[1])
    _check_number_bounds(lower, path, errors, minimum, maximum, exclusive_minimum)
    _check_number_bounds(upper, path, errors, minimum, maximum, exclusive_minimum)
    if lower > upper:
        errors.append(f"{name} lower value must be less than or equal to upper value")


def _optional_number_bounds(
    config: Mapping[str, Any],
    path: Sequence[str],
    errors: List[str],
    minimum: Optional[float],
    maximum: Optional[float] = None,
    exclusive_minimum: bool = False,
) -> None:
    if _get(config, path) is None:
        return
    _validate_number_bounds(config, path, errors, minimum, maximum, exclusive_minimum)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _print_error(exc: BaseException) -> None:
    if isinstance(exc, ConfigError):
        sys.stderr.write("Configuration validation failed:\n")
        for error in exc.errors:
            sys.stderr.write(f"  - {error}\n")
    else:
        sys.stderr.write(f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
