"""Runtime for portable round-control JSON models."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

import numpy as np

from .types import (
    DesignConstraints, DesignIntent, DesignPoint, Diagnosis, Estimate,
    ExperimentProposal, Objective, Prediction, Recommendation, SupportStatus,
)


def _termination_unit(z: float, length: float, n: float) -> float:
    q = 0.995
    inner = max(1.0 - (q * z / length) ** n, 0.0)
    return (length / q) * (1.0 - inner ** (1.0 / n))


def _base_radius(z: float, r0: float, coverage: float, k: float,
                 throat_angle: float) -> float:
    return (r0 + z * math.tan(math.radians(throat_angle))
            + math.sqrt(k*k*r0*r0 +
                        z*z*math.tan(math.radians(coverage))**2) - k*r0)


def _geometry(length: float, mouth: float, coverage: float, k: float,
              n: float, throat_radius: float, throat_angle: float
              ) -> dict[str, float]:
    unit = _termination_unit(length, length, n)
    s = ((mouth / 2.0) -
         _base_radius(length, throat_radius, coverage, k, throat_angle)) / unit
    step = max(0.01, length * 1e-4)

    def radius(z: float) -> float:
        return (_base_radius(z, throat_radius, coverage, k, throat_angle)
                + s * _termination_unit(z, length, n))

    samples = [radius(max(0.0, length - i*step)) for i in range(4)]
    slope = (3*samples[0] - 4*samples[1] + samples[2]) / (2*step)
    second = (2*samples[0] - 5*samples[1] +
              4*samples[2] - samples[3]) / (step*step)
    curvature = abs(second) / max((1+slope*slope)**1.5, 1e-12)
    growth = max(0.0, ((mouth/2.0) - radius(0.9*length)) /
                 max((mouth/2.0) - throat_radius, 1e-9))
    return {
        "s_horizontal": s, "s_vertical": s,
        "mouth_exit_angle_deg": math.degrees(math.atan(slope)),
        "mouth_curvature_radius_mm": (
            math.inf if curvature < 1e-12 else 1.0 / curvature),
        "final_tenth_radial_growth_fraction": growth,
        "total_length_mm": length,
    }


def _bracket(grid: list[float], value: float) -> tuple[float, float, float]:
    if value <= grid[0]:
        return grid[0], grid[0], 0.0
    if value >= grid[-1]:
        return grid[-1], grid[-1], 0.0
    upper = next(index for index, item in enumerate(grid) if item >= value)
    low, high = grid[upper-1], grid[upper]
    return low, high, (value-low)/(high-low)


def _basis(model: dict, length_factor: float, k: float, n: float) -> np.ndarray:
    scaling = model["control_scaling"]
    l = ((length_factor-scaling["length_factor"]["center"]) /
         scaling["length_factor"]["scale"])
    kk = (k-scaling["k"]["center"])/scaling["k"]["scale"]
    nn = (n-scaling["n"]["center"])/scaling["n"]["scale"]
    return np.asarray((1, l, kk, nn, l*l, kk*kk, nn*nn,
                       l*kk, l*nn, kk*nn), dtype=float)


def evaluate(model: dict, design: DesignPoint) -> tuple[dict[str, float], float]:
    mouth = design.intent.mouth_width_mm
    coverage = design.intent.horizontal_coverage_deg
    mouths = list(map(float, model["mouth_grid_mm"]))
    coverages = list(map(float, model["coverage_grid_deg"]))
    m0, m1, tm = _bracket(mouths, mouth)
    c0, c1, tc = _bracket(coverages, coverage)
    corners = ((c0,m0,(1-tc)*(1-tm)), (c0,m1,(1-tc)*tm),
               (c1,m0,tc*(1-tm)), (c1,m1,tc*tm))
    active = [(c,m,w) for c,m,w in corners if w > 0] or [(c0,m0,1.0)]
    reference = sum(
        model["reference_length_mm"][f"{int(c)}deg-{int(m)}mm"]*weight
        for c,m,weight in active)
    basis = _basis(model, design.profile_length_mm/reference,
                   design.k_horizontal, design.n_horizontal)
    values = {
        name: float(sum(
            weight*np.dot(
                model["cells"][f"{int(c)}deg-{int(m)}mm"]["coefficients"][name],
                basis)
            for c,m,weight in active))
        for name in model["diagnostics"]
    }
    return values, reference


class PortableRoundControlBackend:
    """Read-only evaluator for primary or augmented round-control releases."""

    def __init__(self, model_path: Path):
        self.path = model_path
        self.model = json.loads(model_path.read_text(encoding="utf-8"))
        index_path = model_path.with_name("training_index.json")
        self.index = (json.loads(index_path.read_text())["rows"]
                      if index_path.is_file() else [])
        self.companion = None
        companion = self.model.get("companion_model")
        if companion:
            companion_path = (model_path.parent / companion).resolve()
            if companion_path.is_file():
                self.companion = json.loads(companion_path.read_text())

    @property
    def model_id(self) -> str:
        return str(self.model["model_id"])

    def _validate_design(self, design: DesignPoint) -> dict[str, float]:
        intent = design.intent
        if not (
            math.isclose(intent.mouth_width_mm, intent.mouth_height_mm)
            and math.isclose(intent.horizontal_coverage_deg,
                             intent.vertical_coverage_deg)
            and math.isclose(design.k_horizontal, design.k_vertical)
            and math.isclose(design.n_horizontal, design.n_vertical)
            and math.isclose(design.extension_mm, 0.0)
            and math.isclose(design.mouth_squareness, 0.0)
            and math.isclose(design.sag_mm, 0.0)
            and math.isclose(design.throat_angle_deg, 6.0)
        ):
            raise ValueError(
                "round control supports only axisymmetric round-mouth, "
                "zero-extension, zero-sag designs with a 6 degree throat angle")
        policy = self.model["geometry_policy"]
        geometry = _geometry(
            design.profile_length_mm, intent.mouth_width_mm,
            intent.horizontal_coverage_deg, design.k_horizontal,
            design.n_horizontal, policy["throat_radius_mm"],
            policy["throat_angle_deg"])
        lower, upper = policy["derived_s_bounds"]
        if not lower <= geometry["s_horizontal"] <= upper:
            raise ValueError(
                f"invalid geometry: derived S {geometry['s_horizontal']:.6g} "
                f"is outside [{lower}, {upper}]")
        if (geometry["final_tenth_radial_growth_fraction"] >
                policy["maximum_final_tenth_radial_growth_fraction"]):
            raise ValueError("invalid geometry: final-tenth radial growth exceeds 52%")
        return geometry

    def _support(self, design: DesignPoint, reference: float
                 ) -> tuple[SupportStatus, float, list[str]]:
        mouth = design.intent.mouth_width_mm
        coverage = design.intent.horizontal_coverage_deg
        warnings = []
        distance = 0.0
        for value, bounds, name in (
            (mouth, self.model["mouth_grid_mm"], "mouth"),
            (coverage, self.model["coverage_grid_deg"], "coverage"),
            (design.profile_length_mm/reference, (0.8, 1.2), "length factor"),
            (design.k_horizontal, (2.0, 6.0), "K"),
            (design.n_horizontal, (4.0, 16.0), "N"),
        ):
            low, high = float(bounds[0]), float(bounds[-1])
            if value < low:
                distance += (low-value)/max(high-low, 1e-9)
                warnings.append(f"{name} is below fitted support")
            elif value > high:
                distance += (value-high)/max(high-low, 1e-9)
                warnings.append(f"{name} is above fitted support")
        if distance:
            return SupportStatus.EXTRAPOLATED, 1.0+distance, warnings
        evidence_distance = self._nearest_distance(design, reference)
        limited = False
        widening = 1.0
        if evidence_distance > 0.75:
            limited = True
            widening = max(widening, 1.25 + evidence_distance - 0.75)
            warnings.append(
                "joint L/K/N coordinate is distant from measured evidence "
                f"(normalized distance {evidence_distance:.3g})")
        if (mouth not in self.model["mouth_grid_mm"] or
                coverage not in self.model["coverage_grid_deg"]):
            limited = True
            widening = max(widening, 1.25)
            warnings.append(
                "mouth/coverage coefficient interpolation is not simulation-confirmed")
        if limited:
            return SupportStatus.LIMITED, widening, warnings
        return SupportStatus.SUPPORTED, 1.0, warnings

    def _evidence(self) -> list[dict]:
        return [row for row in self.index if row["role"] in {
            "fit", "locked_validation", "historical_challenge"
        } and row["reference_length_mm"]]

    @staticmethod
    def _evidence_distance(design: DesignPoint, reference: float,
                           row: dict) -> float:
        return math.sqrt(
            ((row["mouth_mm"]-design.intent.mouth_width_mm)/50)**2 +
            ((row["coverage_deg"]-
              design.intent.horizontal_coverage_deg)/5)**2 +
            ((row["length_factor"]-
              design.profile_length_mm/reference)/0.2)**2 +
            ((row["k"]-design.k_horizontal)/2)**2 +
            ((row["n"]-design.n_horizontal)/4)**2)

    def _nearest_distance(self, design: DesignPoint, reference: float) -> float:
        candidates = self._evidence()
        if not candidates:
            return math.inf
        return min(
            self._evidence_distance(design, reference, row)
            for row in candidates)

    def _nearest(self, design: DesignPoint, reference: float) -> tuple[str, ...]:
        candidates = self._evidence()
        ranked = sorted(candidates, key=lambda row:
                        self._evidence_distance(design, reference, row))
        return tuple(row["id"] for row in ranked[:3])

    def predict(self, design: DesignPoint) -> Prediction:
        geometry = self._validate_design(design)
        current, reference = evaluate(self.model, design)
        model_values = {self.model_id: current}
        chosen = current
        chosen_id = self.model_id
        if self.companion is not None:
            primary, _ = evaluate(self.companion, design)
            model_values[self.companion["model_id"]] = primary
            cell = (f"{round(design.intent.horizontal_coverage_deg/5)*5}deg-"
                    f"{round(design.intent.mouth_width_mm/50)*50}mm")
            choice = self.model.get("choice_by_cell", {}).get(cell, {})
            if choice.get("normal_model") == "primary":
                chosen, chosen_id = primary, self.companion["model_id"]
        support, widening, warnings = self._support(design, reference)
        intervals = self.model.get("interval_half_width", {})
        diagnostics = {
            name: Estimate(value, value-widening*float(intervals.get(name, 0.0)),
                           value+widening*float(intervals.get(name, 0.0)))
            for name, value in chosen.items()
        }
        side_by_side = {
            model_id: {
                name: Estimate(value, value-float(intervals.get(name, 0.0)),
                               value+float(intervals.get(name, 0.0)))
                for name, value in values.items()
            }
            for model_id, values in model_values.items()
        }
        if chosen_id != self.model_id:
            warnings.append(
                "primary is the normal choice in this cell because augmented "
                "locked validation was not at least as good")
        warnings.append(
            "throat_impedance_score is experimental and is not part of surface_score")
        return Prediction(
            design=design, diagnostics=diagnostics, derived_geometry=geometry,
            support=support, model_id=chosen_id, warnings=tuple(warnings),
            nearest_evidence_ids=self._nearest(design, reference),
            model_predictions=side_by_side)

    def _deferred(self) -> None:
        from .application import ModelNotReadyError
        raise ModelNotReadyError(
            "this release verifies predict() only; diagnosis, improvement, "
            "design search, and experiment selection are deferred")

    def diagnose(self, design: DesignPoint, *,
                 objectives: Sequence[Objective]) -> Diagnosis:
        self._deferred()

    def improve(self, design: DesignPoint, *, objectives: Sequence[Objective],
                constraints: DesignConstraints,
                limit: int) -> Sequence[Recommendation]:
        self._deferred()

    def design(self, intent: DesignIntent, *, objectives: Sequence[Objective],
               constraints: DesignConstraints,
               limit: int) -> Sequence[Recommendation]:
        self._deferred()

    def select_experiments(
            self, intents: Sequence[DesignIntent], *,
            constraints: DesignConstraints,
            budget: int) -> Sequence[ExperimentProposal]:
        self._deferred()
