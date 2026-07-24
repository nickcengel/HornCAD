from __future__ import annotations

import unittest

import numpy as np

from app.tools.fit_surface_score_weights_to_cell_rankings import fit_weights


class SurfaceScoreWeightFitTests(unittest.TestCase):
    def test_fit_prefers_component_consistent_with_order(self) -> None:
        features = {
            f"p{index}": {"good": 10.0 - index, "bad": float(index)}
            for index in range(10)
        }
        cell = {
            "order": list(features),
            "features": features,
        }
        weights = fit_weights(
            [cell], ("good", "bad"), np.asarray([0.5, 0.5])
        )
        self.assertGreater(weights[0], 0.99)
        self.assertLess(weights[1], 0.01)
        self.assertAlmostEqual(1.0, float(np.sum(weights)))


if __name__ == "__main__":
    unittest.main()
