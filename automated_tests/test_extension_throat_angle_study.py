import unittest
from pathlib import Path
import json
import re

import numpy as np

from app.tools.run_extension_throat_angle_study import (
    DEVELOPMENT_STAGES,
    DIAGNOSTICS,
    _formula_prediction,
    _search_document,
    select_parents,
)
from app.tools.prepare_extension_throat_angle_study import candidate_design
from app.tools.report_extension_throat_angle_study import (
    _percent_change,
    render_index,
)
from app.tools.throat_impedance_diagnostics import (
    throat_impedance_diagnostics,
)
from app.tools.run_extension_s_matched_followup import (
    select_followups,
    solve_parent_s_length,
    solve_parent_s_mouth,
)


class ExtensionThroatAngleStudyTests(unittest.TestCase):
    def test_parent_selection_covers_full_grid_and_transfer_cells(self):
        parents = select_parents()
        self.assertEqual(len(parents["primary"]), 25)
        self.assertEqual(len(parents["secondary"]), 3)
        self.assertFalse(parents["selection_rule"]["throat_impedance_used"])

    def test_every_initial_coordinate_becomes_one_fixed_search(self):
        parents = select_parents()
        row = next(
            row for row in candidate_design()
            if row["stage"] in DEVELOPMENT_STAGES)
        cell = f"{row['coverage_deg']}deg-{row['round_mouth_diameter_mm']}mm"
        document, _ = _search_document(row, parents["primary"][cell])
        search = document["bem_candidate_search"]
        self.assertEqual(search["max_evaluations"], 1)
        self.assertEqual(len(search["initial_pool"]), 1)
        self.assertTrue(search["fixed_design"])
        self.assertTrue(
            search["extension_throat_angle_study"][
                "throat_impedance_reported"])

    def test_paired_formula_is_exact_at_forty(self):
        measured = {}
        for angle in (0, 6, 12):
            for extension in (0, 20, 40, 60):
                measured[(angle, extension)] = {
                    key: angle+extension/10 for key in DIAGNOSTICS
                }
        predicted = _formula_prediction(measured, 12, 40)
        self.assertEqual(predicted, measured[(12, 40)])

    def test_candidate_change_is_percent_from_parent(self):
        self.assertAlmostEqual(_percent_change(90.0, 75.0), 20.0)
        self.assertAlmostEqual(_percent_change(60.0, 75.0), -20.0)
        self.assertIsNone(_percent_change(None, 75.0))
        self.assertIsNone(_percent_change(75.0, 0.0))

    def test_s_matched_selection_reserves_extended_cases(self):
        eligible = [
            {
                "id": f"case-{index}",
                "surface_delta_points": float(index),
                "extension_mm": 40 if index in (4, 5) else 0,
            }
            for index in range(6)
        ]
        selected = select_followups(eligible)
        self.assertEqual(len(selected), 6)
        self.assertGreaterEqual(
            sum(row["extension_mm"] > 0 for row in selected), 2)

    def test_s_matched_length_is_shorter_and_recovers_parent_s(self):
        length = solve_parent_s_length(
            original_length_mm=333.689,
            effective_throat_radius_mm=12.7,
            coverage_deg=30.0,
            k=7.0,
            n=8.0,
            mouth_radius_mm=225.0,
            throat_angle_deg=12.0,
            target_s=0.483500820567733,
        )
        self.assertLess(length, 333.689)
        self.assertAlmostEqual(length, 293.50631695, places=6)

    def test_angle_only_s_match_increases_mouth_at_parent_length(self):
        mouth = solve_parent_s_mouth(
            length_mm=333.689,
            effective_throat_radius_mm=12.7,
            coverage_deg=30.0,
            k=7.0,
            n=8.0,
            throat_angle_deg=12.0,
            target_s=0.483500820567733,
        )
        self.assertGreater(mouth, 450.0)
        self.assertAlmostEqual(mouth, 521.71131869, places=6)

    def test_impedance_v2_2_preserves_reviewed_parent_order(self):
        names = (
            "250x250x84.633_45_K2_N8",
            "250x250x89.754_50_K4_N11.25",
            "450x450x151.574_50_K6_N8",
            "250x250x122.757_35_K2_N8",
            "400x400x140.92_50_K6_N8",
            "450x450x159.689_50_K7_N8",
            "250x250x139.546_30_K2_N4",
            "350x350x235.546_30_K4_N8",
            "400x400x291.235_30_K6_N8",
            "450x450x333.689_30_K7_N8",
        )
        manifest = json.loads(Path(
            "examples/extension-throat-angle-heuristics/manifest.json"
        ).read_text(encoding="utf-8"))
        scores = {}
        for role in ("primary", "secondary"):
            for parent in manifest["parents"][role].values():
                response = Path(parent["response_path"])
                state = json.loads(
                    (response.parents[3] / "search_state.json").read_text(
                        encoding="utf-8"))
                candidate_id = response.parents[1].name
                record = next(
                    row for row in state["candidates"]
                    if row["id"] == candidate_id)
                name = Path(record["report_file"]).stem.removesuffix(
                    "_Report")
                if name not in names:
                    continue
                with np.load(response, allow_pickle=False) as archive:
                    result = throat_impedance_diagnostics(
                        archive["frequencies_hz"],
                        archive["impedance"],
                        state["crossover_hz"],
                        state["upper_frequency_hz"],
                    )
                scores[name] = result["overall_percent"]
        ordered = [scores[name] for name in names]
        self.assertLess(ordered[0], ordered[1])
        self.assertLess(max(ordered[:2]), min(ordered[2:6]))
        self.assertLess(max(ordered[2:6]), ordered[6])
        self.assertLess(ordered[6], ordered[7])
        self.assertLess(ordered[7], min(ordered[8:]))
        self.assertLessEqual(max(ordered[2:6]) - min(ordered[2:6]), 6.5)
        self.assertLessEqual(abs(ordered[8] - ordered[9]), 3.0)

    def test_index_uses_established_sections_and_reports_impedance(self):
        manifest_path = Path(
            "examples/extension-throat-angle-heuristics/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = render_index(
            manifest_path.parent.resolve(), manifest,
            {
                "candidates": [],
                "stages": [],
                "study_status": "development running",
                "runtime_active": True,
            },
        )
        for heading in (
            "Project range", "Design map", "Measured round parents",
            "Candidates", "Execution stages", "Sub-searches",
        ):
            self.assertIn(heading, output)
        self.assertIn("Throat-impedance score", output)
        self.assertIn("not included in the surface score", output)
        self.assertIn(
            "../control-decoupling/searches/three-factor-corner/"
            "30deg/250x250/candidates/candidate-000/bem/"
            "250x250x139.546_30_K2_N4_Report.html",
            output,
        )
        self.assertNotIn("candidates/search_report.html", output)
        self.assertNotIn(
            "30deg/250x250/search_report.html",
            output,
        )
        self.assertIn("<strong>development running</strong>study status", output)
        self.assertIn("Surface Δ vs parent", output)
        self.assertIn("Impedance Δ vs parent", output)
        self.assertIn("S Δ vs parent", output)
        self.assertIn(
            "Throat impedance v2.2.0: "
            "highest- and lowest-scoring parents", output)
        self.assertEqual(output.count("data-peak-normalized='1'"), 10)
        self.assertEqual(output.count("class='impedance-curve'"), 10)
        self.assertEqual(output.count("class='impedance-hit'"), 10)
        self.assertIn(
            "ranked by the experimental "
            "<em>throat-impedance diagnostic score</em>",
            output,
        )
        plotted_scores = [
            float(value) for value in re.findall(
                r"data-impedance-score='([^']+)'", output)
        ]
        self.assertEqual(len(plotted_scores), 10)
        self.assertEqual(plotted_scores, sorted(plotted_scores))
        self.assertEqual(
            [int(value) for value in re.findall(
                r"data-color-rank='([^']+)'", output)],
            list(range(10)),
        )
        hues = [
            float(value) for value in re.findall(
                r"class='impedance-curve' "
                r"style='stroke:hsl\(([^ ]+)", output)
        ]
        self.assertEqual(len(hues), 10)
        self.assertEqual(hues, sorted(hues))
        self.assertEqual(hues[0], 0.0)
        self.assertEqual(hues[-1], 120.0)
        self.assertIn("One continuous color scale covers all ten", output)
        self.assertGreaterEqual(output.count("Open report:"), 20)


if __name__ == "__main__":
    unittest.main()
