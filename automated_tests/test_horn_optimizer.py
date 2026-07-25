from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from app.horn_optimizer import (
    HornOptimizer, load_optimizer_config, rank_measurements,
)
from app.horn_optimizer.optimizer import coordinate_hash, proposal_hash
from app.horn_optimizer.optimizer import _transfer_guidance


ROOT = Path(__file__).parents[1]
SEED = (
    ROOT / "examples/non-round-transfer-study/searches"
    / "d1-elliptical-weighted/project.yaml"
)


class FakeQueue:
    def __init__(self, score=lambda path: 80.0):
        self.calls = []
        self.score = score

    def __call__(self, paths, runtime, **kwargs):
        self.calls.append((list(paths), runtime, kwargs))
        for path in paths:
            directory = path.parent
            candidate = directory / "candidates" / "candidate-000"
            (candidate / "bem").mkdir(parents=True, exist_ok=True)
            (candidate / "bem" / "responses.npz").write_bytes(b"mock")
            state = {
                "status": "complete",
                "candidates": [{
                    "id": "candidate-000",
                    "status": "complete",
                    "surface_diagnostics": {"score": {
                        "version": "v2.3",
                        "overall_percent": self.score(path),
                    }},
                    "throat_impedance_diagnostics": {
                        "diagnostic_version": "2.3.0",
                        "overall_percent": 70.0,
                    },
                }],
            }
            (directory / "search_state.json").write_text(
                json.dumps(state), encoding="utf-8")
        return {"status": "complete"}


