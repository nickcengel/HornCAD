"""Nonlocal baffled-aperture radiation operators.

The time convention is ``exp(+i omega t)``.  Piecewise-constant normal velocity
on triangular aperture panels is mapped to collocated complex pressure through
the Rayleigh integral.  The diagonal uses the exact integral over an
equal-area circular panel, avoiding a singular point evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy import linalg, special


@dataclass(frozen=True)
class RadiationMedium:
    density_kg_m3: float = 1.2041
    sound_speed_m_s: float = 343.21


def triangle_panels(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return triangle centroids and positive areas in SI units."""
    triangles = np.asarray(vertices, dtype=float)[np.asarray(faces, dtype=np.int64)]
    cross = np.cross(triangles[:, 1] - triangles[:, 0],
                     triangles[:, 2] - triangles[:, 0])
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    if np.any(areas <= 0.0):
        raise ValueError("aperture contains a degenerate triangle")
    return triangles.mean(axis=1), areas


def rayleigh_impedance_matrix(centroids_m: np.ndarray, areas_m2: np.ndarray,
                              frequency_hz: float,
                              medium: RadiationMedium = RadiationMedium()) -> np.ndarray:
    """Map panel-normal velocity to collocated pressure, ``p = Z @ v``.

    This is the infinite-baffle Rayleigh kernel. Cross-panel integrals use a
    centroid rule; self-panel integrals use an equal-area disk with radius
    ``sqrt(area/pi)`` and are finite for all positive frequencies.
    """
    points = np.asarray(centroids_m, dtype=float)
    areas = np.asarray(areas_m2, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) != len(areas):
        raise ValueError("centroids must be Nx3 and share length with areas")
    if frequency_hz <= 0.0 or medium.density_kg_m3 <= 0.0 or medium.sound_speed_m_s <= 0.0:
        raise ValueError("frequency and medium properties must be positive")
    if np.any(areas <= 0.0):
        raise ValueError("panel areas must be positive")
    omega = 2.0 * math.pi * frequency_hz
    wave_number = omega / medium.sound_speed_m_s
    separation = points[:, None, :] - points[None, :, :]
    distance = np.linalg.norm(separation, axis=2)
    kernel = np.zeros(distance.shape, dtype=np.complex128)
    off_diagonal = ~np.eye(len(points), dtype=bool)
    kernel[off_diagonal] = (
        np.exp(-1j * wave_number * distance[off_diagonal]) /
        distance[off_diagonal]
    )
    kernel *= areas[None, :]
    equivalent_radius = np.sqrt(areas / math.pi)
    # Integral_0^a exp(-ikr)/r * 2*pi*r dr.
    self_integral = 2.0 * math.pi * (
        1.0 - np.exp(-1j * wave_number * equivalent_radius)
    ) / (1j * wave_number)
    np.fill_diagonal(kernel, self_integral)
    return 1j * medium.density_kg_m3 * omega / (2.0 * math.pi) * kernel


def solve_normal_velocity(impedance: np.ndarray, pressure: np.ndarray,
                          condition_limit: float = 1e12) -> np.ndarray:
    """Apply the pressure-to-velocity aperture map with a condition gate."""
    matrix = np.asarray(impedance, dtype=np.complex128)
    pressure = np.asarray(pressure, dtype=np.complex128)
    condition = float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition > condition_limit:
        raise ValueError(f"aperture impedance is ill-conditioned: {condition:.6g}")
    return linalg.solve(matrix, pressure, assume_a="gen", check_finite=True)


def uniform_specific_impedance(impedance: np.ndarray, areas_m2: np.ndarray) -> complex:
    """Area-average pressure for unit uniform normal velocity."""
    areas = np.asarray(areas_m2, dtype=float)
    pressure = np.asarray(impedance) @ np.ones(len(areas), dtype=np.complex128)
    return complex(np.sum(areas * pressure) / np.sum(areas))


def circular_piston_specific_impedance(radius_m: float, frequency_hz: float,
                                       medium: RadiationMedium = RadiationMedium()) -> complex:
    """Analytic infinite-baffle circular-piston specific radiation impedance."""
    if radius_m <= 0.0 or frequency_hz <= 0.0:
        raise ValueError("radius and frequency must be positive")
    ka = 2.0 * math.pi * frequency_hz * radius_m / medium.sound_speed_m_s
    resistance = 1.0 - special.j1(2.0 * ka) / ka
    reactance = special.struve(1, 2.0 * ka) / ka
    return medium.density_kg_m3 * medium.sound_speed_m_s * (resistance + 1j * reactance)

