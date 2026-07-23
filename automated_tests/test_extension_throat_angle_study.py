import unittest
from pathlib import Path
import json

from app.tools.run_extension_throat_angle_study import (
    DEVELOPMENT_STAGES,
    DIAGNOSTICS,
    _formula_prediction,
    _search_document,
    select_parents,
)
from app.tools.prepare_extension_throat_angle_study import candidate_design
from app.tools.report_extension_throat_angle_study import render_index


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

    def test_index_uses_established_sections_and_reports_impedance(self):
        manifest_path = Path(
            "examples/extension-throat-angle-heuristics/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = render_index(
            manifest_path.parent.resolve(), manifest,
            {"candidates": [], "stages": []},
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
            "30deg/250x250/search_report.html",
            output,
        )
        self.assertNotIn("candidates/search_report.html", output)


if __name__ == "__main__":
    unittest.main()