class HornOptimizerTests(unittest.TestCase):
    def config(self, root: Path, *, max_simulations=8,
               approval_mode="autonomous", seed=False, shape="round"):
        document = {"horn_optimizer": {
            "version": 1,
            "output_dir": "run",
            "intent": {
                "horizontal_coverage_deg": 50,
                "vertical_coverage_deg": 35,
            },
            "throat_angle_deg": 6,
            "mouth_shape": shape,
            "mouth": {"width_mm": 400, "height_mm": 280},
            "sag_axes": "none",
            "sag_mm": 0,
            "max_simulations": max_simulations,
            "approval_mode": approval_mode,
        }}
        if seed:
            document["horn_optimizer"]["seed_yaml"] = str(SEED)
        path = root / "optimizer.yaml"
        path.write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return load_optimizer_config(path)

    def preflight(self):
        return patch(
            "app.horn_optimizer.optimizer.run_search",
            return_value={
                "status": "preflight",
                "candidates": [{"status": "preflight"}],
            },
        )

    def test_default_ranking_uses_half_point_surface_shortlist(self):
        rows = [
            {"status": "complete", "coordinate_hash": "a",
             "surface_score_v2_3": 90.0,
             "throat_impedance_score_v2_3_0": 70.0},
            {"status": "complete", "coordinate_hash": "b",
             "surface_score_v2_3": 89.5,
             "throat_impedance_score_v2_3_0": 85.0},
            {"status": "complete", "coordinate_hash": "c",
             "surface_score_v2_3": 89.49,
             "throat_impedance_score_v2_3_0": 99.0},
        ]
        ranked = rank_measurements(rows)
        self.assertEqual([row["coordinate_hash"] for row in ranked], [
            "b", "a", "c"])

    def test_hashes_are_deterministic_and_lineage_sensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(self.config(Path(temp)))
            values = optimizer._baseline_values()
            first = coordinate_hash(optimizer.config, values)
            second = coordinate_hash(optimizer.config, dict(reversed(
                list(values.items()))))
            self.assertEqual(first, second)
            self.assertEqual(
                proposal_hash(first, 1, "h-axis", "parent"),
                proposal_hash(first, 1, "h-axis", "parent"))
            self.assertNotEqual(
                proposal_hash(first, 1, "h-axis", "parent"),
                proposal_hash(first, 1, "v-axis", "parent"))

    def test_measured_transfer_result_widens_near_failed_square_region(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "transfer.json"
            result.write_text(json.dumps({
                "promotion": {
                    "common_length_rule": "s-balanced",
                    "wider_first_round_intents": ["L1"],
                },
                "equal_hv_square_summary": {
                    "median_surface_delta_from_round_points": -1.25,
                },
                "locked_evidence": [{
                    "source_intent_id": "L1",
                    "mouth_width_mm": 400,
                    "mouth_height_mm": 280,
                    "horizontal_coverage_deg": 50,
                    "vertical_coverage_deg": 35,
                }],
                "content_sha256": "measured",
            }), encoding="utf-8")
            config = self.config(root, shape="square")
            with patch(
                "app.horn_optimizer.optimizer.TRANSFER_RESULTS", result,
            ):
                guidance = _transfer_guidance(config)
                optimizer = HornOptimizer(config, response_library=[])
                state = optimizer.initialize()
                pool = optimizer._round_one_pool(state)
            self.assertEqual(guidance["common_length_rule"], "s-balanced")
            self.assertTrue(guidance["wider_first_round"])
            self.assertTrue(any(
                "square-corner" in warning
                for warning in guidance["support_warnings"]))
            base = optimizer._baseline_values()
            h_low = next(
                row for row in pool if row["branch"] == "h-axis-k-low")
            self.assertAlmostEqual(
                base["k_h"]-h_low["values"]["k_h"], 1.25)

    def test_seed_is_mandatory_first_measured_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = FakeQueue()
            optimizer = HornOptimizer(
                self.config(Path(temp), seed=True),
                response_library=[], queue_runner=queue)
            with self.preflight():
                state = optimizer.step()
            baseline = state["candidates"][0]
            self.assertEqual(baseline["branch"], "seed-baseline")
            self.assertEqual(baseline["status"], "complete")
            self.assertEqual(state["accounting"]["solver_evaluations"], 1)
            self.assertEqual(len(queue.calls), 1)

    def test_exact_library_reuse_consumes_no_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))
            probe = HornOptimizer(config, response_library=[])
            values = probe._baseline_values()
            library = [{
                "coordinate_hash": coordinate_hash(config, values),
                "surface_score_v2_3": 88,
                "throat_impedance_score_v2_3_0": 77,
                "response_path": "retained/responses.npz",
            }]
            queue = FakeQueue()
            optimizer = HornOptimizer(
                config, response_library=library, queue_runner=queue)
            state = optimizer.step()
            self.assertEqual(state["candidates"][0]["status"], "reused")
            self.assertEqual(state["accounting"]["solver_evaluations"], 0)
            self.assertEqual(state["accounting"]["exact_library_reuses"], 1)
            self.assertFalse(queue.calls)
            self.assertTrue(
                (config.output_dir / "winning_project.yaml").is_file())

    def test_fixed_intent_shape_and_sag_are_materialized(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(
                self.config(Path(temp)), response_library=[])
            candidate = optimizer.propose()[0]
            project_path, _search, _project = optimizer.materialize(candidate)
            config = yaml.safe_load(
                project_path.read_text())["horncad_config"]
            self.assertEqual(
                config["operating_intent"]["horizontal_coverage_deg"], 50)
            self.assertEqual(config["horizontal_basis"]["coverage_deg"], 50)
            self.assertEqual(config["vertical_basis"]["coverage_deg"], 35)
            self.assertEqual(config["global"]["throat_angle_deg"], 6)
            self.assertEqual(
                config["section_modifier"]["mouth_squareness"], 0)
            self.assertFalse(config["global"]["mouth_sag_h_enabled"])
            self.assertFalse(config["global"]["mouth_sag_v_enabled"])

    def test_hard_cap_and_stage_aware_batch_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = FakeQueue()
            optimizer = HornOptimizer(
                self.config(Path(temp), max_simulations=1),
                response_library=[], queue_runner=queue)
            with self.preflight():
                state = optimizer.step()
            self.assertEqual(state["status"], "budget-exhausted")
            self.assertEqual(state["accounting"]["solver_evaluations"], 1)
            _paths, _runtime, kwargs = queue.calls[0]
            self.assertEqual(kwargs["numcalc_processes"], 20)
            self.assertLessEqual(kwargs["queue_workers"], 4)

    def test_mocked_second_round_improves_and_keeps_independent_axes(self):
        with tempfile.TemporaryDirectory() as temp:
            def score(path):
                search = yaml.safe_load(path.read_text())[
                    "bem_candidate_search"]
                branch = search["horn_optimizer"]["branch"]
                return 86.0 if branch.startswith("h-axis") else 80.0

            queue = FakeQueue(score)
            optimizer = HornOptimizer(
                self.config(Path(temp), max_simulations=8),
                response_library=[], queue_runner=queue)
            with self.preflight():
                first = optimizer.step()
                second = optimizer.step()
            self.assertEqual(
                first["candidates"][0]["surface_score_v2_3"], 80)
            self.assertEqual(
                optimizer.ranking(second)[0]["surface_score_v2_3"], 86)
            round_one = [
                row for row in second["candidates"] if row["round"] == 1]
            self.assertLessEqual(len(round_one), 4)
            self.assertTrue(any(
                row["values"]["k_h"] != row["values"]["k_v"]
                for row in round_one))
            self.assertEqual(
                second["response_approximation"]["portable_prediction"],
                False)

    def test_interrupted_evaluation_retries_without_duplicate_charge(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))

            def interrupt(*_args, **_kwargs):
                raise RuntimeError("interrupted")

            optimizer = HornOptimizer(
                config, response_library=[], queue_runner=interrupt)
            with self.preflight():
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    optimizer.step()
            state = optimizer.load_state()
            self.assertEqual(state["accounting"]["solver_evaluations"], 1)
            self.assertEqual(state["candidates"][0]["status"], "interrupted")

            resumed = HornOptimizer(
                config, response_library=[], queue_runner=FakeQueue())
            with self.preflight():
                state = resumed.step()
            self.assertEqual(state["accounting"]["solver_evaluations"], 1)
            self.assertEqual(state["accounting"]["interrupted_retries"], 1)
            self.assertEqual(state["candidates"][0]["status"], "complete")

    def test_geometry_rejection_does_not_consume_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(
                self.config(Path(temp)), response_library=[],
                queue_runner=FakeQueue())
            rejected = patch(
                "app.horn_optimizer.optimizer.run_search",
                return_value={
                    "status": "preflight",
                    "candidates": [{
                        "status": "rejected",
                        "reason": "invalid geometry",
                    }],
                },
            )
            with rejected:
                state = optimizer.step()
            self.assertEqual(state["accounting"]["solver_evaluations"], 0)
            self.assertEqual(state["accounting"]["geometry_rejections"], 1)

    def test_approval_gate_and_dry_run_materialization(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(
                self.config(Path(temp), approval_mode="approval-gated"),
                response_library=[], queue_runner=FakeQueue())
            proposed = optimizer.propose()
            self.assertEqual(proposed[0]["status"], "awaiting_approval")
            self.assertEqual(optimizer.approve(), 1)
            with self.preflight():
                state = optimizer.execute_pending(dry_run=True)
            self.assertEqual(state["candidates"][0]["status"], "dry-run")
            self.assertEqual(state["accounting"]["solver_evaluations"], 0)
            self.assertTrue(Path(
                state["candidates"][0]["project_path"]).is_file())

    def test_live_report_is_sortable(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(self.config(Path(temp)))
            state = optimizer.initialize()
            document = optimizer.render_report(state).read_text()
            self.assertIn("http-equiv='refresh' content='5'", document)
            self.assertIn('table class="sortable"', document)
            self.assertIn('header.onclick', document)

    def test_live_refresh_harvests_completed_batch_member(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(
                self.config(Path(temp)), response_library=[])
            candidate = optimizer.propose()[0]
            _project, search, _document = optimizer.materialize(candidate)
            state = optimizer.load_state()
            state["candidates"][0]["status"] = "running"
            optimizer.save_state(state)
            FakeQueue()([search], Path(temp) / "runtime.json")

            optimizer._refresh_from_disk()

            refreshed = optimizer.load_state()
            self.assertEqual(
                refreshed["candidates"][0]["status"], "complete")
            report = (optimizer.output / "index.html").read_text()
            self.assertIn(">complete</td>", report)

    def test_early_stop_requires_all_three_conditions_then_confirms(self):
        with tempfile.TemporaryDirectory() as temp:
            optimizer = HornOptimizer(
                self.config(Path(temp), max_simulations=8),
                response_library=[], queue_runner=FakeQueue())
            with self.preflight():
                state = optimizer.step()
            winner = optimizer.ranking(state)[0]
            state["step_sizes"] = {
                "length_fraction": 0.02,
                "extension_mm": 5,
                "k": 0.25,
                "n": 1,
                "mouth_mm": 5,
                "sag_mm": 2,
            }
            state["non_improving_rounds"] = 1
            state["early_stopping"]["no_feasible_heuristic_branch"] = True
            state["rounds"].append({
                "round": state["next_round"],
                "proposal_hashes": [winner["proposal_hash"]],
                "status": "proposed",
                "best_before": winner["proposal_hash"],
            })
            optimizer._close_round(state)
            self.assertTrue(
                state["early_stopping"]["contracted_local_search"])
            self.assertTrue(
                state["early_stopping"]["two_non_improving_rounds"])
            self.assertTrue(
                state["early_stopping"]["no_feasible_heuristic_branch"])
            self.assertEqual(state["status"], "confirmation-pending")
            self.assertEqual(
                state["candidates"][-1]["branch"], "final-confirmation")


if __name__ == "__main__":
    unittest.main()
