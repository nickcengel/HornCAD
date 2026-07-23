import unittest
from unittest import mock

from app.tools.prepare_extension_throat_angle_study import (
    CONDITIONAL_CELLS,
    COVERAGES,
    EXPECTED_COUNTS,
    INITIAL_CANDIDATES,
    LOCKED_CELLS,
    MAX_CANDIDATES,
    MOUTHS,
    build_manifest,
    candidate_design,
    validate_design,
)


class ExtensionThroatAngleStudyDesignTests(unittest.TestCase):
    def test_frozen_allocation_and_cap(self):
        rows = candidate_design()
        self.assertEqual(validate_design(rows), EXPECTED_COUNTS)
        self.assertEqual(len(rows), MAX_CANDIDATES)
        self.assertEqual(INITIAL_CANDIDATES, 210)

    def test_primary_development_covers_full_five_by_five_grid(self):
        cells = {
            (row["coverage_deg"], row["round_mouth_diameter_mm"])
            for row in candidate_design()
            if row["stage"] == "primary-development"
        }
        self.assertEqual(cells, set((c, m) for c in COVERAGES for m in MOUTHS))

    def test_retained_baseline_is_never_rescheduled(self):
        self.assertFalse(any(
            row["throat_angle_deg"] == 6 and row["extension_mm"] == 0
            for row in candidate_design()
        ))

    def test_validation_cells_are_fixed_and_locked(self):
        rows = candidate_design()
        locked_cells = {
            (row["coverage_deg"], row["round_mouth_diameter_mm"])
            for row in rows if row["stage"] == "locked-validation"
        }
        conditional_cells = {
            (row["coverage_deg"], row["round_mouth_diameter_mm"])
            for row in rows if row["stage"] == "conditional-validation"
        }
        self.assertEqual(locked_cells, set(LOCKED_CELLS))
        self.assertEqual(conditional_cells, set(CONDITIONAL_CELLS))
        self.assertTrue(all(
            row["outcome_access"] == "locked-until-heuristic-freeze"
            for row in rows
            if row["stage"] in ("locked-validation", "conditional-validation")
        ))

    @mock.patch(
        "app.tools.prepare_extension_throat_angle_study.assert_ridge_complete",
        return_value=(
            {"manifest_freeze_sha256": "ridge-manifest"},
            "ridge-results",
        ),
    )
    def test_manifest_requires_candidate_sharded_stage_aware_scheduler(self, _):
        scheduler = build_manifest()["required_scheduler"]
        self.assertEqual(scheduler["type"], "stage-aware-bem-queue")
        self.assertEqual(scheduler["search_sharding"], "one-candidate-per-search")
        self.assertFalse(scheduler["whole_search_slot_fallback_allowed"])


if __name__ == "__main__":
    unittest.main()
