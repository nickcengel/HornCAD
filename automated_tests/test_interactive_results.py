from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.tools.interactive_results import (
    AIR_DENSITY_KG_M3, SOUND_SPEED_M_S, _frequency_axis,
    _frequency_grid_values, _positive_half_angle, comparison_report,
    comparison_diagnostics, coverage_diagnostics, load_run, single_report,
)


class InteractiveResultsTests(unittest.TestCase):
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
            reference = AIR_DENSITY_KG_M3 * SOUND_SPEED_M_S / (np.pi * 0.0148 ** 2)
            np.testing.assert_allclose(
                data["normalized_impedance"], np.array([1 + 2j, 3 + 4j]) / reference)
            self.assertEqual(data["intended_coverages"],
                             {"horizontal": 50.0, "vertical": 35.0})
            values = _positive_half_angle(data["angles"], data["horizontal"])
            np.testing.assert_allclose(values, [33.75, 22.5])

    def test_writes_single_and_four_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = [self.make_run(root, f"run-{index}") for index in range(4)]
            single = single_report(runs[0])
            compare = comparison_report(runs, root / "compare.html",
                                        ["A", "B", "C", "D"])
            single_text = single.read_text()
            self.assertIn("Horn acoustic parameters", single_text)
            self.assertIn("Coverage diagnostics", single_text)
            # Plotly JSON escapes the Unicode minus sign in the trace names.
            self.assertIn("Horizontal \\u22126 dB", single_text)
            self.assertIn("Vertical \\u22126 dB", single_text)
            self.assertIn(r"Horizontal intended coverage \u00b150\u00b0", single_text)
            self.assertIn(r"Vertical intended coverage \u00b135\u00b0", single_text)
            self.assertIn('"coloraxis":"coloraxis"', single_text)
            self.assertIn('"orientation":"h"', single_text)
            self.assertIn('"layer":"above"', single_text)
            self.assertIn('"x0":600.0', single_text)
            self.assertGreaterEqual(single_text.count('"hoverinfo":"skip"'), 4)
            text = compare.read_text()
            self.assertIn("Normalized throat impedance magnitude", text)
            self.assertIn("Conical extension", text)
            self.assertIn("Common evaluated band", text)
            self.assertIn("<h3>Combined</h3>", text)
            self.assertIn("<h3>Horizontal</h3>", text)
            self.assertIn("<h3>Vertical</h3>", text)
            self.assertLess(text.index("<th style='color:#2563eb'>A</th>"),
                            text.index("<th style='color:#dc2626'>B</th>"))

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
        self.assertGreater(result["combined"]["smoothness_percent"], 99.0)
        self.assertAlmostEqual(result["horizontal"]["non_narrowing_percent"], 80.0,
                               delta=0.2)
        self.assertAlmostEqual(result["horizontal"]["coverage_match_percent"],
                               88.4, delta=0.5)
        self.assertAlmostEqual(result["horizontal"]["narrowing_percent"], 20.0,
                               delta=0.2)
        self.assertAlmostEqual(result["vertical"]["narrowing_percent"], 20.0,
                               delta=0.2)

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
