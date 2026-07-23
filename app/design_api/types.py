"""Stable value types for HornCAD's learned design application."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Mapping


STANDARD_DIAGNOSTICS = (
    "surface_score",
    "mean_containment",
    "profile_rms_error",
    "slice_energy_rms_departure",
    "outward_rise_violation",
    "minus_six_db_rms_error",
)


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and greater than zero")


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class DesignIntent:
    """Mouth and coverage requested by a user, independent of optimization."""

    mouth_width_mm: float
    mouth_height_mm: float
    horizontal_coverage_deg: float
    vertical_coverage_deg: float

    def __post_init__(self) -> None:
        for name in ("mouth_width_mm", "mouth_height_mm"):
            _positive(name, getattr(self, name))
        for name in ("horizontal_coverage_deg", "vertical_coverage_deg"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 < value <= 90.0:
                raise ValueError(f"{name} must be in (0, 90]")

    @classmethod
    def round(cls, mouth_mm: float, coverage_deg: float) -> DesignIntent:
        return cls(mouth_mm, mouth_mm, coverage_deg, coverage_deg)


@dataclass(frozen=True, slots=True)
class DesignPoint:
    """Complete authored geometry coordinates accepted by a model.

    ``profile_length_mm`` is strictly the OS-SE profile length. Extension and
    sag remain separate controls; a solved total length belongs in prediction
    derived geometry rather than being silently substituted here.
    """

    intent: DesignIntent
    profile_length_mm: float
    k_horizontal: float
    n_horizontal: float
    k_vertical: float
    n_vertical: float
    extension_mm: float = 0.0
    throat_angle_deg: float = 6.0
    mouth_squareness: float = 0.0
    sag_mm: float = 0.0

    def __post_init__(self) -> None:
        _positive("profile_length_mm", self.profile_length_mm)
        for name in ("k_horizontal", "n_horizontal", "k_vertical", "n_vertical"):
            _positive(name, getattr(self, name))
        for name in ("extension_mm", "mouth_squareness", "sag_mm"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
        _finite("throat_angle_deg", self.throat_angle_deg)

    @classmethod
    def round(
        cls,
        mouth_mm: float,
        coverage_deg: float,
        profile_length_mm: float,
        k: float,
        n: float,
        **geometry: float,
    ) -> DesignPoint:
        return cls(
            intent=DesignIntent.round(mouth_mm, coverage_deg),
            profile_length_mm=profile_length_mm,
            k_horizontal=k,
            n_horizontal=n,
            k_vertical=k,
            n_vertical=n,
            **geometry,
        )


@dataclass(frozen=True, slots=True)
class Estimate:
    mean: float
    lower: float
    upper: float

    def __post_init__(self) -> None:
        for name in ("mean", "lower", "upper"):
            _finite(name, getattr(self, name))
        if not self.lower <= self.mean <= self.upper:
            raise ValueError("estimate must satisfy lower <= mean <= upper")


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    LIMITED = "limited"
    EXTRAPOLATED = "extrapolated"
    INVALID_GEOMETRY = "invalid_geometry"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class Prediction:
    design: DesignPoint
    diagnostics: Mapping[str, Estimate]
    derived_geometry: Mapping[str, float]
    support: SupportStatus
    model_id: str
    warnings: tuple[str, ...] = ()
    nearest_evidence_ids: tuple[str, ...] = ()
    model_predictions: Mapping[str, Mapping[str, Estimate]] = field(
        default_factory=dict)

    @property
    def surface_score(self) -> Estimate:
        try:
            return self.diagnostics["surface_score"]
        except KeyError as error:
            raise KeyError("prediction does not contain surface_score") from error


@dataclass(frozen=True, slots=True)
class Objective:
    diagnostic: str
    direction: str = "maximize"
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.direction not in {"maximize", "minimize"}:
            raise ValueError("direction must be 'maximize' or 'minimize'")
        if not math.isfinite(self.weight) or self.weight <= 0.0:
            raise ValueError("weight must be finite and greater than zero")


@dataclass(frozen=True, slots=True)
class DesignConstraints:
    """Model-level constraints; deterministic geometry gates still apply."""

    profile_length_mm: tuple[float, float] | None = None
    k: tuple[float, float] | None = None
    n: tuple[float, float] | None = None
    minimum_surface_score: float | None = None
    maximum_uncertainty: float | None = None

    def __post_init__(self) -> None:
        for name in ("profile_length_mm", "k", "n"):
            bounds = getattr(self, name)
            if bounds is not None and (
                    len(bounds) != 2 or not all(math.isfinite(x) for x in bounds)
                    or bounds[0] > bounds[1]):
                raise ValueError(f"{name} must be finite (minimum, maximum) bounds")


@dataclass(frozen=True, slots=True)
class Recommendation:
    prediction: Prediction
    expected_deltas: Mapping[str, Estimate]
    rationale: tuple[str, ...]
    confirmation_required: bool = True


@dataclass(frozen=True, slots=True)
class Diagnosis:
    prediction: Prediction
    issues: tuple[str, ...]
    control_sensitivities: Mapping[str, Mapping[str, float]]
    recommendations: tuple[Recommendation, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentProposal:
    design: DesignPoint
    purpose: str
    acquisition_score: float
    nearest_evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str | float] = field(default_factory=dict)
