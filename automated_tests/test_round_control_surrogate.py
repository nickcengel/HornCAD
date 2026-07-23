from pathlib import Path
import unittest

import numpy as np

from app.tools.round_control_surrogate import (
    CANDIDATES, DIAGNOSTICS, _predict_cell, fit, predict,
)


class RoundControlSurrogateTests(unittest.TestCase):
    def _rows(self):
        rows = []
        for coverage in (30, 35, 40, 45, 50):
            for mouth in (250, 300, 350, 400, 450):
                for index, (length, k, n) in enumerate((
                        (0.8, 2.0, 4.0), (0.9, 3.0, 6.0),
                        (1.0, 4.0, 8.0), (1.1, 5.0, 10.0),
                        (1.2, 6.0, 12.0), (1.05, 4.5, 14.0),
                        (0.95, 3.5, 16.0), (1.15, 2.5, 9.0),
                        (0.85, 5.5, 7.0), (1.02, 4.2, 11.0),
                )):
                    value = length + k + n + coverage/10 + mouth/100
                    rows.append({
                        "id": f"{coverage}-{mouth}-{index}",
                        "coverage_deg": coverage,
                        "mouth_mm": mouth,
                        "length_factor": length,
                        "k": k,
                        "n": n,
                        "responses": {
                            name: value+offset
                            for offset, name in enumerate(DIAGNOSTICS)
                        },
                    })
        return rows

    def test_every_candidate_reproduces_exact_evidence(self):
        rows = self._rows()
        for candidate in CANDIDATES:
            model = fit(rows, candidate)
            result = predict(model, rows[2])
            for name in DIAGNOSTICS:
                self.assertAlmostEqual(
                    result[name], rows[2]["responses"][name])

    def test_rbf_prediction_is_finite(self):
        rows = self._rows()
        candidate = next(
            item for item in CANDIDATES
            if item["method"] == "quadratic_rbf")
        model = fit(rows, candidate)
        cell = model["cells"]["30deg-250mm"]
        value = _predict_cell(cell, np.asarray((0.1, 0.1, 0.1)))
        self.assertTrue(np.all(np.isfinite(value)))


if __name__ == "__main__":
    unittest.main()
