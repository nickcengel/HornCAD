from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np

from app.tools.bem_learning import (
    active_rules, merged_candidate_policy, nominal_candidate_rejections,
)
from app.tools.learn_bem_response import _quadratic
from app.tools.run_bem_domain_mapping_program import (
    _normalized_profile, _source_project,
)


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "examples" / "mouth-size-coverage-grid"


class BemLearningTests(unittest.TestCase):
    def test_ledger_is_active_and_unambiguous(self) -> None:
        rules = active_rules(ROOT)
        policy = merged_candidate_policy(ROOT)
        self.assertIn("physical-profile-materiality-v1", rules)
        self.assertEqual(policy["minimum_k_step"], 0.5)
        self.assertEqual(policy["minimum_n_step"], 1.0)
        self.assertTrue(policy["reject_repeated_k4_n10_length_axis"])

    def test_nominal_rules_reject_retired_edges_and_old_control_resolution(self) -> None:
        self.assertIn("study-domain-v1", nominal_candidate_rejections(
            25, 300, 4, 10, ROOT))
        self.assertIn("study-domain-v1", nominal_candidate_rejections(
            40, 500, 4, 10, ROOT))
        self.assertIn("coarse-control-grid-v1", nominal_candidate_rejections(
            40, 300, 4.25, 8.75, ROOT))
        self.assertFalse(nominal_candidate_rejections(40, 300, 4.5, 9, ROOT))

    def test_low_s_n_change_is_not_material_geometry(self) -> None:
        config = _source_project(
            STUDY / "30deg" / "250x250-s-grid")["horncad_config"]
        low = _normalized_profile(config, 30, 200.597, 3, 6)
        high = _normalized_profile(config, 30, 200.597, 3, 14)
        rms = float(np.sqrt(np.mean((low - high) ** 2)))
        self.assertLess(rms, merged_candidate_policy(ROOT)[
            "normalized_profile_rms_materiality_fraction"])

    def test_global_quadratic_feature_count(self) -> None:
        x = np.arange(18, dtype=float).reshape(3, 6)
        self.assertEqual(_quadratic(x).shape, (3, 28))


if __name__ == "__main__":
    unittest.main()
