from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.interactive_results import (
    _positive_half_angle, comparison_report, load_run, single_report,
)


class InteractiveResultsTests(unittest.TestCase):
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
            values = _positive_half_angle(data["angles"], data["horizontal"])
            np.testing.assert_allclose(values, [33.75, 22.5])

    def test_writes_single_and_four_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = [self.make_run(root, f"run-{index}") for index in range(4)]
            single = single_report(runs[0])
            compare = comparison_report(runs, root / "compare.html",
                                        ["A", "B", "C", "D"])
            self.assertIn("Horn acoustic parameters", single.read_text())
            text = compare.read_text()
            self.assertIn("Throat impedance magnitude", text)
            self.assertIn("Conical extension", text)


if __name__ == "__main__":
    unittest.main()
