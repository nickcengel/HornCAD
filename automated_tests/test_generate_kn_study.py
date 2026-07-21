from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from app.tools.generate_kn_study import KN_POINTS, materialize_kn_search


ROOT = Path(__file__).resolve().parents[1]


class GenerateKNStudyTests(unittest.TestCase):
    def test_materializes_local_cross_extremes_and_interactions(self) -> None:
        source_dir = (ROOT / "examples" / "mouth-size-coverage-grid" /
                      "45deg" / "350x350")
        source_project = source_dir / "project.yaml"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "350x350-kn-grid"
            materialize_kn_search(source_project, source_dir / "search.yaml", output)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]

        self.assertEqual(search["max_evaluations"], 13)
        self.assertTrue(search["adaptive_kn"]["enabled"])
        points = [(item["values"]["k_h"], item["values"]["n_h"])
                  for item in search["initial_pool"]]
        self.assertEqual(points, [(float(k), float(n)) for k, n in KN_POINTS])
        self.assertEqual(search["bounds"]["k_h"], [3.0, 5.000001])
        self.assertEqual(search["bounds"]["n_h"], [2.0, 20.000001])


if __name__ == "__main__":
    unittest.main()
