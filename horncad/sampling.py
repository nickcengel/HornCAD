"""Sampling helpers for curve and section generation."""

from __future__ import annotations

from bisect import bisect_left
import math
from typing import Callable, List, Tuple


def adaptive_stations(length: float, count: int, value_at: Callable[[float], float]) -> List[float]:
    """Return count + 1 stations with denser spacing where value changes faster."""

    if count <= 0:
        return [0.0]
    if length <= 0.0 or not math.isfinite(length):
        return [0.0 for _ in range(count + 1)]

    dense_count = max(count * 8, 32)
    dense_z = [length * index / dense_count for index in range(dense_count + 1)]
    dense_values = [value_at(z) for z in dense_z]
    cumulative = [0.0]
    total = 0.0
    for index in range(dense_count):
        dz = dense_z[index + 1] - dense_z[index]
        dv = dense_values[index + 1] - dense_values[index]
        segment = math.hypot(dz, dv)
        total += segment
        cumulative.append(total)

    if total <= 0.0:
        return [length * index / count for index in range(count + 1)]

    stations = []
    for index in range(count + 1):
        target = total * index / count
        right = bisect_left(cumulative, target)
        if right <= 0:
            stations.append(0.0)
        elif right >= len(cumulative):
            stations.append(length)
        else:
            left = right - 1
            span = cumulative[right] - cumulative[left]
            fraction = 0.0 if span == 0.0 else (target - cumulative[left]) / span
            stations.append(dense_z[left] + (dense_z[right] - dense_z[left]) * fraction)
    stations[0] = 0.0
    stations[-1] = length
    return stations


def adaptive_closed_angles(
    count: int,
    point_at: Callable[[float], Tuple[float, float]],
    forced_quadrant_angles: List[float] | None = None,
) -> List[float]:
    """Return symmetric closed-loop angles denser where boundary position changes faster."""

    if count <= 0:
        return []
    if count < 4:
        return [2.0 * math.pi * index / count for index in range(count)]

    quadrant_count = max(2, count // 4)
    quadrant = adaptive_angle_quadrant(quadrant_count, point_at)
    quadrant = _merge_forced_quadrant_angles(quadrant, forced_quadrant_angles or [])
    angles = set()
    for angle in quadrant:
        for mirrored in (
            angle,
            math.pi - angle,
            math.pi + angle,
            2.0 * math.pi - angle,
        ):
            wrapped = mirrored % (2.0 * math.pi)
            angles.add(round(wrapped, 12))
    return sorted(angles)


def _merge_forced_quadrant_angles(angles: List[float], forced_angles: List[float]) -> List[float]:
    merged = list(angles)
    used_indexes = {0, len(merged) - 1}
    for forced in sorted(forced_angles):
        if forced <= 0.0 or forced >= math.pi / 2.0:
            continue
        available = [index for index in range(1, len(merged) - 1) if index not in used_indexes]
        if not available:
            break
        nearest = min(available, key=lambda index: abs(merged[index] - forced))
        merged[nearest] = forced
        used_indexes.add(nearest)
    merged[0] = 0.0
    merged[-1] = math.pi / 2.0
    return sorted(merged)


def adaptive_angle_quadrant(
    segments: int,
    point_at: Callable[[float], Tuple[float, float]],
) -> List[float]:
    dense_count = max(segments * 16, 64)
    dense_angles = [(math.pi / 2.0) * index / dense_count for index in range(dense_count + 1)]
    dense_points = [point_at(angle) for angle in dense_angles]
    segment_lengths = []
    headings = []
    for index in range(dense_count):
        x0, y0 = dense_points[index]
        x1, y1 = dense_points[index + 1]
        dx = x1 - x0
        dy = y1 - y0
        segment_lengths.append(math.hypot(dx, dy))
        headings.append(math.atan2(dy, dx))

    chord_total = sum(segment_lengths)
    turn_scale = chord_total / (math.pi / 2.0) if chord_total > 0.0 else 0.0

    cumulative = [0.0]
    total = 0.0
    for index in range(dense_count):
        turn = 0.0
        if index > 0:
            delta = abs(headings[index] - headings[index - 1])
            turn = min(delta, 2.0 * math.pi - delta)
        total += segment_lengths[index] + 0.35 * turn_scale * turn
        cumulative.append(total)
    if total <= 0.0:
        return [(math.pi / 2.0) * index / segments for index in range(segments + 1)]
    angles = []
    for index in range(segments + 1):
        target = total * index / segments
        right = bisect_left(cumulative, target)
        if right <= 0:
            angles.append(0.0)
        elif right >= len(cumulative):
            angles.append(math.pi / 2.0)
        else:
            left = right - 1
            span = cumulative[right] - cumulative[left]
            fraction = 0.0 if span == 0.0 else (target - cumulative[left]) / span
            angles.append(dense_angles[left] + (dense_angles[right] - dense_angles[left]) * fraction)
    angles[0] = 0.0
    angles[-1] = math.pi / 2.0
    return angles
