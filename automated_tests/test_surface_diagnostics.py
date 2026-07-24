from __future__ import annotations

import unittest

import numpy as np

from app.tools.surface_diagnostics import (
    ACTIVE_SURFACE_SCORE_V2_CANDIDATE,
    ACTIVE_SURFACE_SCORE_VERSION,
    NARROW_COVERAGE_MINIMUM_V2_FRACTION,
    SURFACE_SCORE_WEIGHTS,
    surface_diagnostics,
    surface_score,
    surface_score_v1,
    surface_score_v2,
)


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

    def width_trace_surface(
        self, normalized_width: np.ndarray, coverage: float = 30.0,
        angle_count: int = 181,
    ) -> np.ndarray:
        angles = np.linspace(0.0, 90.0, angle_count)
        return np.asarray([
            -6.0 * angles / (coverage * width)
            for width in normalized_width
        ])

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
        self.assertIsNotNone(result["score"])

    def test_final_score_uses_fixed_weights_and_penalizes_surface_errors(self) -> None:
        ideal = surface_diagnostics(self.make_run(self.ideal_surface()))
        damaged_surface = self.ideal_surface()
        angles = np.linspace(0.0, 90.0, damaged_surface.shape[1])
        damaged_surface += 5.0 * np.sin(angles * np.pi / 4.0)[None, :]
        damaged = surface_diagnostics(self.make_run(damaged_surface))

        self.assertAlmostEqual(sum(SURFACE_SCORE_WEIGHTS.values()), 1.0)
        self.assertGreater(
            surface_score(ideal)["overall_percent"],
            surface_score(damaged)["overall_percent"])
        self.assertEqual(
            surface_score(ideal, {"horizontal": 2, "vertical": 1})["axis_weights"],
            {"horizontal": 2 / 3, "vertical": 1 / 3})

    def test_v1_is_preserved_and_v2_candidates_are_reported(self) -> None:
        result = surface_diagnostics(self.make_run(self.ideal_surface()))
        self.assertEqual("v1", result["score"]["version"])
        self.assertEqual(ACTIVE_SURFACE_SCORE_VERSION, result["score"]["version"])
        self.assertEqual("v1", surface_score_v1(result)["version"])
        experimental = surface_score_v2(
            result, candidate_name=ACTIVE_SURFACE_SCORE_V2_CANDIDATE
        )
        self.assertEqual("v2.2", experimental["version"])
        self.assertEqual(
            ACTIVE_SURFACE_SCORE_V2_CANDIDATE,
            experimental["candidate_name"],
        )
        self.assertEqual(
            {"conservative", "balanced", "smoothness", "contour_forward"},
            set(result["score_v2_candidates"]),
        )

    def test_v2_narrow_coverage_restores_target_adherence(self) -> None:
        result = surface_diagnostics(
            self.make_run(self.ideal_surface(coverage=25.0), coverage=25.0)
        )
        plane = result["score_v2_candidates"]["contour_forward"]["horizontal"]
        self.assertAlmostEqual(
            NARROW_COVERAGE_MINIMUM_V2_FRACTION,
            plane["v2_fraction"],
        )
        self.assertAlmostEqual(
            0.08, plane["component_weights"]["beamwidth_quality"]
        )
        self.assertAlmostEqual(
            0.08, plane["component_weights"]["minus_six_line"]
        )

    def test_v2_2_coverage_adaptation_rises_smoothly(self) -> None:
        result = surface_diagnostics(self.make_run(self.ideal_surface()))
        plane = result["score_v2_candidates"]["contour_forward"]["horizontal"]
        self.assertAlmostEqual(0.218, plane["v2_fraction"])
        self.assertAlmostEqual(
            0.0872, plane["component_weights"]["beamwidth_quality"]
        )
        self.assertAlmostEqual(
            0.0782, plane["component_weights"]["minus_six_line"]
        )

    def test_v2_1_remains_reproducible(self) -> None:
        result = surface_diagnostics(self.make_run(self.ideal_surface()))
        prior = surface_score_v2(
            result,
            candidate_name="contour_forward",
            revision="v2.1",
        )
        self.assertEqual("v2.1", prior["version"])
        self.assertAlmostEqual(1.0, prior["horizontal"]["v2_fraction"])
        self.assertFalse(prior["coverage_adaptation"]["enabled"])

    def test_original_v2_remains_reproducible(self) -> None:
        result = surface_diagnostics(
            self.make_run(self.ideal_surface(coverage=25.0), coverage=25.0)
        )
        original = surface_score_v2(
            result,
            candidate_name="contour_forward",
            adapt_narrow_coverage=False,
        )
        self.assertEqual("v2", original["version"])
        self.assertAlmostEqual(1.0, original["horizontal"]["v2_fraction"])
        self.assertFalse(original["narrow_coverage_adaptation"]["enabled"])

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

    def test_smooth_global_narrowing_beats_equal_scale_ripple(self) -> None:
        x = np.linspace(0.0, 1.0, 49)
        smooth = self.width_trace_surface(1.10 - 0.20 * x)
        ripple = self.width_trace_surface(1.0 + 0.10 * np.sin(8 * np.pi * x))
        smooth_result = surface_diagnostics(self.make_run(smooth))["horizontal"]
        ripple_result = surface_diagnostics(self.make_run(ripple))["horizontal"]
        self.assertGreater(
            smooth_result["beamwidth_quality"]["overall_percent"],
            ripple_result["beamwidth_quality"]["overall_percent"],
        )
        self.assertLess(
            smooth_result["contours"]["minus_6_db"][
                "trend_complexity_fraction_per_octave"
            ],
            ripple_result["contours"]["minus_6_db"][
                "trend_complexity_fraction_per_octave"
            ],
        )

    def test_local_narrowing_is_penalized_more_than_local_widening(self) -> None:
        x = np.linspace(-1.0, 1.0, 49)
        disturbance = 0.12 * np.exp(-0.5 * (x / 0.12) ** 2)
        narrow = surface_diagnostics(self.make_run(
            self.width_trace_surface(1.0 - disturbance)
        ))["horizontal"]
        wide = surface_diagnostics(self.make_run(
            self.width_trace_surface(1.0 + disturbance)
        ))["horizontal"]
        narrow_line = narrow["contours"]["minus_6_db"]
        wide_line = wide["contours"]["minus_6_db"]
        self.assertGreater(
            narrow_line["local_narrowing_fraction"],
            wide_line["local_narrowing_fraction"],
        )
        self.assertLess(
            narrow_line["overall_percent"],
            wide_line["overall_percent"],
        )

    def test_fine_and_broad_ripples_are_detected(self) -> None:
        x = np.linspace(0.0, 1.0, 49)
        ideal_score = surface_diagnostics(
            self.make_run(self.width_trace_surface(np.ones(49)))
        )["horizontal"]["beamwidth_quality"]["overall_percent"]
        fine_score = surface_diagnostics(self.make_run(
            self.width_trace_surface(1.0 + 0.08 * np.sin(12 * np.pi * x))
        ))["horizontal"]["beamwidth_quality"]["overall_percent"]
        broad_score = surface_diagnostics(self.make_run(
            self.width_trace_surface(1.0 + 0.08 * np.sin(2 * np.pi * x))
        ))["horizontal"]["beamwidth_quality"]["overall_percent"]
        self.assertLess(fine_score, ideal_score)
        self.assertLess(broad_score, ideal_score)

    def test_shoulder_contours_contribute_independently(self) -> None:
        surface = self.ideal_surface()
        angles = np.linspace(0.0, 90.0, surface.shape[1])
        frequency_shape = np.exp(
            -0.5 * ((np.arange(surface.shape[0]) - 24) / 2.0) ** 2
        )
        shoulder_shape = (
            np.exp(-0.5 * ((angles - 15.0) / 3.0) ** 2)
            - np.exp(-0.5 * ((angles - 45.0) / 4.0) ** 2)
        )
        damaged = surface + 2.0 * frequency_shape[:, None] * shoulder_shape[None, :]
        result = surface_diagnostics(self.make_run(damaged))["horizontal"]
        self.assertLess(
            result["contours"]["minus_3_db"]["overall_percent"], 100.0
        )
        self.assertLess(
            result["contours"]["minus_9_db"]["overall_percent"], 100.0
        )
        self.assertLess(result["beamwidth_quality"]["overall_percent"], 100.0)

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

    def test_beamwidth_score_is_stable_under_frequency_and_angle_resampling(self) -> None:
        frequencies = np.geomspace(500.0, 8000.0, 49)
        x = np.linspace(0.0, 1.0, len(frequencies))
        widths = 1.0 + 0.05 * np.sin(4 * np.pi * x)
        full_surface = self.width_trace_surface(widths)
        full_run = self.make_run(full_surface)
        full = surface_diagnostics(full_run)["horizontal"][
            "beamwidth_quality"
        ]["overall_percent"]

        decimated_run = dict(full_run)
        for key in ("frequencies", "horizontal", "vertical"):
            decimated_run[key] = np.asarray(full_run[key])[::2]
        decimated = surface_diagnostics(decimated_run)["horizontal"][
            "beamwidth_quality"
        ]["overall_percent"]

        coarse_surface = self.width_trace_surface(widths, angle_count=91)
        coarse = surface_diagnostics(self.make_run(coarse_surface))["horizontal"][
            "beamwidth_quality"
        ]["overall_percent"]
        self.assertAlmostEqual(full, decimated, delta=0.6)
        self.assertAlmostEqual(full, coarse, delta=0.1)

    def test_missing_contour_caps_beamwidth_quality(self) -> None:
        surface = np.maximum(self.ideal_surface(), -2.0)
        plane = surface_diagnostics(self.make_run(surface))["horizontal"]
        self.assertEqual(
            plane["contours"]["minus_3_db"]["overall_percent"], 0.0
        )
        self.assertEqual(plane["beamwidth_quality"]["overall_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
