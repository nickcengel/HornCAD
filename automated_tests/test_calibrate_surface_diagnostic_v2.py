import unittest

from app.tools.calibrate_surface_diagnostic_v2 import (
    _candidate_selection,
    _round_statistics,
)
from app.tools.surface_diagnostics import SURFACE_SCORE_V2_CANDIDATE_WEIGHTS


class SurfaceDiagnosticV2CalibrationTests(unittest.TestCase):
    def test_round_statistics_reward_matching_order(self):
        order = [f"P{index}" for index in range(10)]
        values = {plot_id: 10 - index for index, plot_id in enumerate(order)}
        result = _round_statistics(order, values)
        self.assertAlmostEqual(result["spearman"], 1.0)
        self.assertAlmostEqual(result["pairwise_agreement"], 1.0)

    def test_candidate_selection_uses_close_agreement_with_broad_guardrail(self):
        metrics = ["v1", *SURFACE_SCORE_V2_CANDIDATE_WEIGHTS]
        per_round = {}
        for number in range(1, 21):
            per_round[str(number)] = {}
            for metric in metrics:
                close_value = 0.6 if metric == "balanced" else 0.2
                broad_value = 0.9
                if metric == "balanced":
                    broad_value = 0.86
                per_round[str(number)][metric] = {
                    "spearman": broad_value if number <= 10 else close_value,
                    "pairwise_agreement": 0.8 if metric == "balanced" else 0.6,
                }
        self.assertEqual(
            _candidate_selection(per_round, set(range(1, 21))),
            "balanced",
        )


if __name__ == "__main__":
    unittest.main()
