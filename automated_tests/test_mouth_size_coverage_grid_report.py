from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.tools.generate_mouth_size_coverage_grid_report import (
    _legacy_ranking_score,
    _search_summary,
    generate_report,
)


ROOT = Path(__file__).resolve().parents[1]


class MouthSizeCoverageGridReportTests(unittest.TestCase):
    def test_legacy_ranking_score_uses_the_previous_four_metrics(self) -> None:
        candidate = {"diagnostics": {"combined": {
            "coverage_match_percent": 80.0,
            "coverage_smoothness_percent": 90.0,
            "waist_stability_percent": 70.0,
            "window_uniformity_percent": 100.0,
        }}}

        self.assertEqual(_legacy_ranking_score(candidate), 85.0)
        self.assertIsNone(_legacy_ranking_score({}))

    def test_candidate_columns_are_toggleable_and_details_start_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "index.html"
            generate_report(ROOT / "examples" / "mouth-size-coverage-grid", output)
            report = output.read_text(encoding="utf-8")

        self.assertIn("<h2>Candidates</h2>", report)
        self.assertNotIn("<h2>Active ranking</h2>", report)
        self.assertNotIn("<h2>All results</h2>", report)
        self.assertIn("data-column-toggle='surface-score'", report)
        self.assertIn("data-column-toggle='legacy-rank'", report)
        self.assertIn("data-column-toggle='legacy-score'", report)
        self.assertIn(">Final surface score</th>", report)
        self.assertIn(">Previous rank</th>", report)
        self.assertIn(">Previous diagnostic score</th>", report)
        self.assertIn(">Newest</th>", report)
        self.assertIn("Candidates are ranked by the final surface score", report)
        self.assertIn("data-column-toggle='containment-mean'", report)
        self.assertIn("data-column-toggle='profile-rms'", report)
        self.assertIn("data-column-toggle='slice-rms'", report)
        self.assertIn("data-column-toggle='mouth-height'", report)
        self.assertNotIn("1/3-oct", report)
        self.assertIn("data-column='mouth-height' hidden", report)
        self.assertIn("data-column='mouth-width' hidden", report)
        self.assertNotIn("Average diagnostic score", report)
        self.assertNotIn("Coverage Match", report)
        # The selection ratio is mouth width divided by length: 250 / 179.
        self.assertIn("data-sort='1.396648'", report)

    def test_uniform_s_grid_has_a_distinct_report_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            search_dir = Path(temp) / "25deg" / "200x200-s-grid"
            search_dir.mkdir(parents=True)
            (search_dir / "search.yaml").write_text(
                "bem_candidate_search:\n"
                "  seed_yaml: project.yaml\n"
                "  crossover_hz: 750\n",
                encoding="utf-8",
            )
            summary = _search_summary(search_dir / "search.yaml")

        self.assertEqual(summary["study"], "uniform S grid")
        self.assertEqual(summary["label"], "25 deg\u00a0/\u200b 200 mm · uniform S grid")


if __name__ == "__main__":
    unittest.main()
