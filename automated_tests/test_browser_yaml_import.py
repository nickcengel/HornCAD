from pathlib import Path
import json
import re
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
HTML = ROOT / "app" / "HornCAD.html"
EXAMPLE = ROOT / "examples" / "osse-400x280-reference" / "project.yaml"


class BrowserYamlImportTests(unittest.TestCase):
    def test_standalone_parser_reads_the_maintained_project(self) -> None:
        html = HTML.read_text()
        match = re.search(
            r"// BEGIN HORNCAD YAML PARSER.*?\n(.*?)\n  // END HORNCAD YAML PARSER",
            html, re.DOTALL)
        self.assertIsNotNone(match)
        script = match.group(1) + "\n" + (
            "const fs = require('fs');"
            "console.log(JSON.stringify(parseHorncadYaml(fs.readFileSync(process.argv[1], 'utf8'))));")
        result = subprocess.run(
            ["node", "-e", script, str(EXAMPLE)], check=True,
            capture_output=True, text=True)
        config = json.loads(result.stdout)["horncad_config"]
        self.assertEqual(config["type"], "HornCAD")
        self.assertEqual(config["version"], 2)
        self.assertEqual(config["global"]["mouth_width"], 400)
        self.assertEqual(config["horizontal_basis"]["coverage_deg"], 50)
        self.assertEqual(len(config["section_modifier"]["squareness_morph_spline"]), 2)

    def test_import_ui_and_apply_hook_are_present(self) -> None:
        html = HTML.read_text()
        self.assertIn("data-import-yaml-file", html)
        self.assertIn("applyHorncadConfig(parseHorncadYaml(await file.text()))", html)


if __name__ == "__main__":
    unittest.main()
