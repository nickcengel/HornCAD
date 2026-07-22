from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from app.tools.run_coupled_kn_length_program import (
    anchor_selection, canonical_extension_targets, materialize_canonical_s_extension,
    materialize_kn_closure, materialize_local_s,
)
from app.tools.run_bem_search import load_search


ROOT = Path(__file__).resolve().parents[1]


class CoupledKNLengthProgramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = (ROOT / "examples" / "mouth-size-coverage-grid" /
                         "45deg" / "350x350-s-grid")
        self.seed = self.baseline / "candidates" / "candidate-004" / "project.yaml"
        if not self.seed.exists():
            self.seed = (ROOT / "examples" / "mouth-size-coverage-grid" /
                         "45deg" / "350x350" / "project.yaml")

    def test_materializes_dynamic_kn_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "closure-kn"
            materialize_kn_closure(self.seed, self.baseline, output)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
            loaded, _, _ = load_search(output / "search.yaml")
        self.assertEqual(search["initial_candidates"], 0)
        self.assertEqual(loaded["initial_candidates"], 0)
        self.assertNotIn("initial_pool", loaded)
        self.assertTrue(search["adaptive_kn_closure"]["enabled"])
        self.assertEqual(search["adaptive_kn_closure"]["minimum_k_step"], 0.5)
        self.assertEqual(search["adaptive_kn_closure"]["minimum_k"], 1.0)
        self.assertEqual(search["adaptive_kn_closure"]["minimum_n"], 2.0)
        self.assertEqual(search["adaptive_kn_closure"]["rescue_minimum_s"], 2.0)
        self.assertEqual(search["adaptive_kn_closure"]["rescue_minimum_n"], 8.0)
        self.assertEqual(search["adaptive_kn_closure"]["rescue_n_step"], 2.0)
        self.assertEqual(search["solver"]["workers"], 10)

    def test_materializes_five_point_local_s_rescan_at_closed_kn(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "closure-s"
            _, center = materialize_local_s(self.seed, self.baseline, output)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
            project = yaml.safe_load((output / "project.yaml").read_text())
        self.assertEqual(search["max_evaluations"], 5)
        self.assertEqual(len(search["initial_pool"]), 4)
        self.assertGreater(center, 0)
        k = project["horncad_config"]["horizontal_basis"]["k"]
        n = project["horncad_config"]["horizontal_basis"]["n"]
        self.assertEqual(search["bounds"]["k_h"][0], k)
        self.assertEqual(search["bounds"]["n_h"][0], n)

    def test_canonical_extension_adds_matched_points_without_rerunning_grid(self) -> None:
        targets = canonical_extension_targets(self.baseline)
        self.assertIn(0.5, targets)
        self.assertNotIn(3.5, targets)
        self.assertNotIn(1.0, targets)
        self.assertLess(len(targets), 9)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "canonical-s"
            materialize_canonical_s_extension(self.baseline, output)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
        self.assertEqual(search["max_evaluations"], len(targets))
        self.assertEqual(search["solver"]["workers"], 10)

    def test_anchor_selection_keeps_controls_and_material_scale_contrasts(self) -> None:
        selected, evidence = anchor_selection(
            ROOT / "examples" / "mouth-size-coverage-grid")
        self.assertTrue(all(any(
            path == ROOT / "examples" / "mouth-size-coverage-grid" /
            f"{angle}deg" / "400x400-s-grid" for path in selected)
                            for angle in (40, 45, 50)))
        self.assertTrue(all("role" in item and "selected" in item
                            for item in evidence))


if __name__ == "__main__":
    unittest.main()
