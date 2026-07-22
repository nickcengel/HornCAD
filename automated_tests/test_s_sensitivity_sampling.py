from __future__ import annotations

import unittest

from app.tools.apply_s_sensitivity_policy import configure
from app.tools.s_sensitivity_sampling import (
    SPoint, common_skeleton, interval_refinement_reason, replay,
    space_filling_order,
)


class SSensitivitySamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = [0.7, 1.0, 1.3, 1.6, 1.9, 2.2, 2.5, 2.8, 3.0]

    def test_common_thirty_degree_skeleton(self) -> None:
        self.assertEqual(common_skeleton(self.values),
                         [0.7, 1.3, 1.9, 2.5, 3.0])
        self.assertEqual(space_filling_order([0.7, 1.3, 1.9, 2.5, 3.0]),
                         [0.7, 3.0, 1.9, 1.3, 2.5])

    def test_flat_nonwinning_interval_does_not_refine(self) -> None:
        points = [SPoint(0.7, 80), SPoint(1.3, 80.4),
                  SPoint(1.9, 88), SPoint(2.5, 84), SPoint(3.0, 82)]
        self.assertIsNone(interval_refinement_reason(points, 1.0))

    def test_sensitive_interval_refines(self) -> None:
        points = [SPoint(0.7, 70), SPoint(1.3, 75),
                  SPoint(1.9, 88), SPoint(2.5, 84), SPoint(3.0, 82)]
        self.assertIn("variation", interval_refinement_reason(points, 1.0))

    def test_wide_interval_bordering_winner_refines(self) -> None:
        points = [SPoint(0.7, 80), SPoint(1.3, 88),
                  SPoint(1.9, 87.6), SPoint(2.5, 82), SPoint(3.0, 80)]
        self.assertIn("winner", interval_refinement_reason(points, 1.6))

    def test_replay_saves_flat_points_without_regret(self) -> None:
        scores = [70, 70.2, 70.4, 70.5, 70.6, 70.7, 70.8, 70.9, 71]
        result = replay(SPoint(s, score) for s, score in zip(self.values, scores))
        self.assertEqual(result["score_regret"], 0)
        self.assertGreaterEqual(result["saved_fraction"], 0.25)

    def test_policy_configuration_orders_and_requires_skeleton(self) -> None:
        document = {"bem_candidate_search": {"initial_pool": [
            {"label": f"coverage 30°, S={s:g}", "values": {"length_mm": s}}
            for s in self.values]}}

        configured = configure(document)["bem_candidate_search"]

        labels = [item["label"] for item in configured["initial_pool"]]
        self.assertEqual(labels[:5], [
            "coverage 30°, S=0.7", "coverage 30°, S=3",
            "coverage 30°, S=1.9", "coverage 30°, S=1.3",
            "coverage 30°, S=2.5",
        ])
        self.assertTrue(all(item.get("required")
                            for item in configured["initial_pool"][:5]))
        self.assertTrue(configured["s_sensitivity_sampling"]["enabled"])


if __name__ == "__main__":
    unittest.main()
