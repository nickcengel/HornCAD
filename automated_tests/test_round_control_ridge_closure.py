from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.tools.run_round_control_ridge_closure import (
    CELLS, LENGTH_MULTIPLIERS, MAX_CANDIDATES, _coordinate_id, _groups,
    _match_coordinate,
)


class RoundControlRidgeClosureTests(unittest.TestCase):
    def test_frozen_design_uses_exact_candidate_cap(self):
        groups = _groups()
        self.assertEqual(len(groups), len(CELLS))
        self.assertEqual(
            sum(len(group["candidates"]) for group in groups),
            MAX_CANDIDATES,
        )
        self.assertTrue(all(
            tuple(candidate["length_multiplier"]
                  for candidate in group["candidates"])
            == LENGTH_MULTIPLIERS
            for group in groups
        ))

    def test_design_covers_complete_mouth_and_coverage_axes(self):
        self.assertEqual({row[0] for row in CELLS}, {30, 35, 40, 45, 50})
        self.assertEqual({row[1] for row in CELLS}, {250, 300, 350, 400, 450})
        self.assertEqual({row[2] for row in CELLS}, {1.0, 7.0})

    def test_coordinate_matching_uses_measured_length(self):
        group = _groups()[0]
        candidate = group["candidates"][1]
        record = {"values": {"length_mm": candidate["length_mm"]}}
        self.assertEqual(_match_coordinate(record, group)["id"], candidate["id"])

    def test_coordinate_ids_are_stable(self):
        self.assertEqual(
            _coordinate_id(40, 450, 7.0, 8.0, 1.1),
            "ridge-40deg-450mm-K7-N8-Lx1p1",
        )


if __name__ == "__main__":
    unittest.main()
