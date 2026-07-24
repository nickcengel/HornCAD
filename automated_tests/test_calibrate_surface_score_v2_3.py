from __future__ import annotations

import unittest

import numpy as np

from app.tools.calibrate_surface_score_v2_3 import (
    CORE_COMPONENTS,
    Guardrail,
    score_candidate,
)


class SurfaceScoreV23CalibrationTests(unittest.TestCase):
    def test_guarded_core_blends_with_v2_2_baseline(self) -> None:
        features = {
            "profile_rms": 100.0,
            "slice_energy": 100.0,
            "minus_six_line": 100.0,
            "beamwidth_quality": 100.0,
            "mean_containment": 75.0,
            "outward_rise": 60.0,
        }
        weights = np.full(len(CORE_COMPONENTS), 0.25)
        guardrail = Guardrail(0.2, 75.0, 60.0, 1.0, 0.125)
        self.assertAlmostEqual(
            84.0,
            score_candidate(features, weights, guardrail, 80.0),
        )

        features["mean_containment"] = 37.5
        self.assertAlmostEqual(
            74.0,
            score_candidate(features, weights, guardrail, 80.0),
        )

    def test_guardrails_do_not_reward_values_above_the_floor(self) -> None:
        features = {
            component: 80.0 for component in CORE_COMPONENTS
        }
        features.update({
            "mean_containment": 100.0,
            "outward_rise": 100.0,
        })
        weights = np.full(len(CORE_COMPONENTS), 0.25)
        guardrail = Guardrail(0.2, 75.0, 60.0, 1.0, 0.125)
        self.assertAlmostEqual(
            80.0,
            score_candidate(features, weights, guardrail, 80.0),
        )


if __name__ == "__main__":
    unittest.main()
