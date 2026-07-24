import json
import tempfile
import unittest
from pathlib import Path

from app.tools.surface_ranking_experiment import (
    BROAD_ROUND_COUNT,
    CLOSE_ROUND_COUNT,
    ROUND_COUNT,
    _initial_state,
    _rank_statistics,
    build_report,
    select_candidates,
    validate_state,
)


def manifest():
    return {
        "experiment_id": "test",
        "rounds": [
            {
                "round": round_number,
                "plots": [
                    {"plot_id": f"R{round_number:02d}-P{plot_number:02d}"}
                    for plot_number in range(1, 11)
                ],
            }
            for round_number in range(1, ROUND_COUNT + 1)
        ],
    }


class SurfaceRankingExperimentTests(unittest.TestCase):
    def test_selection_is_deterministic_and_balanced(self):
        candidates = [
            {
                "response_sha256": f"{index:064x}",
                "responses": {"surface_score": float(index)},
            }
            for index in range(1000)
        ]
        first = select_candidates(candidates, 7)
        second = select_candidates(candidates, 7)
        self.assertEqual(first, second)
        self.assertEqual(ROUND_COUNT, len(first))
        self.assertEqual(200, len({row["response_sha256"] for group in first for row in group}))
        for group in first[:BROAD_ROUND_COUNT]:
            self.assertEqual(list(range(10)), sorted(int(row["responses"]["surface_score"]) // 100 for row in group))
        close_ranges = [
            max(row["responses"]["surface_score"] for row in group)
            - min(row["responses"]["surface_score"] for row in group)
            for group in first[BROAD_ROUND_COUNT:]
        ]
        self.assertEqual(CLOSE_ROUND_COUNT, len(close_ranges))
        self.assertTrue(all(score_range <= 25 for score_range in close_ranges))

    def test_notes_follow_plot_and_locked_round_cannot_change(self):
        public = manifest()
        state = _initial_state(public)
        state["notes"]["R01-P03"] = "Good center, rough upper edge."
        order = state["orders"]["1"]
        order.insert(0, order.pop(2))
        state["locked_rounds"] = [1]
        saved = validate_state(state, public)
        self.assertEqual("R01-P03", saved["orders"]["1"][0])
        self.assertEqual("Good center, rough upper edge.", saved["notes"]["R01-P03"])
        changed = json.loads(json.dumps(saved))
        changed["notes"]["R01-P03"] = "Changed"
        with self.assertRaisesRegex(ValueError, "already locked"):
            validate_state(changed, public, saved)

    def test_rank_statistics(self):
        order = [f"P{index}" for index in range(10)]
        self.assertEqual(1.0, _rank_statistics(order, order)["spearman"])
        reverse = list(reversed(order))
        self.assertEqual(-1.0, _rank_statistics(reverse, order)["spearman"])
        self.assertEqual(0.0, _rank_statistics(reverse, order)["pairwise_agreement"])

    def test_completed_report_includes_escaped_notes(self):
        public = manifest()
        state = _initial_state(public)
        state["locked_rounds"] = list(range(1, ROUND_COUNT + 1))
        state["complete"] = True
        state["notes"]["R01-P01"] = "<specific> observation"
        plots = {}
        for round_item in public["rounds"]:
            for index, plot in enumerate(round_item["plots"]):
                plots[plot["plot_id"]] = {
                    "candidate_id": f"candidate-{plot['plot_id']}",
                    "surface_score": 100 - index,
                    "candidate_report": None,
                }
        with tempfile.TemporaryDirectory() as directory:
            path = build_report(Path(directory), state, {"plots": plots})
            document = path.read_text()
        self.assertIn("&lt;specific&gt; observation", document)
        self.assertNotIn("<specific> observation", document)


if __name__ == "__main__":
    unittest.main()
