from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import yaml

from app.tools.run_s_boundary_closure_program import (
    authored_sentinel, baseline_searches, close_baseline, closure_status,
    materialize_probe, next_probe_s,
)
from app.tools.run_bem_search import load_search


ROOT = Path(__file__).resolve().parents[1]


class SBoundaryClosureTests(unittest.TestCase):
    @staticmethod
    def points(*pairs: tuple[float, float]):
        return [(s, score, Path(f"{s}.yaml")) for s, score in pairs]

    def test_interior_winner_is_closed(self) -> None:
        status, best = closure_status(self.points((0.5, 80), (0.7, 90), (1.0, 85)))
        self.assertEqual((status, best), ("closed", 0.7))

    def test_low_boundary_moves_down_until_bracketed(self) -> None:
        status, best = closure_status(self.points((0.7, 90), (1.0, 85)))
        self.assertEqual((status, next_probe_s(status, best)), ("lower", 0.5))
        status, best = closure_status(self.points((0.5, 88), (0.7, 90), (1.0, 85)))
        self.assertEqual((status, best), ("closed", 0.7))

    def test_improving_boundary_continues_outward(self) -> None:
        status, best = closure_status(self.points((0.5, 92), (0.7, 90), (1.0, 85)))
        self.assertEqual((status, next_probe_s(status, best)), ("lower", 0.3))

    def test_only_uniform_baseline_names_are_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            angle = root / "30deg"
            for name in ("250x250-s-grid", "250x250-canonical-s",
                         "250x250-coupled-r01-s"):
                (angle / name).mkdir(parents=True)
            self.assertEqual([path.name for path in baseline_searches(root)],
                             ["250x250-s-grid"])

    def test_probe_preserves_baseline_controls_at_requested_s(self) -> None:
        baseline = (ROOT / "examples" / "mouth-size-coverage-grid" /
                    "25deg" / "250x250-s-grid")
        seed = baseline / "candidates" / "candidate-000" / "project.yaml"
        if not seed.exists():
            seed = baseline / "project.yaml"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "250x250-s-boundary-r01"
            materialize_probe(seed, baseline, output, 0.5)
            project = yaml.safe_load((output / "project.yaml").read_text())
            search = yaml.safe_load((output / "search.yaml").read_text())[
                "bem_candidate_search"]
            loaded, _, _ = load_search(output / "search.yaml")
        self.assertEqual(project["horncad_config"]["horizontal_basis"]["solved_s"], 0.5)
        self.assertEqual(search["max_evaluations"], 1)
        self.assertEqual(search["solver"]["workers"], 10)
        self.assertEqual(loaded["initial_candidates"], 0)

    def test_authored_sentinel_uses_far_edge_of_original_grid(self) -> None:
        baseline = (ROOT / "examples" / "mouth-size-coverage-grid" /
                    "25deg" / "250x250-s-grid")
        self.assertEqual(authored_sentinel(baseline), 3.0)

    def test_repairs_legacy_empty_probe_pool(self) -> None:
        baseline = (ROOT / "examples" / "mouth-size-coverage-grid" /
                    "25deg" / "250x250-s-grid")
        seed = baseline / "project.yaml"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "probe"
            materialize_probe(seed, baseline, output, 0.5)
            document = yaml.safe_load((output / "search.yaml").read_text())
            document["bem_candidate_search"]["initial_pool"] = []
            (output / "search.yaml").write_text(yaml.safe_dump(document))
            materialize_probe(seed, baseline, output, 0.5)
            loaded, _, _ = load_search(output / "search.yaml")
        self.assertNotIn("initial_pool", loaded)

    def test_geometry_rejected_probe_closes_admissible_s_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "30deg" / "300x300-s-grid"
            rejected = root / "30deg" / "300x300-s-boundary-r01"
            baseline.mkdir(parents=True)
            rejected.mkdir()
            (baseline / "search_state.json").write_text(json.dumps({
                "status": "complete", "candidates": [{
                    "id": "candidate-000", "status": "complete",
                    "derived": {"s_h": 2.5},
                    "surface_diagnostics": {"score": {"overall_percent": 80}},
                }],
            }))
            (rejected / "search_state.json").write_text(json.dumps({
                "status": "geometry-rejected", "geometry_rejection": {
                    "reason": "late radial growth", "derived": {"s_h": 3.0}},
            }))
            result = close_baseline(root, baseline)
        self.assertEqual(result["status"], "geometry-limited")
        self.assertEqual(result["best_s"], 2.5)
        self.assertEqual(result["rejected_s"], 3.0)


if __name__ == "__main__":
    unittest.main()
