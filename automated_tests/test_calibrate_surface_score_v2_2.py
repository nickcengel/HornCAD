from __future__ import annotations

import unittest

from app.tools.calibrate_surface_score_v2_2 import _fraction
from app.tools.surface_diagnostics import surface_score_v2_fraction


class SurfaceScoreV22CalibrationTests(unittest.TestCase):
    def test_selected_fraction_schedule_matches_implementation(self) -> None:
        for coverage in (25, 30, 35, 40, 45, 50):
            self.assertAlmostEqual(
                _fraction(coverage, 2.0, 0.65),
                surface_score_v2_fraction(coverage, "v2.2"),
            )

    def test_fraction_clamps_outside_calibration_grid(self) -> None:
        self.assertAlmostEqual(0.20, _fraction(20.0, 2.0, 0.65))
        self.assertAlmostEqual(0.65, _fraction(60.0, 2.0, 0.65))


if __name__ == "__main__":
    unittest.main()
