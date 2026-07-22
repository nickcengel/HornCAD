"""Sensitivity-driven selection and retrospective replay for uniform S grids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SPoint:
    s: float
    score: float


def common_skeleton(values: Iterable[float], max_spacing: float = 0.6) -> list[float]:
    """Return endpoints plus a shared coarse skeleton on authored coordinates."""
    available = sorted(set(round(float(value), 6) for value in values))
    if len(available) <= 2:
        return available
    selected = [available[0]]
    while available[-1] - selected[-1] > max_spacing + 1e-9:
        candidates = [value for value in available
                      if selected[-1] < value <= selected[-1] + max_spacing + 1e-9]
        if not candidates:
            candidates = [value for value in available if value > selected[-1]]
        selected.append(max(candidates))
    if selected[-1] != available[-1]:
        selected.append(available[-1])
    return selected


def space_filling_order(values: Iterable[float]) -> list[float]:
    """Order fixed anchors as low, high, then repeated largest-gap midpoints."""
    remaining = sorted(set(round(float(value), 6) for value in values))
    if len(remaining) <= 1:
        return remaining
    ordered = [remaining.pop(0), remaining.pop(-1)]
    while remaining:
        measured = sorted(ordered)
        best = max(remaining, key=lambda value: min(
            abs(value - measured[index]) if not measured[index] < value < measured[index + 1]
            else min(value - measured[index], measured[index + 1] - value)
            for index in range(len(measured) - 1)))
        # Prefer the point nearest the midpoint of the largest measured gap.
        gaps = [(measured[index + 1] - measured[index], measured[index], measured[index + 1])
                for index in range(len(measured) - 1)]
        _, lower, upper = max(gaps)
        inside = [value for value in remaining if lower < value < upper]
        if inside:
            midpoint = (lower + upper) / 2
            best = min(inside, key=lambda value: (abs(value - midpoint), value))
        ordered.append(best)
        remaining.remove(best)
    return ordered


def interval_refinement_reason(points: Iterable[SPoint], target_s: float,
                               variation_points: float = 0.75,
                               winner_resolution: float = 0.3) -> str | None:
    """Explain why an authored target inside a measured interval must run."""
    measured = sorted(points, key=lambda point: point.s)
    lower_index = next((index for index in range(len(measured) - 1)
                        if measured[index].s < target_s < measured[index + 1].s), None)
    if lower_index is None:
        return "target is not bracketed by measured skeleton points"
    lower, upper = measured[lower_index], measured[lower_index + 1]
    delta = abs(upper.score - lower.score)
    if delta > variation_points:
        return f"endpoint score variation {delta:.3f} exceeds {variation_points:g}"
    best = max(measured, key=lambda point: point.score)
    if (upper.s - lower.s > winner_resolution + 1e-9 and
            (abs(best.s - lower.s) <= 1e-6 or abs(best.s - upper.s) <= 1e-6)):
        return "interval borders the current winner and is wider than the winner resolution"
    if 0 < lower_index and lower_index + 2 < len(measured):
        previous, following = measured[lower_index - 1], measured[lower_index + 2]
        left_slope = (lower.score - previous.score) / (lower.s - previous.s)
        right_slope = (following.score - upper.score) / (following.s - upper.s)
        if left_slope > 0 and right_slope < 0:
            return "adjacent slopes reverse around the interval"
    return None


def replay(points: Iterable[SPoint], *, max_spacing: float = 0.6,
           variation_points: float = 0.75,
           winner_resolution: float = 0.3) -> dict[str, object]:
    """Replay adaptive selection over a completed dense curve."""
    all_points = sorted(points, key=lambda point: point.s)
    by_s = {round(point.s, 6): point for point in all_points}
    skeleton = common_skeleton(by_s, max_spacing)
    selected = {value for value in skeleton}
    changed = True
    while changed:
        changed = False
        measured = [by_s[value] for value in sorted(selected)]
        for target in sorted(set(by_s) - selected):
            reason = interval_refinement_reason(
                measured, target, variation_points, winner_resolution)
            if reason is not None:
                selected.add(target)
                changed = True
                break
    full_best = max(all_points, key=lambda point: point.score)
    sampled_best = max((by_s[value] for value in selected), key=lambda point: point.score)
    return {
        "skeleton": skeleton,
        "selected_s": sorted(selected),
        "full_best_s": full_best.s,
        "full_best_score": full_best.score,
        "selected_best_s": sampled_best.s,
        "selected_best_score": sampled_best.score,
        "score_regret": full_best.score - sampled_best.score,
        "s_error": abs(full_best.s - sampled_best.s),
        "saved_fraction": 1 - len(selected) / len(all_points),
    }
