import math
import unittest

from app.tools.export_horncad import termination_metrics


class TerminationMetricsTests(unittest.TestCase):
    def test_metrics_are_finite_and_high_n_increases_realized_roundover(self) -> None:
        low = termination_metrics(300, 25, 50, 30, 2, 200, 5)
        high = termination_metrics(300, 25, 50, 30, 10, 200, 5)
        for metrics in (low, high):
            self.assertTrue(all(math.isfinite(value) for value in metrics.values()))
            self.assertGreater(metrics["curvature_radius_mm"], 0)
            self.assertGreater(metrics["normalized_curvature_radius"], 0)
        self.assertGreater(high["curvature_radius_mm"], low["curvature_radius_mm"])
        self.assertGreater(high["exit_angle_deg"], low["exit_angle_deg"])

    def test_horizontal_and_vertical_use_the_same_measurement(self) -> None:
        first = termination_metrics(300, 25, 45, 25, 4, 150, 5)
        second = termination_metrics(300, 25, 45, 25, 4, 150, 5)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
