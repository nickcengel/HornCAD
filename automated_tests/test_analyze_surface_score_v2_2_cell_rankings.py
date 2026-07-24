from __future__ import annotations

import unittest

from app.tools.analyze_surface_score_v2_2_cell_rankings import (
    _rank_statistics,
)


class SurfaceScoreV22CellRankingAnalysisTests(unittest.TestCase):
    def test_rank_statistics_identify_exact_and_reversed_orders(self) -> None:
        mapping = {
            name: {"score": value}
            for name, value in zip("abcd", (4.0, 3.0, 2.0, 1.0))
        }
        exact = _rank_statistics(list("abcd"), mapping, "score")
        reversed_result = _rank_statistics(list("dcba"), mapping, "score")
        self.assertAlmostEqual(1.0, exact["spearman"])
        self.assertAlmostEqual(1.0, exact["pairwise_agreement"])
        self.assertTrue(exact["top_1_match"])
        self.assertAlmostEqual(-1.0, reversed_result["spearman"])
        self.assertAlmostEqual(0.0, reversed_result["pairwise_agreement"])
        self.assertFalse(reversed_result["top_1_match"])


if __name__ == "__main__":
    unittest.main()
