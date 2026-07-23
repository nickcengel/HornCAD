from pathlib import Path
import unittest

from app.design_api import DesignIntent, RoundControlHeuristics
from app.tools.build_round_control_heuristics import build


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "models/round_control_heuristics_v1"


class RoundControlHeuristicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()
        cls.heuristics = RoundControlHeuristics.load(ARTIFACT)

    def test_exact_grid_length_is_preserved(self):
        seed = self.heuristics.axis_length(400, 50)
        self.assertAlmostEqual(seed.reference_length_mm, 117.433)
        self.assertAlmostEqual(seed.profile_length_mm, 1.2*117.433, places=3)
        self.assertEqual(seed.k, 6.0)

    def test_bilinear_axis_seed_is_bounded(self):
        seed = self.heuristics.axis_length(325, 37.5)
        corners = (
            self.heuristics.axis_length(300, 35).reference_length_mm,
            self.heuristics.axis_length(350, 35).reference_length_mm,
            self.heuristics.axis_length(300, 40).reference_length_mm,
            self.heuristics.axis_length(350, 40).reference_length_mm,
        )
        self.assertGreaterEqual(seed.reference_length_mm, min(corners))
        self.assertLessEqual(seed.reference_length_mm, max(corners))

    def test_changed_controls_can_preserve_coverage_s_seed(self):
        seed = self.heuristics.length_for_target_s(400, 45, 5.0, 7.0)
        actual = self.heuristics._s_at_length(
            400, 45, seed.profile_length_mm, 5.0, 7.0)
        self.assertAlmostEqual(actual, seed.target_s, places=8)

    def test_hv_seed_returns_flat_and_sag_options(self):
        result = self.heuristics.recommend(
            DesignIntent(400, 300, 50, 35))
        self.assertLess(
            result.horizontal.profile_length_mm,
            result.vertical.profile_length_mm)
        self.assertEqual(
            result.cylindrical_sag_compensation.active_axis, "horizontal")
        self.assertAlmostEqual(
            result.cylindrical_sag_compensation.profile_length_mm
            - result.cylindrical_sag_compensation.sag_mm,
            result.horizontal.profile_length_mm)
        self.assertAlmostEqual(
            result.cylindrical_sag_compensation.profile_length_mm,
            result.vertical.profile_length_mm)

    def test_outside_support_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside heuristic support"):
            self.heuristics.axis_length(500, 45)


if __name__ == "__main__":
    unittest.main()
