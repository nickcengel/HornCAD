from __future__ import annotations

import unittest

from app.tools.calibrate_surface_score_v2_pairwise import (
    _revised_score,
    _v2_fraction,
)


class SurfaceScoreV21PairwiseCalibrationTests(unittest.TestCase):
    def test_narrow_coverage_blend(self) -> None:
        candidate = {
            "coverage_deg": 25.0,
            "score_v1": 80.0,
            "score_v2": 60.0,
        }
        self.assertAlmostEqual(0.20, _v2_fraction(25.0))
        self.assertAlmostEqual(76.0, _revised_score(candidate))

    def test_correction_tapers_to_zero(self) -> None:
        self.assertAlmostEqual(0.60, _v2_fraction(27.5))
        self.assertAlmostEqual(1.00, _v2_fraction(30.0))
        self.assertAlmostEqual(1.00, _v2_fraction(45.0))


if __name__ == "__main__":
    unittest.main()
