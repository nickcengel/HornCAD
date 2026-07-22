from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.tools.run_bem_phase4_handoff import (
    batch_one_handoff_ready, search_finished, truncate_batch_one,
)


class BemPhaseFourHandoffTests(unittest.TestCase):
    def test_handoff_requires_published_batch_two_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "domain_mapping_state.json"
            state.write_text(json.dumps({"phase": "domain-map-batch-1"}))
            self.assertFalse(batch_one_handoff_ready(root))
            state.write_text(json.dumps({"phase": "domain-map-batch-2"}))
            self.assertTrue(batch_one_handoff_ready(root))

    def test_truncation_records_abandoned_slots_and_enables_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            finished = root / "30deg" / "250x250-domain-map-b01"
            finished.mkdir(parents=True)
            (finished / "search_state.json").write_text(json.dumps({
                "status": "complete",
            }))
            (root / "domain_mapping_state.json").write_text(json.dumps({
                "phase": "domain-map-batch-1",
                "planned_slots": [
                    {"batch": 1, "coverage_deg": 30, "mouth_mm": 250, "slot": 0},
                    {"batch": 1, "coverage_deg": 30, "mouth_mm": 300, "slot": 0},
                    {"batch": 2, "coverage_deg": 30, "mouth_mm": 250, "slot": 0},
                ],
            }))
            relative = "30deg/250x250-domain-map-b01"
            self.assertTrue(search_finished(root, relative))
            truncate_batch_one(root, [relative])
            state = json.loads((root / "domain_mapping_state.json").read_text())
        self.assertEqual(state["phase"], "domain-map-batch-2")
        self.assertEqual(state["batch_1_decision"]["abandoned_candidate_slots"], 1)
        self.assertEqual(state["planned_slots"][0]["status"],
                         "complete-before-truncation")
        self.assertEqual(state["planned_slots"][1]["status"],
                         "abandoned-redundant-boundary")


if __name__ == "__main__":
    unittest.main()
