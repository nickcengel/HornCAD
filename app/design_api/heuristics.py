"""Measured seed heuristics for translating H/V intent into starting geometry."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from .types import DesignIntent


@dataclass(frozen=True, slots=True)
class AxisLengthSeed:
    mouth_mm: float
    coverage_deg: float
    reference_length_mm: float
    profile_length_mm: float
    length_factor: float
    k: float
    n: float
    target_s: float
    source_cell: str


@dataclass(frozen=True, slots=True)
class SagCompensationSeed:
    profile_length_mm: float
    sag_mm: float
    horizontal_enabled: bool
    vertical_enabled: bool
    active_axis: str
    sag_to_active_half_span: float
    status: str


@dataclass(frozen=True, slots=True)
class RoundControlSeed:
    intent: DesignIntent
    horizontal: AxisLengthSeed
    vertical: AxisLengthSeed
    flat_profile_length_mm: float
    k_horizontal: float
    n_horizontal: float
    k_vertical: float
    n_vertical: float
    cylindrical_sag_compensation: SagCompensationSeed
    warnings: tuple[str, ...]


def _bracket(value: float, grid: list[float]) -> tuple[float, float]:
    if value < grid[0] or value > grid[-1]:
        raise ValueError(
            f"{value:g} is outside heuristic support [{grid[0]:g}, "
            f"{grid[-1]:g}]")
    for low, high in zip(grid, grid[1:]):
        if low <= value <= high:
            return low, high
    return grid[-1], grid[-1]


def _mix(low: float, high: float, value: float,
         low_value: float, high_value: float) -> float:
    if math.isclose(low, high):
        return low_value
    fraction = (value-low)/(high-low)
    return low_value+fraction*(high_value-low_value)


class RoundControlHeuristics:
    """Load the audited rule artifact and generate a non-predictive design seed."""

    def __init__(self, artifact: dict[str, Any]):
        self.artifact = artifact

    @classmethod
    def load(cls, path: str | Path) -> RoundControlHeuristics:
        artifact_path = Path(path)
        if artifact_path.is_dir():
            artifact_path /= "heuristics.json"
        value = json.loads(artifact_path.read_text(encoding="utf-8"))
        if value.get("heuristic_id") != "round_control_heuristics_v1":
            raise ValueError("unsupported round-control heuristic artifact")
        return cls(value)

    def axis_length(self, mouth_mm: float,
                    coverage_deg: float) -> AxisLengthSeed:
        mouths = [float(value) for value in self.artifact["domain"]["mouth_mm"]]
        angles = [
            float(value)
            for value in self.artifact["domain"]["coverage_half_angle_deg"]
        ]
        mouth_low, mouth_high = _bracket(float(mouth_mm), mouths)
        angle_low, angle_high = _bracket(float(coverage_deg), angles)
        table = self.artifact["reference_length_mm"]

        def at(angle: float, mouth: float) -> float:
            return float(table[f"{angle:g}"][f"{mouth:g}"])

        low_angle = _mix(
            mouth_low, mouth_high, mouth_mm,
            at(angle_low, mouth_low), at(angle_low, mouth_high))
        high_angle = _mix(
            mouth_low, mouth_high, mouth_mm,
            at(angle_high, mouth_low), at(angle_high, mouth_high))
        reference = _mix(
            angle_low, angle_high, coverage_deg, low_angle, high_angle)
        nearest_mouth = min(
            mouths, key=lambda value: abs(value-mouth_mm)/50.0)
        nearest_angle = min(
            angles, key=lambda value: abs(value-coverage_deg)/5.0)
        source_cell = f"{nearest_angle:g}deg-{nearest_mouth:g}mm"
        observed = self.artifact["audit"]["observed_high_score_zones"][
            "cells"][source_cell]["best"]["coordinate"]
        s_table = self.artifact["s_guidance_by_coverage"]
        s_low = float(s_table[f"{angle_low:g}"]["median"])
        s_high = float(s_table[f"{angle_high:g}"]["median"])
        target_s = _mix(
            angle_low, angle_high, coverage_deg, s_low, s_high)
        length_factor = float(observed["length_factor"])
        return AxisLengthSeed(
            mouth_mm=float(mouth_mm),
            coverage_deg=float(coverage_deg),
            reference_length_mm=float(reference),
            profile_length_mm=float(reference*length_factor),
            length_factor=length_factor,
            k=float(observed["k"]),
            n=float(observed["n"]),
            target_s=float(target_s),
            source_cell=source_cell,
        )

    @staticmethod
    def _s_at_length(mouth_mm: float, coverage_deg: float, length_mm: float,
                     k: float, n: float) -> float:
        q = 0.995
        r0 = 12.7
        throat_angle = math.radians(6.0)
        coverage = math.radians(coverage_deg)
        base = (
            r0+length_mm*math.tan(throat_angle)
            + math.sqrt(
                k*k*r0*r0
                + length_mm*length_mm*math.tan(coverage)**2)
            - k*r0
        )
        termination = (
            length_mm/q
            * (1.0-(1.0-q**n)**(1.0/n))
        )
        return (mouth_mm/2.0-base)/termination

    def length_for_target_s(
        self,
        mouth_mm: float,
        coverage_deg: float,
        k: float,
        n: float,
        target_s: float | None = None,
    ) -> AxisLengthSeed:
        """Reconcile a changed K/N pair with the measured coverage-level S seed."""
        seed = self.axis_length(mouth_mm, coverage_deg)
        target = seed.target_s if target_s is None else float(target_s)
        if not all(math.isfinite(value) and value > 0.0 for value in (
                mouth_mm, coverage_deg, k, n, target)):
            raise ValueError("mouth, coverage, K, N, and target S must be positive")
        low = seed.reference_length_mm*0.2
        high = seed.reference_length_mm*2.0
        low_s = self._s_at_length(mouth_mm, coverage_deg, low, k, n)
        high_s = self._s_at_length(mouth_mm, coverage_deg, high, k, n)
        if not high_s <= target <= low_s:
            raise ValueError(
                f"target S {target:g} is not bracketed by feasible seed lengths")
        for _ in range(80):
            middle = (low+high)/2.0
            middle_s = self._s_at_length(
                mouth_mm, coverage_deg, middle, k, n)
            if middle_s > target:
                low = middle
            else:
                high = middle
        length = (low+high)/2.0
        return AxisLengthSeed(
            mouth_mm=float(mouth_mm),
            coverage_deg=float(coverage_deg),
            reference_length_mm=seed.reference_length_mm,
            profile_length_mm=float(length),
            length_factor=float(length/seed.reference_length_mm),
            k=float(k),
            n=float(n),
            target_s=target,
            source_cell=seed.source_cell,
        )

    def recommend(self, intent: DesignIntent) -> RoundControlSeed:
        horizontal = self.axis_length(
            intent.mouth_width_mm, intent.horizontal_coverage_deg)
        vertical = self.axis_length(
            intent.mouth_height_mm, intent.vertical_coverage_deg)
        width = intent.mouth_width_mm
        height = intent.mouth_height_mm
        flat = (
            width*horizontal.profile_length_mm
            + height*vertical.profile_length_mm
        ) / (width+height)
        difference = (
            vertical.profile_length_mm-horizontal.profile_length_mm)
        if difference > 0.0:
            axis = "horizontal"
            h_enabled, v_enabled = True, False
            active_half_span = width/2.0
            profile_length = vertical.profile_length_mm
        elif difference < 0.0:
            axis = "vertical"
            h_enabled, v_enabled = False, True
            active_half_span = height/2.0
            profile_length = horizontal.profile_length_mm
        else:
            axis = "none"
            h_enabled = v_enabled = False
            active_half_span = math.inf
            profile_length = horizontal.profile_length_mm
        sag = abs(difference)
        feasible = sag <= active_half_span
        status = (
            "geometrically reconciles principal-axis seed lengths; acoustic "
            "effect unvalidated"
            if feasible else
            "length mismatch exceeds active half-span; do not apply")
        compensation = SagCompensationSeed(
            profile_length_mm=float(profile_length),
            sag_mm=float(sag),
            horizontal_enabled=h_enabled if feasible else False,
            vertical_enabled=v_enabled if feasible else False,
            active_axis=axis if feasible else "none",
            sag_to_active_half_span=(
                0.0 if not math.isfinite(active_half_span)
                else float(sag/active_half_span)),
            status=status,
        )
        return RoundControlSeed(
            intent=intent,
            horizontal=horizontal,
            vertical=vertical,
            flat_profile_length_mm=float(flat),
            k_horizontal=horizontal.k,
            n_horizontal=horizontal.n,
            k_vertical=vertical.k,
            n_vertical=vertical.n,
            cylindrical_sag_compensation=compensation,
            warnings=(
                "length rules come from round zero-extension evidence",
                "axis controls come from the nearest measured cell winner",
                "H/V combination and sag are starting constructions, not "
                "validated performance predictions",
                "recheck length after material K/N, extension, squareness, or "
                "throat changes",
            ),
        )
