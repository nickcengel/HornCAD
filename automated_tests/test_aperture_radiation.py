import math
import unittest

import numpy as np
from scipy.spatial import Delaunay

from app.tools.aperture_radiation import (
    RadiationMedium,
    circular_piston_specific_impedance,
    rayleigh_impedance_matrix,
    solve_normal_velocity,
    triangle_panels,
    uniform_specific_impedance,
)


def disk_panels(radius: float, radial_samples: int = 10, angular_samples: int = 48):
    points = [[0.0, 0.0]]
    for radial in range(1, radial_samples + 1):
        r = radius * radial / radial_samples
        count = max(8, round(angular_samples * radial / radial_samples))
        points.extend((r * math.cos(2 * math.pi * i / count),
                       r * math.sin(2 * math.pi * i / count)) for i in range(count))
    xy = np.asarray(points)
    faces = Delaunay(xy).simplices
    centroids = xy[faces].mean(axis=1)
    faces = faces[np.linalg.norm(centroids, axis=1) <= radius * (1 + 1e-12)]
    vertices = np.column_stack((xy, np.zeros(len(xy))))
    return triangle_panels(vertices, faces)


class ApertureRadiationTests(unittest.TestCase):
    def test_velocity_pressure_round_trip(self) -> None:
        centroids, areas = disk_panels(0.05, 5, 24)
        impedance = rayleigh_impedance_matrix(centroids, areas, 1_000.0)
        velocity = np.exp(1j * np.linspace(0.0, 0.5, len(areas)))
        recovered = solve_normal_velocity(impedance, impedance @ velocity)
        np.testing.assert_allclose(recovered, velocity, rtol=1e-9, atol=1e-9)

    def test_uniform_disk_matches_analytic_piston_impedance(self) -> None:
        radius = 0.05
        frequency = 550.0  # ka ~= 0.5: both resistance and reactance are material.
        medium = RadiationMedium()
        centroids, areas = disk_panels(radius, 10, 48)
        numerical = uniform_specific_impedance(
            rayleigh_impedance_matrix(centroids, areas, frequency, medium), areas)
        analytic = circular_piston_specific_impedance(radius, frequency, medium)
        self.assertLess(abs(numerical - analytic) / abs(analytic), 0.08)
        self.assertGreater(numerical.real, 0.0)
        self.assertGreater(numerical.imag, 0.0)

    def test_input_validation(self) -> None:
        with self.assertRaises(ValueError):
            rayleigh_impedance_matrix(np.zeros((1, 3)), np.ones(1), 0.0)


if __name__ == "__main__":
    unittest.main()
