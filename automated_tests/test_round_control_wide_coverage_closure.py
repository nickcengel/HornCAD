import unittest

from app.tools.run_round_control_wide_coverage_closure import (
    HARD_CANDIDATE_CAP,
    INITIAL_COORDINATES,
    initial_coordinates,
)


class WideCoverageClosureTests(unittest.TestCase):
    def test_initial_design_is_bounded_and_records_s(self):
        rows = initial_coordinates()
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(INITIAL_COORDINATES), 10)
        self.assertEqual(HARD_CANDIDATE_CAP, 12)
        self.assertTrue(all(row["derived_s"] > 0 for row in rows))
        self.assertTrue(all(row["k"] <= 7 for row in rows))
        self.assertTrue(all(row["n"] == 8 for row in rows))

    def test_cells_and_probe_counts_are_frozen(self):
        rows = initial_coordinates()
        counts = {}
        for row in rows:
            key = (row["coverage_deg"], row["mouth_mm"])
            counts[key] = counts.get(key, 0)+1
        self.assertEqual(counts, {
            (45, 350): 4,
            (50, 350): 4,
            (50, 450): 2,
        })


if __name__ == "__main__":
    unittest.main()
