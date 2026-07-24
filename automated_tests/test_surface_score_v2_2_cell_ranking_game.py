from __future__ import annotations

import unittest

from app.tools.generate_surface_score_v2_2_cell_ranking_game import (
    select_cell_candidates,
)


class SurfaceScoreV22CellRankingGameTests(unittest.TestCase):
    def test_selection_has_five_unique_picks_from_each_score(self) -> None:
        candidates = []
        for index in range(15):
            candidates.append({
                "id": f"candidate-{index:02d}",
                "response_sha256": f"{index:064x}",
                "score_v1": 100.0 - index,
                "score_v2_2": (
                    100.0 - index if index < 3 else 100.0 - abs(index - 8)
                ),
            })
        selected = select_cell_candidates(candidates)
        self.assertEqual(10, len(selected))
        self.assertEqual(
            10, len({row["response_sha256"] for row in selected})
        )
        self.assertEqual(
            {"v1": 5, "v2.2": 5},
            {
                name: sum(row["selected_by"] == name for row in selected)
                for name in ("v1", "v2.2")
            },
        )
        self.assertTrue(all(row["rank_v1"] >= 1 for row in selected))
        self.assertTrue(all(row["rank_v2_2"] >= 1 for row in selected))


if __name__ == "__main__":
    unittest.main()
