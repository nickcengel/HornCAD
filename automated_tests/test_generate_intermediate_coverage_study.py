from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from app.tools.generate_intermediate_coverage_study import (
    COMPARABLE_30_S_TARGETS, S_TARGETS, materialize_coverage_sweep, study_grid,
)


ROOT = Path(__file__).resolve().parents[1]


class IntermediateCoverageStudyTests(unittest.TestCase):
    def test_materializes_dense_boundary_safe_s_sweep(self) -> None:
        source = ROOT / "examples" / "mouth-size-coverage-grid" / "45deg" / "300x300"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "40deg" / "300x300-s-grid"
            materialize_coverage_sweep(
                source / "project.yaml", source / "search.yaml", output, 40)
            project = yaml.safe_load((output / "project.yaml").read_text())
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]

        self.assertEqual(S_TARGETS[0], 0.5)
        self.assertEqual(S_TARGETS[-1], 4.0)
        self.assertEqual(len(S_TARGETS), 15)
        self.assertEqual(search["max_evaluations"], 15)
        self.assertEqual(search["solver"]["workers"], 10)
        self.assertTrue(search["adaptive_pruning"]["enabled"])
        self.assertTrue(search["initial_pool"][-1]["required"])
        self.assertEqual(project["horncad_config"]["horizontal_basis"]["coverage_deg"], 40)
        self.assertEqual(project["horncad_config"]["operating_intent"]["horizontal_coverage_deg"], 40)

    def test_30_degree_grid_matches_25_and_35_degree_coordinates(self) -> None:
        mouths, targets = study_grid(30.0)

        self.assertEqual(mouths, (250, 300, 350, 400, 450, 500))
        self.assertEqual(targets, COMPARABLE_30_S_TARGETS)
        self.assertEqual(targets, (0.7, 1.0, 1.3, 1.6, 1.9,
                                   2.2, 2.5, 2.8, 3.0))


if __name__ == "__main__":
    unittest.main()
