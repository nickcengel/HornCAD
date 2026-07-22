from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ControlDecouplingBenchmarkTests(unittest.TestCase):
    def test_one_external_benchmark_per_cell(self) -> None:
        output = json.loads((ROOT / "examples" / "control-decoupling" /
                             "benchmarks.json").read_text())
        rows = output["benchmarks"]
        self.assertEqual(len(rows), 25)
        self.assertEqual(len({(row["coverage_deg"], row["mouth_mm"])
                              for row in rows}), 25)
        self.assertIn("excluded", output["role"])


if __name__ == "__main__":
    unittest.main()
