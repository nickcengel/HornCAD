from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import unittest

import numpy as np
import yaml

from app.tools.plan_control_decoupling_study import (
    ANGLES, MOUTHS, MAX_REGISTERED_COORDINATES, build_manifest,
    validate_manifest,
)
from app.tools.report_control_decoupling_study import _active_searches
from app.tools.run_bem_search import load_search


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "mouth-size-coverage-grid"
STUDY = ROOT / "examples" / "control-decoupling"


@lru_cache(maxsize=1)
def manifest():
    return build_manifest(SOURCE)


class ControlDecouplingStudyTests(unittest.TestCase):
    def test_runtime_events_mark_search_active_before_state_exists(self) -> None:
        runtime = {"status": "running", "events": [
            {"search": "searches/one", "status": "started"},
            {"search": "searches/two", "status": "started"},
            {"search": "searches/one", "status": "complete"},
        ]}
        self.assertEqual(_active_searches(runtime), {"searches/two"})

    def test_registered_design_is_complete_and_fixed(self) -> None:
        rows = manifest()["coordinates"]
        self.assertEqual(len(rows), MAX_REGISTERED_COORDINATES)
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        for angle in ANGLES:
            for mouth in MOUTHS:
                cell = [row for row in rows if
                        row["coverage_deg"] == angle and row["mouth_mm"] == mouth]
                self.assertEqual(len(cell), 38)
                self.assertEqual(Counter(row["kind"] for row in cell), {
                    "canonical-grid": 27, "reference-anchor": 1,
                    "boundary-sentinel": 2, "locked-validation": 2,
                    "conditional-axis-closure": 6,
                })

    def test_preflight_rejects_known_bad_geometry_and_is_balanced(self) -> None:
        study = manifest()
        self.assertEqual(validate_manifest(study, SOURCE), [])
        audit = study["design_audit"]
        self.assertEqual(audit["quadratic_model_rank"], 10)
        self.assertLess(audit["quadratic_model_condition"], 10)
        correlation = np.asarray(audit["factor_correlation_matrix"])
        self.assertLessEqual(float(np.max(np.abs(
            correlation - np.eye(3)))), 0.30)
        self.assertGreaterEqual(
            audit["active_coordinates_per_cell"]["minimum"], 15)
        self.assertGreaterEqual(
            audit["per_cell_factor_level_counts"]["n_level"]["1"]["minimum"], 2)
        self.assertEqual(len(audit["cell_quadratic_models"]), 25)
        self.assertTrue(all(item["quadratic_model_rank"] == 10
                            for item in audit["cell_quadratic_models"].values()))
        self.assertLess(max(item["quadratic_model_condition"]
                            for item in audit["cell_quadratic_models"].values()), 10)

    def test_only_strict_reference_results_are_reused(self) -> None:
        reused = [row for row in manifest()["coordinates"]
                  if row["status"] == "reused"]
        self.assertEqual(len(reused), 25)
        self.assertTrue(all(row["kind"] == "reference-anchor" for row in reused))
        self.assertTrue(all(row["k"] == 4 and row["n"] == 10 for row in reused))
        self.assertTrue(all(math.isfinite(row["s"]) for row in reused))
        self.assertTrue(all(row["reused_from"]["response"].endswith(
            "responses.npz") for row in reused))

    def test_redundant_parameter_changes_are_not_planned_for_bem(self) -> None:
        redundant = [row for row in manifest()["coordinates"]
                     if row["status"] == "geometry-redundant"]
        self.assertTrue(redundant)
        self.assertTrue(all(
            row["profile_rms_difference"] < 0.01 for row in redundant))
        self.assertFalse(any(row["status"] == "planned" and
                             row.get("profile_rms_difference", math.inf) < 0.01
                             for row in manifest()["coordinates"]))

    def test_validation_is_locked_and_not_an_edge_grid_point(self) -> None:
        validation = [row for row in manifest()["coordinates"]
                      if row["kind"] == "locked-validation"]
        self.assertEqual(len(validation), 50)
        self.assertTrue(all(row["locked_before_bem"] for row in validation))
        self.assertTrue(all(0.82 <= row["length_factor"] <= 1.18
                            for row in validation))
        self.assertTrue(all(3 <= row["k"] <= 5 and 6 <= row["n"] <= 14
                            for row in validation))

    def test_execution_plan_materializes_every_planned_coordinate_once(self) -> None:
        plan = json.loads((STUDY / "execution_plan.json").read_text())
        self.assertEqual(plan["candidate_count"],
                         manifest()["status_counts"]["planned"] +
                         manifest()["status_counts"].get("conditional", 0))
        identifiers = [identifier for search in plan["searches"]
                       for identifier in search["coordinate_ids"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        planned = {row["id"] for row in manifest()["coordinates"]
                   if row["status"] in {"planned", "conditional"}}
        self.assertEqual(set(identifiers), planned)
        review = (STUDY / "launch_review.md").read_text()
        self.assertIn(plan["manifest_sha256"], review)
        self.assertIn("No BEM work is started", review)

    def test_broad_k_grid_and_n2_only_as_conditional_closure(self) -> None:
        rows = manifest()["coordinates"]
        grid = [row for row in rows if row["kind"] == "canonical-grid"]
        self.assertEqual({row["k"] for row in grid}, {2.0, 4.0, 6.0})
        self.assertEqual({row["n"] for row in grid}, {4.0, 8.0, 16.0})
        n2 = [row for row in rows if row["n"] == 2.0]
        self.assertEqual(len(n2), 25)
        self.assertTrue(all(row["kind"] == "conditional-axis-closure"
                            and row["closure_axis"] == "N"
                            and row["closure_direction"] == "low"
                            for row in n2))

    def test_single_candidate_searches_omit_empty_initial_pool(self) -> None:
        single_count = 0
        for search_path in STUDY.rglob("search.yaml"):
            search = yaml.safe_load(search_path.read_text())["bem_candidate_search"]
            load_search(search_path)
            if search["max_evaluations"] == 1:
                single_count += 1
                self.assertNotIn("initial_pool", search)
            else:
                self.assertTrue(search["initial_pool"])
        self.assertGreater(single_count, 0)


if __name__ == "__main__":
    unittest.main()
