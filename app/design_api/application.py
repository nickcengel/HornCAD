"""Public façade and backend contract for learned HornCAD design models."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from .types import (
    DesignConstraints, DesignIntent, DesignPoint, Diagnosis,
    ExperimentProposal, Objective, Prediction, Recommendation,
)


class ModelBackend(Protocol):
    """Implementation boundary shared by Python and future browser runtimes."""

    @property
    def model_id(self) -> str: ...

    def predict(self, design: DesignPoint) -> Prediction: ...

    def diagnose(
        self, design: DesignPoint, *, objectives: Sequence[Objective],
    ) -> Diagnosis: ...

    def improve(
        self,
        design: DesignPoint,
        *,
        objectives: Sequence[Objective],
        constraints: DesignConstraints,
        limit: int,
    ) -> Sequence[Recommendation]: ...

    def design(
        self,
        intent: DesignIntent,
        *,
        objectives: Sequence[Objective],
        constraints: DesignConstraints,
        limit: int,
    ) -> Sequence[Recommendation]: ...

    def select_experiments(
        self,
        intents: Sequence[DesignIntent],
        *,
        constraints: DesignConstraints,
        budget: int,
    ) -> Sequence[ExperimentProposal]: ...


class ModelNotReadyError(RuntimeError):
    """Raised while the documented JSON runtime has not yet been implemented."""


class DesignApplication:
    """User-facing operations over a fitted model or layered model bundle."""

    def __init__(self, backend: ModelBackend):
        self._backend = backend

    @property
    def model_id(self) -> str:
        return self._backend.model_id

    @classmethod
    def load(cls, model_directory: str | Path) -> DesignApplication:
        """Load a released portable model."""
        model_path = Path(model_directory) / "model.json"
        if not model_path.is_file():
            raise FileNotFoundError(f"portable model not found: {model_path}")
        from .portable import PortableRoundControlBackend
        return cls(PortableRoundControlBackend(model_path))

    def predict(self, design: DesignPoint) -> Prediction:
        return self._backend.predict(design)

    def diagnose(
        self,
        design: DesignPoint,
        *,
        objectives: Sequence[Objective] = (),
    ) -> Diagnosis:
        return self._backend.diagnose(design, objectives=tuple(objectives))

    def improve(
        self,
        design: DesignPoint,
        *,
        objectives: Sequence[Objective] = (
            Objective("surface_score", "maximize"),
        ),
        constraints: DesignConstraints = DesignConstraints(),
        limit: int = 5,
    ) -> tuple[Recommendation, ...]:
        if limit < 1:
            raise ValueError("limit must be at least one")
        return tuple(self._backend.improve(
            design, objectives=tuple(objectives), constraints=constraints,
            limit=limit))

    def design(
        self,
        intent: DesignIntent,
        *,
        objectives: Sequence[Objective] = (
            Objective("surface_score", "maximize"),
        ),
        constraints: DesignConstraints = DesignConstraints(),
        limit: int = 5,
    ) -> tuple[Recommendation, ...]:
        if limit < 1:
            raise ValueError("limit must be at least one")
        return tuple(self._backend.design(
            intent, objectives=tuple(objectives), constraints=constraints,
            limit=limit))

    def select_experiments(
        self,
        intents: Sequence[DesignIntent],
        *,
        constraints: DesignConstraints = DesignConstraints(),
        budget: int,
    ) -> tuple[ExperimentProposal, ...]:
        if budget < 1:
            raise ValueError("budget must be at least one")
        return tuple(self._backend.select_experiments(
            tuple(intents), constraints=constraints, budget=budget))
