from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.tools.generate_mouth_size_coverage_grid_report import (
    _deduplicate_candidate_rows,
    _legacy_ranking_score,
    _search_summary,
    generate_report,
)


ROOT = Path(__file__).resolve().parents[1]


class MouthSizeCoverageGridReportTests(unittest.TestCase):
    def test_near_duplicate_candidates_keep_the_better_score(self) -> None:
        summary = {"mouth_width": 350, "mouth_height": 350}
        def row(length: float, score: float) -> dict:
            return {
                "search": summary,
                "candidate": {"values": {
                    "length_mm": length, "extension_mm": 0,
                    "osse_coverage_h_deg": 45, "osse_coverage_v_deg": 45,
                    "k_h": 4, "k_v": 4, "n_h": 10, "n_v": 10,
                }},
                "surface_ranking_score": score,
            }

        retained = _deduplicate_candidate_rows([
            row(126.545, 88.279), row(126.861, 88.282), row(130, 80)])

        self.assertEqual(
            sorted(item["candidate"]["values"]["length_mm"] for item in retained),
            [126.861, 130])

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
        self.assertIn("aria-label='Filter candidates by coverage angle'", report)
        self.assertIn("data-angle-filter='all'", report)
        self.assertIn("data-angle-filter='25'", report)
        self.assertIn("data-angle-filter='35'", report)
        self.assertIn("data-angle-filter='45'", report)
        self.assertNotIn("data-angle-filter='60'", report)
        self.assertIn(
            "Supported domain: 25°–50° half-coverage and 250–500 mm mouth size",
            report,
        )
        self.assertNotIn("data-sort='200.000000'", report)
        self.assertIn("data-coverage-angle='25'", report)
        self.assertIn("id='candidate-filter-count'", report)
        self.assertIn("id='candidate-show-more'", report)
        self.assertIn(">Show 25 more</button>", report)
        self.assertIn("let candidateLimit = 25", report)
        self.assertIn("candidateLimit += 25", report)
        self.assertIn("shown < candidateLimit", report)
        self.assertIn("if (table === candidateTable) renderCandidates()", report)
        self.assertIn("aria-label='Filter sub-searches by coverage angle'", report)
        self.assertIn("data-subsearch-angle-filter='30'", report)
        self.assertIn("data-subsearch-angle-filter='50'", report)
        self.assertIn("id='subsearch-filter-count'", report)
        self.assertIn("row.dataset.subsearchCoverageAngle.split(' ')", report)
        self.assertIn("data-sort='number'>Date complete</th>", report)
        self.assertRegex(report, r"<td data-sort='\d+\.\d{6}'>\d{1,2}-\d{2} \d{2}:\d{2}</td>")
        self.assertNotIn("<h2>Active ranking</h2>", report)
        self.assertNotIn("<h2>All results</h2>", report)
        self.assertIn("data-column-toggle='surface-score'", report)
        self.assertIn("data-column-toggle='legacy-rank'", report)
        self.assertIn("data-column-toggle='legacy-score'", report)
        self.assertIn(">Final surface score</th>", report)
        self.assertIn(">Previous rank</th>", report)
        self.assertIn(">Previous diagnostic score</th>", report)
        self.assertIn(">Date</th>", report)
        self.assertNotIn(">New rank</th>", report)
        self.assertIn(
            "<thead><tr><th class='sortable' data-sort='text'>Candidate</th>"
            "<th class='sortable' data-column='surface-score' data-sort='number'>"
            "Final surface score</th><th class='sortable' data-sort='number'>Date</th>",
            report,
        )
        self.assertIn("Candidates are ranked by the final surface score", report)
        self.assertIn("<h2>Design map</h2>", report)
        self.assertIn("class='design-map'", report)
        self.assertIn("<th scope='col'>30°</th>", report)
        self.assertIn("<th scope='row'>250 mm</th>", report)
        self.assertIn("class='design-score'", report)
        self.assertIn("W/L ", report)
        self.assertRegex(report, r"S \d+\.\d{2} · K \d+(?:\.\d+)? · N \d+(?:\.\d+)?")
        self.assertIn("class='design-state ", report)
        self.assertNotIn("id='design-surface'", report)
        self.assertIn(".design-map th:first-child{width:210px", report)
        self.assertRegex(report, r"L \d+\.\d mm · W/L \d+\.\d{2}")
        self.assertIn("<h2>Sampling extent</h2>", report)
        self.assertIn("class='sampling-matrix'", report)
        self.assertIn("data-sampling-key='400:45'", report)
        self.assertIn("id='sampling-2d'", report)
        self.assertIn("id='sampling-3d'", report)
        self.assertIn("const samplingPoints = [", report)
        self.assertIn("No interpolated surface is drawn", report)
        self.assertIn("drawSampling2d", report)
        self.assertIn("drawSampling3d", report)
        self.assertIn("data-column-toggle='containment-mean'", report)
        self.assertIn("data-column-toggle='profile-rms'", report)
        self.assertIn("data-column-toggle='slice-rms'", report)
        self.assertIn("data-column-toggle='mouth-height'", report)
        self.assertNotIn("1/3-oct", report)
        self.assertIn("data-column='mouth-height' hidden", report)
        self.assertIn("data-column='mouth-width' hidden", report)
        self.assertIn("data-column='containment-mean' hidden", report)
        self.assertIn("data-column='profile-rms' hidden", report)
        self.assertIn("data-column='slice-rms' hidden", report)
        self.assertRegex(report, r">\d{1,2}-\d{2} \d{2}:\d{2}</td>")
        self.assertNotIn("Candidate performance trends", report)
        self.assertNotIn("class='plot-card'", report)
        self.assertNotIn("class='trend-plot'", report)
        self.assertNotIn("scatter-popup", report)
        self.assertIn("matched coupled K/N ↔ local S", report)
        self.assertIn("<span class='badge pending'>planned</span>", report)
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

    def test_coupled_rounds_have_distinct_report_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            angle = Path(temp) / "45deg"
            for suffix, expected in (("kn", "coupled K/N closure"),
                                     ("s", "coupled local S")):
                search_dir = angle / f"400x400-coupled-r01-{suffix}"
                search_dir.mkdir(parents=True)
                (search_dir / "search.yaml").write_text(
                    "bem_candidate_search:\n"
                    "  seed_yaml: project.yaml\n"
                    "  crossover_hz: 750\n",
                    encoding="utf-8",
                )
                summary = _search_summary(search_dir / "search.yaml")
                self.assertEqual(summary["study"], expected)
                self.assertIn(expected, summary["label"])

    def test_canonical_s_extension_has_a_distinct_report_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            search_dir = Path(temp) / "45deg" / "400x400-canonical-s"
            search_dir.mkdir(parents=True)
            (search_dir / "search.yaml").write_text(
                "bem_candidate_search:\n"
                "  seed_yaml: project.yaml\n"
                "  crossover_hz: 750\n",
                encoding="utf-8",
            )
            summary = _search_summary(search_dir / "search.yaml")
        self.assertEqual(summary["study"], "canonical S extension")
        self.assertIn("canonical S extension", summary["label"])

    def test_s_boundary_round_has_a_distinct_report_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            search_dir = Path(temp) / "25deg" / "400x400-s-boundary-r01"
            search_dir.mkdir(parents=True)
            (search_dir / "search.yaml").write_text(
                "bem_candidate_search:\n"
                "  seed_yaml: project.yaml\n"
                "  crossover_hz: 750\n",
                encoding="utf-8",
            )
            summary = _search_summary(search_dir / "search.yaml")
        self.assertEqual(summary["study"], "S boundary closure")
        self.assertIn("S boundary closure", summary["label"])


if __name__ == "__main__":
    unittest.main()
