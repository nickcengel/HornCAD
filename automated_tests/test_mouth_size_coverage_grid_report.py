from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.tools.generate_mouth_size_coverage_grid_report import generate_report


ROOT = Path(__file__).resolve().parents[1]


class MouthSizeCoverageGridReportTests(unittest.TestCase):
    def test_candidate_columns_are_toggleable_and_details_start_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "index.html"
            generate_report(ROOT / "examples" / "mouth-size-coverage-grid", output)
            report = output.read_text(encoding="utf-8")

        self.assertIn("<h2>Candidates</h2>", report)
        self.assertNotIn("<h2>Active ranking</h2>", report)
        self.assertNotIn("<h2>All results</h2>", report)
        self.assertIn("data-column-toggle='containment-mean'", report)
        self.assertIn("data-column-toggle='profile-rms'", report)
        self.assertIn("data-column-toggle='slice-rms'", report)
        self.assertIn("data-column-toggle='mouth-height'", report)
        self.assertIn("data-column='containment-worst' hidden", report)
        self.assertIn("data-column='mouth-height' hidden", report)
        self.assertIn("data-column='mouth-width' hidden", report)
        self.assertNotIn("Average diagnostic score", report)
        self.assertNotIn("Coverage Match", report)
        # The selection ratio is mouth width divided by length: 250 / 179.
        self.assertIn("data-sort='1.396648'", report)


if __name__ == "__main__":
    unittest.main()
