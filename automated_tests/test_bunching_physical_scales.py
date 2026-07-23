from __future__ import annotations

import unittest

import numpy as np

from app.tools.analyze_bunching_physical_scales import (
    Observation, association_summary, curve_translation, find_bunching_peaks,
    find_bunching_troughs, physical_scales, spacing_association_summary,
)


class BunchingPhysicalScaleTests(unittest.TestCase):
    @staticmethod
    def observation(identifier: str, shift: float = 0.0) -> Observation:
        frequencies = 500 * 2 ** np.linspace(0, 4, 193)
        x = np.log2(frequencies / 2000) - shift
        curve = (np.exp(-0.5 * (x / 0.15) ** 2) -
                 0.6 * np.exp(-0.5 * ((x - 0.7) / 0.22) ** 2))
        return Observation(
            identifier=identifier, report=None, mouth_mm=300,
            coverage_deg=40, length_mm=100, k=4, n=8, s=1,
            frequencies_hz=frequencies, departure_db=curve,
            peaks=(), troughs=(), scales_mm={"osse_length": 100}, webster={})

    def test_peak_finder_localizes_broad_positive_departure(self) -> None:
        frequencies = 500 * 2 ** np.linspace(0, 4, 193)
        departure = np.exp(-0.5 * (np.log2(frequencies / 2000) / 0.12) ** 2)
        peaks = find_bunching_peaks(frequencies, departure)
        interior = [peak for peak in peaks if not peak["at_band_edge"]]
        self.assertEqual(len(interior), 1)
        self.assertAlmostEqual(interior[0]["frequency_hz"], 2000, delta=1)

    def test_trough_finder_localizes_broad_negative_departure(self) -> None:
        frequencies = 500 * 2 ** np.linspace(0, 4, 193)
        departure = -np.exp(-0.5 * (np.log2(frequencies / 3000) / 0.12) ** 2)
        troughs = find_bunching_troughs(frequencies, departure)
        interior = [trough for trough in troughs if not trough["at_band_edge"]]
        self.assertEqual(len(interior), 1)
        self.assertAlmostEqual(interior[0]["frequency_hz"], 3000, delta=25)
        self.assertLess(interior[0]["departure_db"], 0)

    def test_physical_scales_use_osse_length_and_finite_features(self) -> None:
        config = {
            "global": {"length": 120, "mouth_width": 300,
                       "throat_radius": 12.7, "throat_angle_deg": 6,
                       "conical_extension_length": 0},
            "horizontal_basis": {"coverage_deg": 40, "k": 4, "n": 8},
        }
        scales = physical_scales(config)
        self.assertEqual(scales["osse_length"], 120)
        self.assertEqual(scales["mouth_width"], 300)
        self.assertGreater(scales["wall_path_length"], 120)
        self.assertGreater(scales["termination_10_90_transition_length"], 0)
        self.assertGreater(scales["minimum_area_flare_length"], 0)
        self.assertGreater(scales["diameter_at_max_area_flare"], 0)
        self.assertGreater(scales["high_curvature_zone_length"], 0)
        self.assertTrue(all(np.isfinite(value) and value > 0 for value in scales.values()))

    def test_curve_translation_recovers_feature_shift(self) -> None:
        result = curve_translation(
            self.observation("lower"), self.observation("upper", shift=0.25))
        self.assertAlmostEqual(result["shift_octaves"], 0.25, delta=0.02)
        self.assertGreater(result["alignment_gain_fraction"], 0.8)
        self.assertFalse(result["at_search_boundary"])

    def test_inverse_scale_has_near_zero_collapse_error(self) -> None:
        observations = []
        for index, length in enumerate((80.0, 100.0, 125.0, 160.0)):
            frequency = 200000.0 / length
            observations.append(Observation(
                identifier=str(index), report=None, mouth_mm=300,
                coverage_deg=40, length_mm=length, k=4, n=8, s=1,
                frequencies_hz=np.asarray([frequency]),
                departure_db=np.asarray([1.0]),
                peaks=({"frequency_hz": frequency, "departure_db": 1.0,
                        "prominence_db": 1.0, "at_band_edge": False},),
                troughs=(),
                scales_mm={"controlled_scale": length,
                           "irrelevant_scale": 50 + index * 3},
                webster={},
            ))
        rows = {row["scale"]: row for row in association_summary(observations)}
        self.assertAlmostEqual(rows["controlled_scale"]["log2_dimensionless_mad"],
                               0.0, places=12)
        self.assertAlmostEqual(
            rows["controlled_scale"]["log_frequency_vs_log_length_slope"],
            -1.0, places=12)

    def test_linear_extremum_spacing_can_follow_inverse_length(self) -> None:
        observations = []
        for index, length in enumerate((80.0, 100.0, 125.0, 160.0)):
            spacing = 100000.0 / length
            peaks = tuple({
                "frequency_hz": 1000.0 + feature * spacing,
                "departure_db": 1.0,
                "prominence_db": 1.0,
                "at_band_edge": False,
            } for feature in (0, 1, 2))
            observations.append(Observation(
                identifier=str(index), report=None, mouth_mm=300,
                coverage_deg=40, length_mm=length, k=4, n=8, s=1,
                frequencies_hz=np.asarray([500.0, 8000.0]),
                departure_db=np.asarray([0.0, 0.0]), peaks=peaks, troughs=(),
                scales_mm={"controlled_scale": length},
                webster={},
            ))
        row = spacing_association_summary(observations, "peak_to_peak")[0]
        self.assertAlmostEqual(row["log2_dimensionless_mad"], 0.0, places=12)
        self.assertAlmostEqual(row["log_spacing_vs_log_length_slope"],
                               -1.0, places=12)


if __name__ == "__main__":
    unittest.main()
