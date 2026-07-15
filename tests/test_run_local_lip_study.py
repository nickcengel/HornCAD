import unittest

import numpy as np

from app.local_lip_bem import LocalLipResult
from app.run_local_lip_study import (
    COMPLEX_RELATIVE_L2_LIMIT,
    adjacent_metrics,
    beamwidth_deg,
    depth_metrics,
)


class LocalLipStudyTests(unittest.TestCase):
    def test_beamwidth_and_adjacent_complex_metrics(self) -> None:
        angles = np.arange(-90.0, 91.0)
        base = np.exp(-(angles / 30.0) ** 2).astype(np.complex128)
        changed = base * np.exp(1j * np.radians(2.0 * angles))

        def result(total: np.ndarray) -> LocalLipResult:
            cuts = {name: total.copy() for name in ("horizontal", "diagonal", "vertical")}
            incident = {name: base.copy() for name in cuts}
            scattered = {name: cuts[name] - incident[name] for name in cuts}
            return LocalLipResult(incident, scattered, cuts, 0, 10)

        left, right = result(base), result(changed)
        self.assertGreater(beamwidth_deg(angles, base), 0.0)
        row = adjacent_metrics(0.025, left, 0.05, right, angles)
        self.assertGreater(row["horizontal_complex_relative_l2"], 0.0)
        self.assertGreater(row["horizontal_complex_relative_l2"],
                           COMPLEX_RELATIVE_L2_LIMIT)
        self.assertAlmostEqual(row["horizontal_normalized_max_delta_db"], 0.0)
        self.assertAlmostEqual(row["horizontal_beamwidth_change_deg"], 0.0)
        depth = depth_metrics(0.025, left, angles)
        self.assertEqual(depth["retained_depth_mm"], 25.0)


if __name__ == "__main__":
    unittest.main()
