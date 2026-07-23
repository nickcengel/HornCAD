import json
from pathlib import Path
import shutil
import subprocess
import unittest

from app.design_api import DesignApplication, DesignPoint, SupportStatus
from app.design_api.portable import evaluate


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "models/round_control_primary_v1"
AUGMENTED = ROOT / "models/round_control_augmented_v1"


@unittest.skipUnless((AUGMENTED / "model.json").is_file(),
                     "round-control release artifacts are not present")
class RoundControlModelTests(unittest.TestCase):
    def setUp(self):
        self.app = DesignApplication.load(AUGMENTED)

    def test_predict_exposes_seven_diagnostics_and_both_models(self):
        result = self.app.predict(DesignPoint.round(300, 40, 145, 4, 8))
        self.assertEqual(result.support, SupportStatus.SUPPORTED)
        self.assertEqual(len(result.diagnostics), 7)
        self.assertIn("throat_impedance_score", result.diagnostics)
        self.assertEqual(set(result.model_predictions), {
            "round_control_primary_v1", "round_control_augmented_v1"})
        self.assertTrue(result.nearest_evidence_ids)

    def test_invalid_geometry_is_rejected_and_extrapolation_is_visible(self):
        with self.assertRaisesRegex(ValueError, "invalid geometry"):
            self.app.predict(DesignPoint.round(250, 50, 60, 6, 16))
        result = self.app.predict(DesignPoint.round(300, 40, 175, 7, 8))
        self.assertEqual(result.support, SupportStatus.EXTRAPOLATED)
        self.assertTrue(result.warnings)

    def test_model_declares_impedance_independent_of_score_and_choice(self):
        model = json.loads((AUGMENTED / "model.json").read_text())
        policy = model["experimental_diagnostics"]["throat_impedance_score"]
        self.assertFalse(policy["included_in_surface_score"])
        self.assertFalse(policy["included_in_model_choice"])
        self.assertTrue(all(
            row["throat_impedance_excluded_from_choice"]
            for row in model["choice_by_cell"].values()))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_python_and_browser_evaluators_agree(self):
        model = json.loads((AUGMENTED / "model.json").read_text())
        design = DesignPoint.round(325, 42.5, 150, 4.5, 9)
        expected, _ = evaluate(model, design)
        script = """
const fs = require("fs");
const runtime = require("./app/browser/round_control_model.js");
const model = JSON.parse(fs.readFileSync(process.argv[1]));
const input = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(runtime.evaluateRoundControl(model, input)));
"""
        actual = json.loads(subprocess.check_output(
            ["node", "-e", script, str(AUGMENTED / "model.json"),
             json.dumps({"mouth_mm": 325, "coverage_deg": 42.5,
                         "length_mm": 150, "k": 4.5, "n": 9})],
            cwd=ROOT, text=True))
        for name in expected:
            self.assertAlmostEqual(actual[name], expected[name], places=11)


if __name__ == "__main__":
    unittest.main()
