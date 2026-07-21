from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import yaml

from app.tools.export_horncad import solved_s
from app.tools.generate_coverage_s_grid import (
    DEFAULT_S_TARGETS,
    length_for_s,
    materialize_s_grid,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "mouth-size-coverage-grid" / "25deg" / "200x200"


class CoverageSGridTests(unittest.TestCase):
    def test_length_inversion_reaches_each_s_target(self) -> None:
        document = yaml.safe_load((SOURCE / "project.yaml").read_text())
        config = document["horncad_config"]
        global_config = config["global"]
        basis = config["horizontal_basis"]
        lengths = [length_for_s(config, target) for target in DEFAULT_S_TARGETS]

        self.assertEqual(lengths, sorted(lengths, reverse=True))
        for target, length in zip(DEFAULT_S_TARGETS, lengths):
            actual = solved_s(
                length,
                global_config["throat_radius"],
                basis["coverage_deg"],
                basis["k"],
                basis["n"],
                global_config["mouth_width"] / 2.0,
                global_config["throat_angle_deg"],
            )
            self.assertAlmostEqual(actual, target, places=4)

    def test_materialized_search_contains_the_uniform_nine_point_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "25deg" / "200x200"
            source.mkdir(parents=True)
            shutil.copy2(SOURCE / "project.yaml", source / "project.yaml")
            shutil.copy2(SOURCE / "search.yaml", source / "search.yaml")

            output = materialize_s_grid(source / "search.yaml", DEFAULT_S_TARGETS)
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]

            self.assertEqual(search["max_evaluations"], 9)
            self.assertEqual(search["initial_candidates"], 8)
            self.assertEqual(len(search["initial_pool"]), 8)
            self.assertEqual(search["derived_s_bounds"], [0.69, 3.01])
            self.assertTrue(all(
                item["values"]["k_h"] == 4.0
                and item["values"]["n_h"] == 10.0
                for item in search["initial_pool"]
            ))

            (output / "search_state.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                materialize_s_grid(source / "search.yaml", DEFAULT_S_TARGETS)


if __name__ == "__main__":
    unittest.main()
