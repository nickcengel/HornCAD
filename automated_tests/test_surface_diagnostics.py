from __future__ import annotations

import unittest

import numpy as np

from app.tools.surface_diagnostics import surface_diagnostics


class SurfaceDiagnosticsTests(unittest.TestCase):
    def make_run(self, horizontal: np.ndarray, vertical: np.ndarray | None = None,
                 coverage: float = 30.0) -> dict:
        frequencies = np.geomspace(500.0, 8000.0, horizontal.shape[0])
        angles = np.linspace(0.0, 90.0, horizontal.shape[1])
        return {
            "frequencies": frequencies,
            "angles": angles,
            "horizontal": horizontal,
            "vertical": horizontal if vertical is None else vertical,
            "intended_coverages": {
                "horizontal": coverage,
                "vertical": coverage,
            },
            "crossover_hz": 500.0,
        }

    def ideal_surface(self, frequency_count: int = 49,
                      angle_count: int = 181, coverage: float = 30.0) -> np.ndarray:
        angles = np.linspace(0.0, 90.0, angle_count)
        row = -6.0 * angles / coverage
        return np.tile(row, (frequency_count, 1))

    def test_ideal_surface_has_stable_energy_and_zero_profile_error(self) -> None:
        result = surface_diagnostics(self.make_run(self.ideal_surface()))
        plane = result["horizontal"]
        self.assertEqual(result["status"], "available")
        self.assertAlmostEqual(plane["distribution"]["rms_profile_error_db"], 0.0,
                               places=10)
        self.assertAlmostEqual(
            plane["distribution"]["rms_outward_rise_violation_db"], 0.0,
            places=10)
        self.assertAlmostEqual(
            plane["slice_energy_stability"]["rms_departure_db"], 0.0,
            places=10)
        self.assertAlmostEqual(
            plane["minus_six_line"]["rms_coverage_error_deg"], 0.0,
            places=10)

    def test_outside_lobe_reduces_containment(self) -> None:
        ideal = self.ideal_surface()
        lobe = ideal.copy()
        angles = np.linspace(0.0, 90.0, lobe.shape[1])
        lobe[:, (angles >= 50) & (angles <= 60)] = -1.0
        ideal_result = surface_diagnostics(self.make_run(ideal))["horizontal"]
        lobe_result = surface_diagnostics(self.make_run(lobe))["horizontal"]
        self.assertLess(lobe_result["containment"]["mean_fraction"],
                        ideal_result["containment"]["mean_fraction"])

    def test_in_window_ripple_increases_distribution_and_rise_errors(self) -> None:
        ideal = self.ideal_surface()
        angles = np.linspace(0.0, 90.0, ideal.shape[1])
        ripple = ideal + 2.0 * np.sin(angles * np.pi / 3.0)[None, :]
        result = surface_diagnostics(self.make_run(ripple))["horizontal"]
        self.assertGreater(result["distribution"]["rms_profile_error_db"], 1.0)
        self.assertGreater(
            result["distribution"]["rms_outward_rise_violation_db"], 0.0)

    def test_frequency_bunching_is_localized_by_slice_energy_metric(self) -> None:
        surface = self.ideal_surface()
        angles = np.linspace(0.0, 90.0, surface.shape[1])
        shape = np.exp(-0.5 * ((angles - 45.0) / 12.0) ** 2)
        surface[24] += 12.0 * shape
        result = surface_diagnostics(self.make_run(surface))["horizontal"]
        stability = result["slice_energy_stability"]
        self.assertGreater(stability["peak_to_peak_db"], 1.0)
        self.assertAlmostEqual(stability["highest_departure_frequency_hz"],
                               np.geomspace(500.0, 8000.0, 49)[24])
        self.assertGreater(
            stability["multiscale_rms_departure_db"]["raw"],
            stability["multiscale_rms_departure_db"]["2/3 octave"])

    def test_missing_minus_six_crossings_are_reported(self) -> None:
        surface = self.ideal_surface()
        surface[10] = np.maximum(surface[10], -5.0)
        result = surface_diagnostics(self.make_run(surface))["horizontal"]
        self.assertAlmostEqual(result["minus_six_line"]["missing_fraction"], 1 / 49)

    def test_frequency_decimation_preserves_broad_metrics(self) -> None:
        surface = self.ideal_surface()
        angles = np.linspace(0.0, 90.0, surface.shape[1])
        frequencies = np.geomspace(500.0, 8000.0, surface.shape[0])
        surface += (1.5 * np.sin(np.log2(frequencies / 500.0) * np.pi / 2)
                    [:, None] * (angles / 90.0)[None, :])
        full_run = self.make_run(surface)
        full = surface_diagnostics(full_run)["horizontal"]
        decimated_run = dict(full_run)
        for key in ("frequencies", "horizontal", "vertical"):
            decimated_run[key] = np.asarray(full_run[key])[::2]
        decimated = surface_diagnostics(decimated_run)["horizontal"]
        self.assertAlmostEqual(full["containment"]["mean_fraction"],
                               decimated["containment"]["mean_fraction"], places=3)
        self.assertAlmostEqual(
            full["slice_energy_stability"]["rms_departure_db"],
            decimated["slice_energy_stability"]["rms_departure_db"], places=2)


if __name__ == "__main__":
    unittest.main()
