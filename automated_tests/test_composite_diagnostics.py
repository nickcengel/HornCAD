from __future__ import annotations

import unittest

from app.tools.composite_diagnostics import (
    COMPOSITE_SCORE_WEIGHTS,
    composite_surface_impedance_score,
)


class CompositeDiagnosticsTests(unittest.TestCase):
    def test_composite_uses_75_25_weights_and_is_not_authoritative(self) -> None:
        result = composite_surface_impedance_score(
            {"overall_percent": 80.0},
            {"overall_percent": 60.0},
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(75.0, result["overall_percent"])
        self.assertEqual(
            {"surface": 0.75, "throat_impedance": 0.25},
            COMPOSITE_SCORE_WEIGHTS,
        )
        self.assertFalse(result["authoritative_for_ranking"])

    def test_composite_requires_both_finite_scores(self) -> None:
        self.assertIsNone(composite_surface_impedance_score(
            {"overall_percent": 80.0}, None))
        self.assertIsNone(composite_surface_impedance_score(
            101.0, 80.0))


if __name__ == "__main__":
    unittest.main()
