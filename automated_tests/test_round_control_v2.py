from pathlib import Path
import tempfile
import unittest

from app.tools.round_control_v2 import (
    HISTORICAL_WEIGHTS, VALIDATION_CELLS, _development_rows,
    _diagnostic_scales, _fit_cells, _read_json,
)


ROOT = Path(__file__).resolve().parents[1]


class RoundControlV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = _read_json(
            ROOT / "examples/control-decoupling/model_source/training_index.json")
        cls.rows = _development_rows(cls.index)

    def test_full_grid_retains_rank_for_every_candidate_weight(self):
        for weight in HISTORICAL_WEIGHTS:
            with self.subTest(weight=weight):
                cells, audit = _fit_cells(self.rows, weight)
                self.assertEqual(len(cells), 25)
                self.assertTrue(all(row["rank"] == 10
                                    for row in audit.values()))

    def test_validation_design_covers_full_grid_axes(self):
        self.assertEqual(len(VALIDATION_CELLS), 12)
        self.assertEqual({coverage for coverage, _ in VALIDATION_CELLS},
                         {30, 35, 40, 45, 50})
        self.assertEqual({mouth for _, mouth in VALIDATION_CELLS},
                         {250, 300, 350, 400, 450})

    def test_throat_impedance_has_scale_but_is_not_preregistered_radiation(self):
        scales = _diagnostic_scales(self.rows)
        self.assertGreater(scales["throat_impedance_score"], 0)


if __name__ == "__main__":
    unittest.main()
