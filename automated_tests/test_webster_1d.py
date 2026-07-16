import math
from pathlib import Path
import unittest

import numpy as np

from app.webster_1d import (
    AreaProfile,
    Medium,
    frequency_grid,
    horncad_area_profile,
    solve_frequency,
)


class Webster1DTests(unittest.TestCase):
    def test_matched_uniform_duct_has_no_input_reflection(self) -> None:
        area = 0.01
        profile = AreaProfile(
            positions_m=np.linspace(0.0, 0.5, 21),
            areas_m2=np.full(21, area),
            s_horizontal=0.0,
            s_vertical=0.0,
        )
        result = solve_frequency(profile, 1000.0, Medium(), "anechoic")
        expected = Medium().density_kg_m3 * Medium().sound_speed_m_s / area
        self.assertAlmostEqual(result.input_impedance_pa_s_m3.real, expected, places=7)
        self.assertAlmostEqual(result.input_impedance_pa_s_m3.imag, 0.0, places=7)
        self.assertLess(abs(result.throat_reflection), 1e-12)
        self.assertAlmostEqual(abs(result.mouth_volume_velocity_ratio), 1.0, places=12)

    def test_negative_s_is_always_invalid(self) -> None:
        profile = AreaProfile(
            positions_m=np.array([0.0, 0.1]),
            areas_m2=np.array([0.001, 0.002]),
            s_horizontal=-0.01,
            s_vertical=0.1,
        )
        with self.assertRaisesRegex(ValueError, "derived S must be nonnegative"):
            profile.validate()

    def test_contracting_area_is_invalid(self) -> None:
        profile = AreaProfile(
            positions_m=np.array([0.0, 0.1, 0.2]),
            areas_m2=np.array([0.001, 0.002, 0.0015]),
            s_horizontal=0.0,
            s_vertical=0.0,
        )
        with self.assertRaisesRegex(ValueError, "not monotonically expanding"):
            profile.validate()

    def test_frequency_grid_endpoints(self) -> None:
        grid = frequency_grid(100.0, 10_000.0, 5, "log")
        self.assertEqual(len(grid), 5)
        self.assertTrue(math.isclose(grid[0], 100.0))
        self.assertTrue(math.isclose(grid[-1], 10_000.0))

    def test_current_sample_produces_valid_expanding_area(self) -> None:
        path = Path(__file__).parents[1] / "examples" / "osse-400x280-reference" / "project.yaml"
        profile = horncad_area_profile(path, 41)
        self.assertGreaterEqual(profile.s_horizontal, 0.0)
        self.assertGreaterEqual(profile.s_vertical, 0.0)
        self.assertGreater(profile.areas_m2[-1], profile.areas_m2[0])
        self.assertAlmostEqual(profile.positions_m[-1], 0.30, places=12)


if __name__ == "__main__":
    unittest.main()
