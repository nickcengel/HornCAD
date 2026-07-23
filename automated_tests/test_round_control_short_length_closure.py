import unittest
from unittest import mock

from app.tools.run_round_control_short_length_closure import (
    CELLS,
    CONDITIONAL_MULTIPLIER,
    HARD_CANDIDATE_CAP,
    INITIAL_MULTIPLIER,
    NUMCALC_PROCESSES,
    _coordinate,
    _search_document,
)


class RoundControlShortLengthClosureTests(unittest.TestCase):
    def test_registered_design_is_three_plus_at_most_three(self):
        self.assertEqual(len(CELLS), 3)
        self.assertEqual(INITIAL_MULTIPLIER, 0.8)
        self.assertEqual(CONDITIONAL_MULTIPLIER, 0.7)
        self.assertEqual(HARD_CANDIDATE_CAP, 6)

    def test_each_coordinate_is_a_one_candidate_search(self):
        coordinate = _coordinate(40, 250, INITIAL_MULTIPLIER)
        document, values = _search_document(coordinate)
        search = document["bem_candidate_search"]
        self.assertEqual(search["max_evaluations"], 1)
        self.assertEqual(search["initial_candidates"], 1)
        self.assertEqual(len(search["initial_pool"]), 1)
        self.assertEqual(search["initial_pool"][0]["values"], values)
        self.assertEqual(search["solver"]["workers"], 10)
        self.assertEqual(values["k_h"], 1.0)
        self.assertEqual(values["k_v"], 1.0)

    def test_shared_scheduler_capacity_is_twenty(self):
        self.assertEqual(NUMCALC_PROCESSES, 20)


if __name__ == "__main__":
    unittest.main()
