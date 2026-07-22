from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml
import app.tools.run_bem_domain_mapping_program as domain_program

from app.tools.run_bem_domain_mapping_program import (
    Proposal, RESPONSE_SURFACE_COORDINATES, SLOTS,
    materialize_cell_search, planned_slots, snap_k_n,
    _active_baseline_searches, _candidate_geometry,
)


ROOT = Path(__file__).resolve().parents[1]


class BemDomainMappingProgramTests(unittest.TestCase):
    def test_plan_has_same_sixteen_coordinates_in_every_cell(self) -> None:
        slots = planned_slots()
        self.assertEqual(len(slots), 400)
        for angle in (30, 35, 40, 45, 50):
            for mouth in (250, 300, 350, 400, 450):
                cell = [item for item in slots if
                        item["coverage_deg"] == angle and item["mouth_mm"] == mouth]
                self.assertEqual(len(cell), 16)
                self.assertEqual({item["batch"] for item in cell}, {1, 2})
                batch_two = [item for item in cell if item["batch"] == 2]
                self.assertEqual(
                    [(item["length_level"], item["k_level"], item["n_level"])
                     for item in batch_two], list(RESPONSE_SURFACE_COORDINATES))
        self.assertFalse(any(item["coverage_deg"] == 25 for item in slots))
        self.assertFalse(any(item["mouth_mm"] == 500 for item in slots))

    def test_batch_one_spans_remote_low_and_high_strata(self) -> None:
        self.assertEqual(SLOTS[1], (("low", "low", "low"),
                                    ("high", "high", "high")))

    def test_batch_two_is_face_centered_with_six_axes_and_eight_corners(self) -> None:
        batch_two = [item for item in planned_slots() if item["batch"] == 2]
        one_cell = [item for item in batch_two
                    if item["coverage_deg"] == 30 and item["mouth_mm"] == 250]
        axes = [item for item in one_cell
                if sum(level != 0 for level in (
                    item["length_level"], item["k_level"], item["n_level"])) == 1]
        corners = [item for item in one_cell
                   if all(level != 0 for level in (
                       item["length_level"], item["k_level"], item["n_level"]))]
        self.assertEqual(len(axes), 6)
        self.assertEqual(len(corners), 8)

    def test_boundary_repair_excludes_retired_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for angle, mouth in ((25, 300), (30, 250), (50, 450), (50, 500)):
                (root / f"{angle}deg" / f"{mouth}x{mouth}-s-grid").mkdir(
                    parents=True)
            selected = {
                str(path.relative_to(root)) for path in _active_baseline_searches(root)
            }
        self.assertEqual(selected, {
            "30deg/250x250-s-grid", "50deg/450x450-s-grid",
        })

    def test_domain_mapper_does_not_restart_legacy_closure_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(
                domain_program, "materialize_batch", return_value=([], [])), \
                patch.object(domain_program, "_apply_response_surface_manifest"), \
                patch.object(domain_program, "generate_report"):
            state = domain_program.run_program(Path(temp))
        self.assertEqual(state["total_coordinates"], 400)
        self.assertNotIn("s_closure", state)
        self.assertNotIn("coupled_length_closure", state)

    def test_batch_two_resume_never_materializes_batch_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "domain_mapping_state.json").write_text(json.dumps({
                "phase": "domain-map-batch-2", "completed_searches": 25,
                "planned_slots": planned_slots(),
            }))
            with patch.object(
                    domain_program, "materialize_batch", return_value=([], [])) as materialize, \
                    patch.object(domain_program, "_apply_response_surface_manifest"), \
                    patch.object(domain_program, "generate_report"):
                domain_program.run_program(root, start_batch=2)
        materialize.assert_called_once_with(root, 2, 10)

    def test_new_controls_snap_to_half_k_and_integer_n(self) -> None:
        self.assertEqual(snap_k_n(5.25, 8.75), (5.0, 9.0))
        self.assertEqual(snap_k_n(5.5, 8.2), (5.5, 8.0))

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

    def test_materialized_search_contains_all_fixed_candidates(self) -> None:
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
                Proposal(slot=2, s=1.2, length_mm=160.0, k=3.0, n=6.0,
                         **common),
            ]
            output = materialize_cell_search(root, proposals)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
        self.assertEqual(search["max_evaluations"], 3)
        self.assertEqual(search["initial_candidates"], 2)
        self.assertFalse(search["adaptive_pruning"]["enabled"])
        self.assertEqual(search["domain_mapping"]["batch"], 1)
        self.assertEqual(len(search["domain_mapping"]["proposals"]), 3)


if __name__ == "__main__":
    unittest.main()
