from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from app.tools.generate_intermediate_coverage_study import (
    S_TARGETS, materialize_coverage_sweep,
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
        self.assertEqual(project["horncad_config"]["horizontal_basis"]["coverage_deg"], 40)
        self.assertEqual(project["horncad_config"]["operating_intent"]["horizontal_coverage_deg"], 40)


if __name__ == "__main__":
    unittest.main()
