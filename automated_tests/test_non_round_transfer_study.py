import math
import unittest

from app.design_api import DesignIntent, RoundControlHeuristics
from app.tools.run_non_round_transfer_study import (
    DEVELOPMENT_INTENTS,
    EQUAL_SQUARE,
    HEURISTICS,
    LENGTH_RULES,
    LOCKED_INTENTS,
    SHAPES,
    _candidate,
    common_lengths,
    refresh_index,
)


class NonRoundTransferStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = RoundControlHeuristics.load(HEURISTICS)

    def test_registered_allocation_is_48_before_closure(self):
        development = len(EQUAL_SQUARE) + (
            len(DEVELOPMENT_INTENTS)*len(SHAPES)*len(LENGTH_RULES))
        locked = len(LOCKED_INTENTS)*len(SHAPES)
        self.assertEqual(development, 36)
        self.assertEqual(locked, 12)
        self.assertEqual(development+locked, 48)

    def test_s_balanced_length_is_deterministic_and_bracketed(self):
        intent = DesignIntent(400, 280, 50, 35)
        first = common_lengths(self.rules, intent)
        second = common_lengths(self.rules, intent)
        seed = self.rules.recommend(intent)
        self.assertEqual(first, second)
        self.assertGreaterEqual(
            first["s-balanced"],
            min(seed.horizontal.profile_length_mm,
                seed.vertical.profile_length_mm),
        )
        self.assertLessEqual(
            first["s-balanced"],
            max(seed.horizontal.profile_length_mm,
                seed.vertical.profile_length_mm),
        )
        self.assertFalse(math.isclose(
            first["weighted"], first["s-balanced"], abs_tol=1e-8))

    def test_candidate_fixes_intent_and_keeps_independent_axes(self):
        intent = DesignIntent(400, 280, 50, 35)
        lengths = common_lengths(self.rules, intent)
        project, search, row = _candidate(
            "test-anchor", intent, "square", "weighted",
            lengths["weighted"], phase="test", purpose="test",
            source_intent_id="T1")
        config = project["horncad_config"]
        self.assertEqual(config["global"]["throat_angle_deg"], 6.0)
        self.assertEqual(config["global"]["conical_extension_length"], 0.0)
        self.assertEqual(config["global"]["mouth_sag"], 0.0)
        self.assertFalse(config["global"]["mouth_sag_h_enabled"])
        self.assertFalse(config["global"]["mouth_sag_v_enabled"])
        self.assertEqual(
            config["section_modifier"]["mouth_squareness"], 1.0)
        self.assertEqual(
            config["operating_intent"]["horizontal_coverage_deg"], 50.0)
        self.assertEqual(
            config["operating_intent"]["vertical_coverage_deg"], 35.0)
        self.assertEqual(config["horizontal_basis"]["coverage_deg"], 50.0)
        self.assertEqual(config["vertical_basis"]["coverage_deg"], 35.0)
        self.assertEqual(row["k_h"], 5.5)
        self.assertEqual(row["k_v"], 2.0)
        self.assertNotEqual(row["k_h"], row["k_v"])
        bounds = search["bem_candidate_search"]["bounds"]
        self.assertAlmostEqual(
            sum(bounds["length_mm"])/2, lengths["weighted"])

    def test_live_index_is_sortable_and_self_refreshing(self):
        document = refresh_index().read_text(encoding="utf-8")
        self.assertIn("http-equiv='refresh' content='5'", document)
        self.assertIn('table class="sortable"', document)
        self.assertIn('data-sort="number">Length', document)
        self.assertIn('data-sort="number">Surface v2.3', document)
        self.assertIn('data-sort="number">Impedance v2.3.0', document)
        self.assertIn('header.addEventListener("click"', document)
        self.assertIn('id="updated-at"', document)


if __name__ == "__main__":
    unittest.main()
