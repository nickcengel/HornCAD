"""Secondary composite score for surface and throat-impedance diagnostics."""
from __future__ import annotations

import math
from typing import Any


COMPOSITE_SCORE_VERSION = "1.0"
COMPOSITE_SCORE_WEIGHTS = {
    "surface": 0.75,
    "throat_impedance": 0.25,
}


def _percent(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("overall_percent")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    value = float(value)
    if not 0.0 <= value <= 100.0:
        return None
    return value


def composite_surface_impedance_score(
    surface: dict[str, Any] | float | None,
    throat_impedance: dict[str, Any] | float | None,
) -> dict[str, Any] | None:
    """Combine available diagnostic scores without changing ranking policy."""
    surface_percent = _percent(surface)
    impedance_percent = _percent(throat_impedance)
    if surface_percent is None or impedance_percent is None:
        return None
    overall = (
        COMPOSITE_SCORE_WEIGHTS["surface"] * surface_percent
        + COMPOSITE_SCORE_WEIGHTS["throat_impedance"] * impedance_percent
    )
    return {
        "version": COMPOSITE_SCORE_VERSION,
        "status": "secondary_not_authoritative_for_ranking",
        "overall_percent": float(overall),
        "components": {
            "surface": surface_percent,
            "throat_impedance": impedance_percent,
        },
        "component_versions": {
            "surface": (
                surface.get("version") if isinstance(surface, dict) else None
            ),
            "throat_impedance": (
                throat_impedance.get("diagnostic_version")
                if isinstance(throat_impedance, dict) else None
            ),
        },
        "component_weights": COMPOSITE_SCORE_WEIGHTS,
        "authoritative_for_ranking": False,
    }
