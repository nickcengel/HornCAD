from horncad.config import resolve_config


THROAT_DIAMETER = 18.0
THROAT_ANGLE = 6.0
CONIC_EXTENSION_LENGTH = 9.0
CONIC_EXTENSION_EXIT_ANGLE = 8.0
MOUTH_WIDTH = 260.0
MOUTH_HEIGHT = 150.0
MOUTH_SAG = 20.0
LENGTH_MAX = 125.0
HORIZONTAL_COVERAGE = 42.0
VERTICAL_COVERAGE = 28.0
ROUNDOVER_TARGET_PERCENT = 30.0
ROUNDOVER_TOLERANCE_PERCENT = 5.0
ANGULAR_SEGMENTS = 96
LENGTH_SEGMENTS = 100


def sample_project_config():
    return resolve_config(
        {
            "throat": {
                "diameter": THROAT_DIAMETER,
                "angle": THROAT_ANGLE,
                "conic_extension": {
                    "length": CONIC_EXTENSION_LENGTH,
                    "exit_angle": CONIC_EXTENSION_EXIT_ANGLE,
                },
            },
            "mouth": {
                "width": MOUTH_WIDTH,
                "height": MOUTH_HEIGHT,
                "shape": {"type": "rounded_rectangle", "shape_power": 6.0, "corner_radius": None},
                "curvature": {"type": "cylinder", "sag": MOUTH_SAG, "radius": None},
            },
            "length": {"max": LENGTH_MAX},
            "profiles": {
                "coverage": {"horizontal": HORIZONTAL_COVERAGE, "vertical": VERTICAL_COVERAGE},
                "roundover": {
                    "horizontal": {
                        "seed": ROUNDOVER_TARGET_PERCENT,
                        "bounds": [
                            ROUNDOVER_TARGET_PERCENT - ROUNDOVER_TOLERANCE_PERCENT,
                            ROUNDOVER_TARGET_PERCENT + ROUNDOVER_TOLERANCE_PERCENT,
                        ],
                    },
                    "vertical": {
                        "seed": ROUNDOVER_TARGET_PERCENT,
                        "bounds": [
                            ROUNDOVER_TARGET_PERCENT - ROUNDOVER_TOLERANCE_PERCENT,
                            ROUNDOVER_TARGET_PERCENT + ROUNDOVER_TOLERANCE_PERCENT,
                        ],
                    },
                },
                "k": {
                    "horizontal": {"seed": 1.0, "bounds": [1.0, 1.0]},
                    "vertical": {"seed": 1.0, "bounds": [1.0, 1.0]},
                },
                "n": {
                    "horizontal": {"seed": 2.0, "bounds": [2.0, 100.0]},
                    "vertical": {"seed": 2.0, "bounds": [2.0, 100.0]},
                },
            },
            "morph": {"start": 0.0, "rate": {"seed": 2.0, "bounds": [0.25, 4.0]}},
            "resolution": {"angular_segments": ANGULAR_SEGMENTS, "length_segments": LENGTH_SEGMENTS},
            "validation": {
                "reject_if": [
                    "conic_extension_length_gte_local_profile_length",
                    "mouth_curvature_radius_too_small",
                ],
                "warn_if": ["outside_surface_self_intersects", "area_error_exceeds_tolerance"],
            },
            "refinement": {
                "area_rms_log_tolerance": 0.02,
                "max_log_area_slope_change": 0.2,
                "morph_timing_weight": 0.05,
                "morph_50_percent_max_z": 0.85,
                "morph_rate_drift_weight": 0.2,
                "k_drift_weight": 0.1,
                "sag_drift_weight": 0.1,
                "max_profile_slope_change": 2.0,
                "smoothness_weight": 2.0,
                "s_span_weight": 0.2,
                "s_smoothness_weight": 0.2,
                "profile_smoothness_weight": 0.5,
            },
            "outputs": {"scope": "full"},
        }
    )


def small_project_config():
    config = sample_project_config()
    config["resolution"]["angular_segments"] = 24
    config["resolution"]["length_segments"] = 30
    return config
