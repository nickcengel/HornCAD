"""Validation for the ``horn_optimizer`` YAML v1 contract."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any

import yaml


def _number(name: str, value: Any, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if nonnegative and result < 0:
        raise ValueError(f"{name} must be nonnegative")
    return result


@dataclass(frozen=True, slots=True)
class NumericRange:
    minimum: float
    maximum: float

    @classmethod
    def parse(cls, name: str, value: Any, *, positive: bool = False,
              nonnegative: bool = False) -> NumericRange:
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError(f"{name} range must contain [minimum, maximum]")
            low = _number(
                f"{name}[0]", value[0], positive=positive,
                nonnegative=nonnegative)
            high = _number(
                f"{name}[1]", value[1], positive=positive,
                nonnegative=nonnegative)
            if low > high:
                raise ValueError(f"{name} range minimum exceeds maximum")
            return cls(low, high)
        scalar = _number(
            name, value, positive=positive, nonnegative=nonnegative)
        return cls(scalar, scalar)

    @property
    def scalar(self) -> bool:
        return math.isclose(self.minimum, self.maximum, abs_tol=1e-12)

    @property
    def midpoint(self) -> float:
        return (self.minimum + self.maximum) / 2

    def clamp(self, value: float) -> float:
        return min(self.maximum, max(self.minimum, float(value)))

    def as_list(self) -> list[float]:
        return [self.minimum, self.maximum]


@dataclass(frozen=True, slots=True)
class MouthSpec:
    width_mm: NumericRange
    height_mm: NumericRange | None = None
    aspect_ratio: NumericRange | None = None

    def __post_init__(self) -> None:
        if (self.height_mm is None) == (self.aspect_ratio is None):
            raise ValueError(
                "mouth requires exactly one of height_mm or aspect_ratio")

    def dimensions(self, width_mm: float | None = None,
                   secondary: float | None = None) -> tuple[float, float]:
        width = self.width_mm.clamp(
            self.width_mm.midpoint if width_mm is None else width_mm)
        if self.height_mm is not None:
            height = self.height_mm.clamp(
                self.height_mm.midpoint if secondary is None else secondary)
        else:
            assert self.aspect_ratio is not None
            aspect = self.aspect_ratio.clamp(
                self.aspect_ratio.midpoint if secondary is None else secondary)
            height = width / aspect
        return width, height


@dataclass(frozen=True, slots=True)
class PracticalLimits:
    length_mm: NumericRange | None = None
    extension_mm: NumericRange = NumericRange(0.0, 60.0)
    k_horizontal: NumericRange = NumericRange(1.0, 7.0)
    k_vertical: NumericRange = NumericRange(1.0, 7.0)
    n_horizontal: NumericRange = NumericRange(2.0, 40.0)
    n_vertical: NumericRange = NumericRange(2.0, 40.0)


@dataclass(frozen=True, slots=True)
class RankingRule:
    enabled: bool = True
    surface_shortlist_points: float = 0.5
    tie_break: str = "throat_impedance"

    def __post_init__(self) -> None:
        if self.surface_shortlist_points < 0:
            raise ValueError("ranking.surface_shortlist_points must be nonnegative")
        if self.tie_break not in {"throat_impedance", "surface_only"}:
            raise ValueError(
                "ranking.tie_break must be throat_impedance or surface_only")


@dataclass(frozen=True, slots=True)
class SolverSpec:
    lower_frequency_hz: float = 500.0
    crossover_hz: float = 750.0
    upper_frequency_hz: float = 8000.0
    points_per_octave: float = 12.0
    confirmation_points_per_octave: float = 16.0
    elements_per_wavelength: float = 6.0
    angles: int = 91
    workers: int = 10

    def __post_init__(self) -> None:
        if not (
            0 < self.lower_frequency_hz <= self.crossover_hz
            < self.upper_frequency_hz
        ):
            raise ValueError(
                "solver frequencies require 0 < lower <= crossover < upper")
        if self.workers < 1 or self.workers > 20:
            raise ValueError("solver.workers must be between 1 and 20")
        if self.points_per_octave <= 0 or self.elements_per_wavelength <= 0:
            raise ValueError("solver sampling values must be positive")


@dataclass(frozen=True, slots=True)
class HornOptimizerConfig:
    source_path: Path
    output_dir: Path
    horizontal_coverage_deg: float
    vertical_coverage_deg: float
    throat_angle_deg: float
    mouth_shape: str
    mouth: MouthSpec
    sag_axes: str
    sag_mm: NumericRange
    max_simulations: int
    approval_mode: str
    seed_yaml: Path | None = None
    practical_limits: PracticalLimits = field(default_factory=PracticalLimits)
    ranking: RankingRule = field(default_factory=RankingRule)
    solver: SolverSpec = field(default_factory=SolverSpec)

    def __post_init__(self) -> None:
        for name in (
            "horizontal_coverage_deg", "vertical_coverage_deg",
        ):
            value = getattr(self, name)
            if not 0 < value <= 90:
                raise ValueError(f"{name} must be in (0, 90]")
        if self.mouth_shape not in {"round", "square"}:
            raise ValueError("mouth_shape must be round or square")
        if self.sag_axes not in {"none", "horizontal", "vertical", "both"}:
            raise ValueError(
                "sag_axes must be none, horizontal, vertical, or both")
        if self.sag_axes == "none" and self.sag_mm.maximum != 0:
            raise ValueError("sag_mm must be zero when sag_axes is none")
        if self.max_simulations < 1:
            raise ValueError("max_simulations must be positive")
        if self.approval_mode not in {"autonomous", "approval-gated"}:
            raise ValueError(
                "approval_mode must be autonomous or approval-gated")


def _mapping(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _optional_range(
    document: dict[str, Any], key: str, *, positive: bool = False,
    nonnegative: bool = False,
) -> NumericRange | None:
    if key not in document:
        return None
    return NumericRange.parse(
        key, document[key], positive=positive, nonnegative=nonnegative)


def load_optimizer_config(path: str | Path) -> HornOptimizerConfig:
    """Load and normalize one optimizer YAML without changing external state."""
    source = Path(path).resolve()
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    root = _mapping("YAML document", document).get("horn_optimizer")
    root = _mapping("horn_optimizer", root)
    if int(root.get("version", 0)) != 1:
        raise ValueError("expected horn_optimizer version 1")
    intent = _mapping("intent", root.get("intent"))
    mouth_doc = _mapping("mouth", root.get("mouth"))
    if "width_mm" not in mouth_doc:
        raise ValueError("mouth.width_mm is required")
    has_height = "height_mm" in mouth_doc
    has_aspect = "aspect_ratio" in mouth_doc
    if has_height == has_aspect:
        raise ValueError(
            "mouth requires width_mm plus exactly one of height_mm or "
            "aspect_ratio")
    mouth = MouthSpec(
        width_mm=NumericRange.parse(
            "mouth.width_mm", mouth_doc["width_mm"], positive=True),
        height_mm=(
            NumericRange.parse(
                "mouth.height_mm", mouth_doc["height_mm"], positive=True)
            if has_height else None
        ),
        aspect_ratio=(
            NumericRange.parse(
                "mouth.aspect_ratio", mouth_doc["aspect_ratio"], positive=True)
            if has_aspect else None
        ),
    )
    practical_doc = _mapping(
        "practical_limits", root.get("practical_limits", {}))
    practical = PracticalLimits(
        length_mm=_optional_range(
            practical_doc, "length_mm", positive=True),
        extension_mm=(
            _optional_range(
                practical_doc, "extension_mm", nonnegative=True)
            or NumericRange(0, 60)
        ),
        k_horizontal=(
            _optional_range(practical_doc, "k_horizontal", positive=True)
            or NumericRange(1, 7)
        ),
        k_vertical=(
            _optional_range(practical_doc, "k_vertical", positive=True)
            or NumericRange(1, 7)
        ),
        n_horizontal=(
            _optional_range(practical_doc, "n_horizontal", positive=True)
            or NumericRange(2, 40)
        ),
        n_vertical=(
            _optional_range(practical_doc, "n_vertical", positive=True)
            or NumericRange(2, 40)
        ),
    )
    ranking_doc = _mapping("ranking", root.get("ranking", {}))
    ranking = RankingRule(
        enabled=bool(ranking_doc.get("enabled", True)),
        surface_shortlist_points=_number(
            "ranking.surface_shortlist_points",
            ranking_doc.get("surface_shortlist_points", 0.5),
            nonnegative=True),
        tie_break=str(ranking_doc.get(
            "tie_break", "throat_impedance")),
    )
    solver_doc = _mapping("solver", root.get("solver", {}))
    solver = SolverSpec(
        lower_frequency_hz=_number(
            "solver.lower_frequency_hz",
            solver_doc.get("lower_frequency_hz", 500), positive=True),
        crossover_hz=_number(
            "solver.crossover_hz",
            solver_doc.get("crossover_hz", 750), positive=True),
        upper_frequency_hz=_number(
            "solver.upper_frequency_hz",
            solver_doc.get("upper_frequency_hz", 8000), positive=True),
        points_per_octave=_number(
            "solver.points_per_octave",
            solver_doc.get("points_per_octave", 12), positive=True),
        confirmation_points_per_octave=_number(
            "solver.confirmation_points_per_octave",
            solver_doc.get("confirmation_points_per_octave", 16),
            positive=True),
        elements_per_wavelength=_number(
            "solver.elements_per_wavelength",
            solver_doc.get("elements_per_wavelength", 6), positive=True),
        angles=int(solver_doc.get("angles", 91)),
        workers=int(solver_doc.get("workers", 10)),
    )
    seed = root.get("seed_yaml")
    seed_path = None
    if seed:
        seed_path = Path(str(seed))
        if not seed_path.is_absolute():
            seed_path = source.parent / seed_path
        seed_path = seed_path.resolve()
        if not seed_path.is_file():
            raise ValueError(f"seed_yaml does not exist: {seed_path}")
    output = Path(str(root.get("output_dir", source.with_suffix("").name)))
    if not output.is_absolute():
        output = source.parent / output
    sag_axes = str(root.get("sag_axes", "none"))
    sag_default: Any = 0 if sag_axes == "none" else root.get("sag_mm", 0)
    if sag_axes != "none" and "sag_mm" not in root:
        raise ValueError("sag_mm is required when sag_axes is enabled")
    return HornOptimizerConfig(
        source_path=source,
        output_dir=output.resolve(),
        horizontal_coverage_deg=_number(
            "intent.horizontal_coverage_deg",
            intent.get("horizontal_coverage_deg"), positive=True),
        vertical_coverage_deg=_number(
            "intent.vertical_coverage_deg",
            intent.get("vertical_coverage_deg"), positive=True),
        throat_angle_deg=_number(
            "throat_angle_deg", root.get("throat_angle_deg"), positive=True),
        mouth_shape=str(root.get("mouth_shape", "")),
        mouth=mouth,
        sag_axes=sag_axes,
        sag_mm=NumericRange.parse(
            "sag_mm", sag_default, nonnegative=True),
        max_simulations=int(root.get("max_simulations", 0)),
        approval_mode=str(root.get("approval_mode", "autonomous")),
        seed_yaml=seed_path,
        practical_limits=practical,
        ranking=ranking,
        solver=solver,
    )
