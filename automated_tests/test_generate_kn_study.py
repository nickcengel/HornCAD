from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from app.tools.generate_kn_study import KN_POINTS, generate_all, materialize_kn_search


ROOT = Path(__file__).resolve().parents[1]


class GenerateKNStudyTests(unittest.TestCase):
    def test_bulk_generation_requires_s_boundary_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "must be bracketed"):
                generate_all(Path(temp))

    def test_materializes_local_cross_and_interactions(self) -> None:
        source_dir = (ROOT / "examples" / "mouth-size-coverage-grid" /
                      "45deg" / "350x350")
        source_project = source_dir / "project.yaml"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "350x350-kn-grid"
            materialize_kn_search(source_project, source_dir / "search.yaml", output)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]

        self.assertEqual(search["max_evaluations"], 80)
        self.assertTrue(search["adaptive_kn"]["enabled"])
        self.assertTrue(search["adaptive_kn_closure"]["enabled"])
        points = [(item["values"]["k_h"], item["values"]["n_h"])
                  for item in search["initial_pool"]]
        self.assertEqual(points, [(float(k), float(n)) for k, n in KN_POINTS])
        self.assertNotIn((4.0, 2.0), points)
        self.assertNotIn((4.0, 20.0), points)
        self.assertEqual(search["bounds"]["k_h"], [1.0, 7.000001])
        self.assertEqual(search["bounds"]["n_h"], [2.0, 40.000001])


if __name__ == "__main__":
    unittest.main()
