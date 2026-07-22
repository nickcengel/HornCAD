from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import yaml

from app.tools.run_bem_domain_mapping_program import (
    ANGLES, MOUTHS, Proposal, SLOTS, materialize_cell_search, planned_slots,
    _candidate_geometry,
)


ROOT = Path(__file__).resolve().parents[1]


class BemDomainMappingProgramTests(unittest.TestCase):
    def test_plan_has_four_slots_in_every_cell(self) -> None:
        slots = planned_slots()
        self.assertEqual(len(slots), 144)
        for angle in ANGLES:
            for mouth in MOUTHS:
                cell = [item for item in slots if
                        item["coverage_deg"] == angle and item["mouth_mm"] == mouth]
                self.assertEqual(len(cell), 4)
                self.assertEqual({item["batch"] for item in cell}, {1, 2})

    def test_foldover_spans_low_and_high_k_n_s(self) -> None:
        self.assertEqual(SLOTS[1], (("low", "low", "low"),
                                    ("high", "high", "high")))
        self.assertEqual(SLOTS[2], (("high", "low", "high"),
                                    ("low", "high", "low")))

    def test_candidate_geometry_derives_length_and_respects_growth_limit(self) -> None:
        baseline = (ROOT / "examples" / "mouth-size-coverage-grid" /
                    "40deg" / "400x400-s-grid")
        config = yaml.safe_load((baseline / "project.yaml").read_text())[
            "horncad_config"]
        result = _candidate_geometry(config, 40, 1.0, 4.0, 10.0)
        self.assertIsNotNone(result)
        length, metrics = result
        self.assertGreater(length, 100)
        self.assertLessEqual(metrics["final_tenth_radial_growth_fraction"], 0.52)

    def test_materialized_search_contains_two_fixed_remote_candidates(self) -> None:
        source = (ROOT / "examples" / "mouth-size-coverage-grid" /
                  "40deg" / "400x400-s-grid")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "40deg" / "400x400-s-grid"
            baseline.mkdir(parents=True)
            shutil.copy2(source / "project.yaml", baseline / "project.yaml")
            shutil.copy2(source / "search.yaml", baseline / "search.yaml")
            common = dict(
                coverage_deg=40, mouth_mm=400, batch=1,
                mouth_length_ratio=2.0, exit_angle_deg=40,
                normalized_curvature_radius=1.0,
                acquisition="remote maximin coverage", nearest_distance=0.5,
            )
            proposals = [
                Proposal(slot=0, s=1.0, length_mm=171.584, k=4.0, n=10.0,
                         **common),
                Proposal(slot=1, s=1.5, length_mm=150.0, k=5.0, n=15.0,
                         **common),
            ]
            output = materialize_cell_search(root, proposals)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
        self.assertEqual(search["max_evaluations"], 2)
        self.assertEqual(search["initial_candidates"], 1)
        self.assertFalse(search["adaptive_pruning"]["enabled"])
        self.assertEqual(search["domain_mapping"]["batch"], 1)
        self.assertEqual(len(search["domain_mapping"]["proposals"]), 2)


if __name__ == "__main__":
    unittest.main()
