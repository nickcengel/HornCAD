from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.tools.report_round_control_parameter_maps import render


class RoundControlParameterMapTests(unittest.TestCase):
    def test_report_contains_four_maps_without_recipe_grid(self):
        manifest = json.loads(Path(
            "examples/extension-throat-angle-heuristics/manifest.json"
        ).read_text(encoding="utf-8"))
        output = render(manifest)
        for title in ("Length", "K", "N", "S"):
            self.assertIn(f"<h2>{title}</h2>", output)
        self.assertEqual(output.count("class='heatmap'"), 4)
        self.assertEqual(output.count("class='map-cell'"), 100)
        self.assertNotIn("Coupled recipe map", output)
        self.assertNotIn("class='glyph-cell'", output)
        self.assertIn("cells with unequal", output)
        self.assertIn("r = 0.904", output)
        self.assertIn("<strong>20 / 25</strong>", output)
        self.assertIn("Why this is not a 3D surface", output)
        self.assertNotIn("canonical", output.lower())
        self.assertNotIn("normalized length", output.lower())
        self.assertNotIn("length_factor", output)


if __name__ == "__main__":
    unittest.main()
