from __future__ import annotations

import unittest

import numpy as np

from app.tools.throat_impedance_diagnostics import throat_impedance_diagnostics


class ThroatImpedanceDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frequencies = np.geomspace(500.0, 8000.0, 193)

    def test_constant_impedance_is_ideal(self) -> None:
        result = throat_impedance_diagnostics(
            self.frequencies, np.ones_like(self.frequencies), 500.0)
        self.assertAlmostEqual(result["overall_percent"], 100.0, places=8)
        self.assertTrue(result["crossover"]["passes_target"])
        self.assertAlmostEqual(result["smoothness"]["ripple_rms_db"], 0.0)
        self.assertEqual(result["smoothness"]["reversal_count"], 0)
        self.assertAlmostEqual(result["shelf"]["lower_frequency_hz"], 2000.0)
        self.assertAlmostEqual(result["shelf"]["upper_frequency_hz"], 8000.0)

    def test_smooth_high_pass_shape_is_allowed(self) -> None:
        ratio = self.frequencies / 500.0
        magnitude = ratio / np.sqrt(1.0 + ratio ** 2)
        result = throat_impedance_diagnostics(
            self.frequencies, magnitude.astype(complex), 500.0)
        self.assertTrue(result["crossover"]["passes_target"])
        self.assertGreater(result["overall_percent"], 90.0)
        self.assertLess(result["smoothness"]["ripple_rms_db"], 0.05)

    def test_underloaded_crossover_is_penalized(self) -> None:
        ratio = self.frequencies / 500.0
        magnitude = ratio / (4.0 + ratio)
        result = throat_impedance_diagnostics(
            self.frequencies, magnitude, 500.0)
        self.assertFalse(result["crossover"]["passes_target"])
        self.assertLess(result["components"]["crossover_loading"], 70.0)

    def test_repeated_peaks_and_troughs_reduce_smoothness(self) -> None:
        ratio = self.frequencies / 500.0
        baseline = ratio / np.sqrt(1.0 + ratio ** 2)
        ripple_db = 3.0 * np.sin(2.0 * np.pi * 3.0 * np.log2(ratio))
        rippled = baseline * 10.0 ** (ripple_db / 20.0)
        smooth = throat_impedance_diagnostics(
            self.frequencies, baseline, 500.0)
        rough = throat_impedance_diagnostics(
            self.frequencies, rippled, 500.0)
        self.assertGreater(rough["smoothness"]["reversal_count"], 10)
        self.assertGreater(rough["smoothness"]["ripple_rms_db"], 1.0)
        self.assertLess(rough["overall_percent"], smooth["overall_percent"] - 20.0)

    def test_rejects_nonpositive_impedance_magnitude(self) -> None:
        with self.assertRaises(ValueError):
            throat_impedance_diagnostics(
                np.array([500.0, 1000.0, 2000.0]),
                np.array([1.0, 0.0, 1.0]), 500.0)


if __name__ == "__main__":
    unittest.main()
