from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

import numpy as np

from app.tools.interactive_results import (
    AIR_DENSITY_KG_M3, SOUND_SPEED_M_S, _frequency_axis,
    _frequency_grid_values, _heatmap_coloraxis, _positive_half_angle,
    _crossover_transition_weights, comparison_report, comparison_diagnostics,
    coverage_diagnostics, load_run, single_report,
)


ROOT = Path(__file__).resolve().parents[1]


class InteractiveResultsTests(unittest.TestCase):
    def test_heatmap_coloraxis_preserves_positive_db_values(self) -> None:
        coloraxis = _heatmap_coloraxis({
            "horizontal": np.array([[-30.0, 0.0, 1.2]]),
            "vertical": np.array([[-20.0, 0.0, 4.1]]),
        })

        self.assertEqual(coloraxis["cmin"], -30.0)
        self.assertEqual(coloraxis["cmax"], 5.0)
        self.assertEqual(coloraxis["colorscale"][-1][1], "#fff7f7")
        zero_stop = next(stop for stop in coloraxis["colorscale"]
                         if stop[1] == "#dc2626")
        self.assertLess(zero_stop[0], 1.0)

    def test_frequency_axis_uses_readable_major_ticks_and_minor_grid(self) -> None:
        axis = _frequency_axis(np.array([500.0, 8000.0]))
        self.assertEqual(axis["tickvals"],
                         [500.0, 1000.0, 2000.0, 5000.0, 8000.0])
        self.assertEqual(axis["ticktext"], ["500", "1k", "2k", "5k", "8k"])
        self.assertTrue(axis["minor"]["showgrid"])
        major, fine = _frequency_grid_values(np.array([500.0, 8000.0]))
        self.assertEqual(major, [500.0, 1000.0, 2000.0, 5000.0, 8000.0])
        self.assertIn(600.0, fine)
        self.assertIn(7000.0, fine)

    def make_run(self, root: Path, name: str) -> Path:
        run = root / name
        run.mkdir()
        yaml_path = run / "horn.yaml"
        yaml_path.write_text("""horncad_config:
  global: {length: 300, throat_radius: 12.7, throat_angle_deg: 6,
    conical_extension_length: 20, effective_throat_radius: 14.8,
    mouth_width: 400, mouth_height: 280, mouth_sag: 60}
  horizontal_basis: {coverage_deg: 50, k: 30, n: 10, solved_s: 0.18}
  vertical_basis: {coverage_deg: 35, k: 18, n: 10, solved_s: 0.17}
  section_modifier: {mouth_squareness: 0.72}
""")
        (run / "run_settings.json").write_text(json.dumps({"yaml_path": str(yaml_path)}))
        frequencies = np.array([500.0, 1000.0])
        angles = np.array([-90.0, -45.0, 0.0, 45.0, 90.0])
        levels = np.array([[-20, -8, 0, -8, -20], [-30, -12, 0, -12, -30]])
        np.savez_compressed(run / "responses.npz", frequencies_hz=frequencies,
                            angles_deg=angles, horizontal_db=levels,
                            vertical_db=levels - np.array([0, 2, 0, 2, 0]),
                            impedance=np.array([1 + 2j, 3 + 4j]))
        return run

    def test_loads_parameters_and_interpolates_half_angle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.make_run(Path(temp), "one")
            data = load_run(run)
            self.assertEqual(data["parameters"]["Coverage H / V"], "50° / 35°")
            self.assertEqual(data["parameters"]["Length-mouth ratio"], "1.33")
            reference = AIR_DENSITY_KG_M3 * SOUND_SPEED_M_S / (np.pi * 0.0148 ** 2)
            np.testing.assert_allclose(
                data["normalized_impedance"], np.array([1 + 2j, 3 + 4j]) / reference)
            self.assertEqual(data["intended_coverages"],
                             {"horizontal": 50.0, "vertical": 35.0})
            self.assertEqual(data["mouth_dimensions_mm"],
                             {"horizontal": 400.0, "vertical": 280.0})
            values = _positive_half_angle(data["angles"], data["horizontal"])
            np.testing.assert_allclose(values, [33.75, 22.5])

    def test_writes_single_and_four_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = [self.make_run(root, f"run-{index}") for index in range(4)]
            single = single_report(runs[0])
            fixed = single_report(
                runs[0], root / "fixed" / "report.html", "Fixed band",
                evaluation_frequencies=np.array([500.0, 1000.0]),
                fixed_band=True, name="Candidate A")
            compare = comparison_report(runs, root / "compare.html",
                                        ["A", "B", "C", "D"])
            single_text = single.read_text()
            fixed_text = fixed.read_text()
            fixed_diagnostics = json.loads(
                fixed.with_name("coverage_diagnostics.json").read_text())
            surface_diagnostics = json.loads(
                fixed.with_name("surface_diagnostics.json").read_text())
            self.assertIn("Horn acoustic parameters", single_text)
            self.assertIn("report-schema: canonical-v12", single_text)
            self.assertIn("Surface diagnostics", single_text)
            self.assertIn("Experimental throat-impedance diagnostic", single_text)
            self.assertIn("Throat-impedance score", single_text)
            self.assertTrue(
                (single.parent / "throat_impedance_diagnostics.json").is_file())
            self.assertIn("Coverage-window containment", single_text)
            self.assertIn("Angular slice-energy departure", single_text)
            self.assertIn("Best: 100%", single_text)
            self.assertGreaterEqual(single_text.count("Best: 0 dB"), 2)
            self.assertIn(r"Target: 1\u00d7", single_text)
            self.assertIn("Primary surface score v1", single_text)
            self.assertIn("Experimental surface score v2.2", single_text)
            self.assertIn("three-contour beamwidth quality", single_text)
            self.assertNotIn("1/3-oct", single_text)
            self.assertNotIn("Coverage Match", single_text)
            self.assertNotIn("Coverage Smoothness", single_text)
            self.assertNotIn("Waist Stability", single_text)
            self.assertNotIn("Window Uniformity", single_text)
            self.assertIn("<strong>Evaluated band:</strong> 500–1000 Hz",
                          fixed_text)
            self.assertEqual(fixed_diagnostics["Candidate A"]["band_kind"],
                             "fixed optimization")
            self.assertEqual(surface_diagnostics["Candidate A"]["band_kind"],
                             "fixed shadow evaluation")
            self.assertIn("--bg:#0c1014", single_text)
            self.assertIn('"template":', single_text)
            self.assertIn('"paper_bgcolor":"#121820"', single_text)
            self.assertIn("Click a chart to enable mouse-wheel zoom", single_text)
            self.assertIn('plot !== armed', single_text)
            self.assertIn('stopImmediatePropagation', single_text)
            # Plotly JSON escapes the Unicode minus sign in the trace names.
            self.assertIn("Horizontal \\u22123 dB", single_text)
            self.assertIn("Horizontal \\u22126 dB", single_text)
            self.assertIn("Horizontal \\u22129 dB", single_text)
            self.assertIn("Vertical \\u22126 dB", single_text)
            self.assertIn(r"Horizontal intended coverage \u00b150\u00b0", single_text)
            self.assertIn(r"Vertical intended coverage \u00b135\u00b0", single_text)
            self.assertIn('"coloraxis":"coloraxis"', single_text)
            self.assertIn('"orientation":"h"', single_text)
            self.assertIn('"layer":"above"', single_text)
            self.assertIn('"x0":600.0', single_text)
            self.assertGreaterEqual(single_text.count('"hoverinfo":"skip"'), 4)
            candidate_surface = surface_diagnostics["Candidate A"]
            self.assertEqual(candidate_surface["score"]["version"], "v1")
            self.assertEqual(candidate_surface["score_v1"]["version"], "v1")
            self.assertEqual(
                {"minus_3_db", "minus_6_db", "minus_9_db"},
                set(candidate_surface["horizontal"]["contours"]),
            )
            text = compare.read_text()
            self.assertIn("color-scheme:dark", text)
            self.assertIn("Normalized throat impedance magnitude", text)
            self.assertIn("Conical extension", text)
            self.assertIn("Surface diagnostics", text)
            self.assertIn("Experimental throat-impedance diagnostic", text)
            self.assertIn("<strong>Evaluated band:</strong>", text)
            self.assertIn("<h3>A</h3>", text)
            self.assertIn("<h3>D</h3>", text)
            self.assertLess(text.index("<th style='color:#2563eb'>A</th>"),
                            text.index("<th style='color:#dc2626'>B</th>"))

    def test_candidate_report_embeds_an_offline_stl_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = self.make_run(root, "run")
            candidate = root / "candidate-001"
            bem = candidate / "bem"
            bem.mkdir(parents=True)
            triangle = struct.pack(
                "<12fH",
                0, 0, 1,
                0, 0, 0,
                1, 0, 0,
                0, 1, 0,
                0,
            )
            (candidate / "test_Surface.STL").write_bytes(
                bytes(80) + struct.pack("<I", 1) + triangle)
            shutil.copy2(
                ROOT / "examples" / "mouth-size-coverage-grid" / "25deg" /
                "250x250" / "project.yaml",
                candidate / "project.yaml")

            report = single_report(run, bem / "test_Report.html")
            text = report.read_text()

        self.assertIn("<h2>Horn STL</h2>", text)
        self.assertIn("class='stl-canvas'", text)
        self.assertIn("Drag to orbit · wheel to zoom", text)
        self.assertIn("../test_Surface.STL", text)
        self.assertIn("new ResizeObserver(render)", text)
        self.assertIn("const ringCount = ", text)
        self.assertIn("const ringSize = ", text)
        self.assertIn("const ringStep = Math.max(1, Math.ceil(ringCount / 28))", text)
        self.assertIn("const columnStep = Math.max(1, Math.round(ringSize / 40))", text)
        self.assertIn("ctx.strokeStyle = 'rgba(77, 182, 168, 0.38)'", text)
        self.assertIn("ctx.stroke();", text)
        self.assertNotIn("ctx.fill();", text)

    def test_coverage_diagnostics_detects_passband_and_scores_planes(self) -> None:
        frequencies = 500.0 * 2 ** (np.arange(17) / 12)
        angles = np.arange(-90.0, 91.0)

        def patterns(half_angles: np.ndarray) -> np.ndarray:
            return np.asarray([-6 * (np.abs(angles) / half_angle) ** 2
                               for half_angle in half_angles])

        horizontal_angles = np.linspace(50, 40, len(frequencies))
        vertical_angles = np.linspace(35, 28, len(frequencies))
        run = {
            "frequencies": frequencies, "angles": angles,
            "horizontal": patterns(horizontal_angles),
            "vertical": patterns(vertical_angles),
            "intended_coverages": {"horizontal": 50.0, "vertical": 35.0},
        }
        result = coverage_diagnostics(run)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["passband_lower_hz"], 500.0)
        self.assertLess(result["combined"]["coverage_match_percent"], 90.0)
        self.assertGreater(result["combined"]["coverage_smoothness_percent"], 99.0)
        self.assertGreater(result["horizontal"]["weighted_undershoot_error_percent"],
                           result["horizontal"]["weighted_overshoot_error_percent"])
        self.assertAlmostEqual(result["horizontal"]["highest_frequency_error_deg"],
                               -10.0, delta=0.5)

    def test_diagnostics_separate_broad_error_and_fine_ripple(self) -> None:
        frequencies = np.geomspace(500.0, 5000.0, 81)
        angles = np.arange(-90.0, 91.0)
        x = np.log2(frequencies / 500.0)

        def patterns(half_angles: np.ndarray) -> np.ndarray:
            return np.asarray([-6 * (np.abs(angles) / half_angle) ** 2
                               for half_angle in half_angles])

        broad_waist = 50 - 10 * np.exp(-0.5 * ((x - 1.5) / 0.25) ** 2)
        fine_ripple = 50 + 3 * np.sin(2 * np.pi * x * 5)
        flat = np.full(len(frequencies), 50.0)
        bumpy = (
            50
            + 12 * np.exp(-0.5 * ((x - 2.2) / 0.25) ** 2)
            - 14 * np.exp(-0.5 * ((x - 2.8) / 0.22) ** 2)
        )
        base = {"frequencies": frequencies, "angles": angles,
                "vertical": patterns(np.full(len(frequencies), 35.0)),
                "intended_coverages": {"horizontal": 50.0, "vertical": 35.0},
                "crossover_hz": 500.0}
        waist = coverage_diagnostics(dict(base, horizontal=patterns(broad_waist)))
        ripple = coverage_diagnostics(dict(base, horizontal=patterns(fine_ripple)))
        no_waist = coverage_diagnostics(dict(base, horizontal=patterns(flat)))
        rough = coverage_diagnostics(dict(base, horizontal=patterns(bumpy)))
        self.assertLess(waist["horizontal"]["coverage_match_percent"],
                        ripple["horizontal"]["coverage_match_percent"])
        self.assertGreater(waist["horizontal"]["coverage_smoothness_percent"],
                           ripple["horizontal"]["coverage_smoothness_percent"])
        self.assertGreater(waist["horizontal"]["worst_broad_undershoot_deg"], 8.0)
        self.assertTrue(waist["horizontal"]["waist_detected"])
        self.assertLess(waist["horizontal"]["waist_stability_percent"], 85.0)
        self.assertGreater(waist["horizontal"]["waistbanding_error_percent"], 15.0)
        self.assertAlmostEqual(waist["horizontal"]["waist_region_octaves"],
                               2.0, places=6)
        self.assertFalse(no_waist["horizontal"]["waist_detected"])
        self.assertEqual(no_waist["horizontal"]["waist_stability_percent"], 100.0)
        self.assertGreater(ripple["horizontal"]["ripple_rms_deg"], 1.5)
        self.assertLess(rough["horizontal"]["coverage_smoothness_percent"], 85.0)
        self.assertGreater(rough["horizontal"]["broad_wiggle_error_percent"], 4.0)
        self.assertGreater(rough["horizontal"]["smoothness_score_gain"], 3.0)

    def test_coverage_match_integrates_error_with_crossover_weighting(self) -> None:
        crossover = 750.0
        frequencies = np.geomspace(crossover, 8000.0, 129)
        angles = np.arange(-90.0, 91.0)
        x = np.log2(frequencies / crossover)
        target = 45.0

        def patterns(half_angles: np.ndarray) -> np.ndarray:
            return np.asarray([-6 * (np.abs(angles) / half_angle) ** 2
                               for half_angle in half_angles])

        weights = _crossover_transition_weights(
            np.array([crossover, crossover * 2 ** 0.5, crossover * 2]),
            crossover)
        self.assertAlmostEqual(weights[0], 10 ** (-6 / 20), places=6)
        self.assertAlmostEqual(weights[1], 1.0, places=6)
        self.assertAlmostEqual(weights[2], 1.0, places=6)

        broad_then_lock = np.where(x < 0.5, 65.0, target)
        narrow_then_lock = np.where(x < 0.5, 25.0, target)
        broad_after_transition = np.where((x >= 1.0) & (x < 1.5), 65.0, target)
        base = {"frequencies": frequencies, "angles": angles,
                "intended_coverages": {"horizontal": target, "vertical": target},
                "crossover_hz": crossover}
        broad = coverage_diagnostics(
            dict(base, horizontal=patterns(broad_then_lock),
                 vertical=patterns(broad_then_lock)))
        narrow = coverage_diagnostics(
            dict(base, horizontal=patterns(narrow_then_lock),
                 vertical=patterns(narrow_then_lock)))
        late = coverage_diagnostics(
            dict(base, horizontal=patterns(broad_after_transition),
                 vertical=patterns(broad_after_transition)))
        self.assertAlmostEqual(
            broad["horizontal"]["weighted_overshoot_error_percent"],
            narrow["horizontal"]["weighted_undershoot_error_percent"], delta=0.5)
        self.assertGreater(broad["horizontal"]["coverage_match_percent"],
                           late["horizontal"]["coverage_match_percent"])
        self.assertGreater(narrow["horizontal"]["coverage_match_percent"],
                           late["horizontal"]["coverage_match_percent"])
        self.assertAlmostEqual(
            broad["horizontal"]["transition_weight_at_crossover"],
            10 ** (-6 / 20), places=6)
        self.assertAlmostEqual(
            broad["horizontal"]["transition_full_weight_hz"],
            crossover * 2 ** 0.5, places=6)

    def test_coverage_match_records_high_frequency_endpoint_loss(self) -> None:
        frequencies = np.geomspace(750.0, 8000.0, 129)
        angles = np.arange(-90.0, 91.0)
        target = 45.0
        x = np.log2(frequencies / frequencies[0])

        def patterns(half_angles: np.ndarray) -> np.ndarray:
            return np.asarray([-6 * (np.abs(angles) / half_angle) ** 2
                               for half_angle in half_angles])

        flat = np.full(len(frequencies), target)
        late_narrowing = np.where(x < 2.0, target, target - 8.0 * (x - 2.0))
        late_narrowing = np.maximum(late_narrowing, 30.0)
        run = {"frequencies": frequencies, "angles": angles,
               "intended_coverages": {"horizontal": target, "vertical": target},
               "crossover_hz": frequencies[0]}
        flat_result = coverage_diagnostics(
            dict(run, horizontal=patterns(flat), vertical=patterns(flat)))
        narrowing_result = coverage_diagnostics(
            dict(run, horizontal=patterns(late_narrowing),
                 vertical=patterns(late_narrowing)))
        self.assertGreater(flat_result["horizontal"]["coverage_match_percent"], 99.0)
        self.assertLess(narrowing_result["horizontal"]["coverage_match_percent"],
                        flat_result["horizontal"]["coverage_match_percent"])
        self.assertLess(narrowing_result["horizontal"]["highest_frequency_error_deg"], 0)
        self.assertGreater(narrowing_result["horizontal"]["highest_frequency_undershoot_deg"],
                           0)

    def test_window_uniformity_scores_in_window_level_variation(self) -> None:
        frequencies = np.geomspace(750.0, 8000.0, 129)
        angles = np.arange(-90.0, 91.0)
        target = 45.0
        probe = target * 0.5
        x = np.log2(frequencies / frequencies[0])
        angle_window = np.exp(-0.5 * ((np.abs(angles) - probe) / 3.0) ** 2)
        base_pattern = -6 * (np.abs(angles) / target) ** 2

        def patterns(amplitude: np.ndarray) -> np.ndarray:
            return base_pattern[None, :] + amplitude[:, None] * angle_window[None, :]

        flat = np.zeros(len(frequencies))
        broad = -3.0 * np.exp(-0.5 * ((x - 2.0) / 0.45) ** 2)
        narrow = -3.0 * np.exp(-0.5 * ((x - 2.0) / 0.05) ** 2)
        base = {"frequencies": frequencies, "angles": angles,
                "intended_coverages": {"horizontal": target, "vertical": target},
                "crossover_hz": frequencies[0]}
        flat_result = coverage_diagnostics(
            dict(base, horizontal=patterns(flat), vertical=patterns(flat)))
        broad_result = coverage_diagnostics(
            dict(base, horizontal=patterns(broad), vertical=patterns(broad)))
        narrow_result = coverage_diagnostics(
            dict(base, horizontal=patterns(narrow), vertical=patterns(narrow)))
        broad_rms = broad_result["horizontal"]["window_rms_deviation_db"]
        self.assertAlmostEqual(
            flat_result["horizontal"]["window_probe_angle_deg"], probe)
        self.assertGreater(flat_result["combined"]["window_uniformity_percent"], 99.0)
        self.assertEqual(broad_result["horizontal"]["window_positive_rms_db"], 0.0)
        self.assertGreater(broad_rms, narrow_result["horizontal"]["window_rms_deviation_db"])
        self.assertLess(broad_result["horizontal"]["window_uniformity_percent"],
                        narrow_result["horizontal"]["window_uniformity_percent"])
        self.assertAlmostEqual(
            broad_result["horizontal"]["window_uniformity_percent"],
            100.0 - 10.0 * broad_rms, places=6)

    def test_window_uniformity_penalizes_positive_off_axis_zones(self) -> None:
        frequencies = np.geomspace(750.0, 8000.0, 129)
        angles = np.arange(-90.0, 91.0)
        target = 45.0
        probe = target * 0.5
        angle_window = np.exp(-0.5 * ((np.abs(angles) - probe) / 3.0) ** 2)
        base_pattern = -6 * (np.abs(angles) / target) ** 2
        positive_bump = np.tile(base_pattern + 2.0 * angle_window,
                                (len(frequencies), 1))
        clean = np.tile(base_pattern, (len(frequencies), 1))
        base = {"frequencies": frequencies, "angles": angles,
                "intended_coverages": {"horizontal": target, "vertical": target},
                "crossover_hz": frequencies[0]}
        clean_result = coverage_diagnostics(
            dict(base, horizontal=clean, vertical=clean))
        positive_result = coverage_diagnostics(
            dict(base, horizontal=positive_bump, vertical=positive_bump))
        positive_rms = positive_result["horizontal"]["window_positive_rms_db"]
        self.assertGreater(clean_result["combined"]["window_uniformity_percent"], 99.0)
        self.assertGreater(positive_rms, 0.4)
        self.assertGreater(
            positive_result["horizontal"]["window_positive_peak_db"], 0.4)
        self.assertGreater(
            positive_result["horizontal"]["window_positive_band_fraction"], 0.99)
        self.assertLess(positive_result["horizontal"]["window_uniformity_percent"],
                        clean_result["horizontal"]["window_uniformity_percent"])
        self.assertAlmostEqual(
            positive_result["horizontal"]["window_uniformity_percent"],
            100.0
            - 10.0 * positive_result["horizontal"]["window_rms_deviation_db"]
            - 20.0 * positive_rms,
            places=6)

    def test_combined_scores_follow_mouth_dimension_weights(self) -> None:
        frequencies = np.array([500.0, 1000.0])
        angles = np.arange(-90.0, 91.0)
        horizontal = np.asarray([-6 * (np.abs(angles) / 50) ** 2] * 2)
        vertical = np.asarray([-6 * (np.abs(angles) / 17.5) ** 2] * 2)
        run = {"frequencies": frequencies, "angles": angles,
               "horizontal": horizontal, "vertical": vertical,
               "intended_coverages": {"horizontal": 50.0, "vertical": 35.0},
               "mouth_dimensions_mm": {"horizontal": 400.0, "vertical": 280.0}}
        result = coverage_diagnostics(run)
        self.assertAlmostEqual(result["axis_weights"]["horizontal"], 400 / 680)
        expected_error = np.sqrt((280 / 680) * 50 ** 2)
        self.assertAlmostEqual(result["combined"]["coverage_match_percent"],
                               100 - expected_error, delta=0.5)

    def test_fixed_band_penalizes_missing_crossings(self) -> None:
        frequencies = np.array([500.0, 1000.0, 2000.0])
        angles = np.arange(-90.0, 91.0)
        levels = np.zeros((len(frequencies), len(angles)))
        run = {"frequencies": frequencies, "angles": angles,
               "horizontal": levels, "vertical": levels,
               "intended_coverages": {"horizontal": 50.0, "vertical": 35.0}}
        result = coverage_diagnostics(run, frequencies, fixed_band=True)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["band_kind"], "fixed optimization")
        self.assertLess(result["combined"]["coverage_match_percent"], 20.0)

    def test_comparison_diagnostics_use_one_grid_and_common_band(self) -> None:
        frequencies_a = 500.0 * 2 ** (np.arange(25) / 12)
        frequencies_b = 700.0 * 2 ** (np.arange(18) / 10)
        angles = np.arange(-90.0, 91.0)

        def run(frequencies: np.ndarray, name: str) -> dict[str, object]:
            half = 50 - 5 * np.log2(frequencies / frequencies[0])
            levels = np.asarray([-6 * (np.abs(angles) / value) ** 2 for value in half])
            return {"name": name, "frequencies": frequencies, "angles": angles,
                    "horizontal": levels, "vertical": levels,
                    "intended_coverages": {"horizontal": 50.0, "vertical": 50.0}}

        diagnostics, grid = comparison_diagnostics(
            [run(frequencies_a, "A"), run(frequencies_b, "B")])
        self.assertEqual(diagnostics["A"]["passband_lower_hz"], grid[0])
        self.assertEqual(diagnostics["B"]["passband_lower_hz"], grid[0])
        self.assertEqual(diagnostics["A"]["passband_upper_hz"], grid[-1])
        self.assertEqual(diagnostics["B"]["passband_upper_hz"], grid[-1])
        self.assertEqual(diagnostics["A"]["band_kind"], "common comparison")


if __name__ == "__main__":
    unittest.main()
