from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from app.tools.run_bem_search import (
    VARIABLES,
    adaptive_kn_pruning_decision, adaptive_pruning_decision,
    candidate_artifact_stem, candidate_distance, candidate_trait, candidate_traits,
    geometry_feasibility,
    geometry_feature_vector, inferior_to_seed_probability, learned_lever_effects,
    load_search, materialize_candidate, pareto_indices, propose_vector,
    next_kn_closure_candidate, requeue_failed_candidates, sampling_stability,
    required_initial_probe, run_search, seed_values, sensitivity_sampling_decision,
    write_report,
)


ROOT = Path(__file__).parents[1]
SEARCH = (ROOT / "examples" / "osse-400x280-reference" / "bem-search" /
          "search.yaml")
ROUND2_SEARCH = SEARCH.parent / "round-2" / "search.yaml"


class BEMSearchTests(unittest.TestCase):
    def test_sensitivity_policy_skips_flat_optional_point(self) -> None:
        search = {
            "intended_coverage_h_deg": 30, "intended_coverage_v_deg": 30,
            "s_sensitivity_sampling": {
                "enabled": True, "mandatory_s": [0.7, 1.3, 1.9, 2.5, 3.0],
            },
            "initial_candidates": 6,
            "initial_pool": [{"label": f"coverage 30°, S={s}", "values": {}}
                             for s in (0.7, 1.3, 1.9, 2.5, 3.0, 1.0)],
        }
        samples = ((0.7, 80), (1.3, 80.4), (1.9, 88), (2.5, 84), (3.0, 82))
        records = [{
            "status": "complete", "derived": {"s_h": s, "s_v": s},
            "surface_diagnostics": {"score": {"overall_percent": score}},
        } for s, score in samples]

        decision = sensitivity_sampling_decision(
            search, records, {}, {"s_h": 1.0, "s_v": 1.0})

        self.assertIsNotNone(decision)
        self.assertIn("insensitive", decision["reason"])

    def test_required_boundary_probe_bypasses_only_its_authored_point(self) -> None:
        search = {"initial_pool": [
            {"label": "coverage 50°, S=3.75"},
            {"label": "coverage 50°, S=4", "required": True},
        ]}
        self.assertFalse(required_initial_probe(search, 1, "initial-curated"))
        self.assertTrue(required_initial_probe(search, 2, "initial-curated"))
        self.assertFalse(required_initial_probe(search, 2, "surrogate"))

    def test_kn_closure_tests_missing_diagonal_around_best(self) -> None:
        search = {"adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.5, "initial_n_step": 5,
            "minimum_k": 1, "maximum_k": 7,
            "minimum_n": 2, "maximum_n": 40,
        }}
        def record(k: float, n: float, score: float) -> dict:
            return {"status": "complete",
                    "values": {"k_h": k, "k_v": k, "n_h": n, "n_v": n},
                    "surface_diagnostics": {"score": {"overall_percent": score}}}
        records = [record(3.5, 5, 77), record(3, 5, 76),
                   record(4, 5, 76), record(3.5, 2, 70),
                   record(3.5, 10, 75), record(3, 2, 69),
                   record(4, 2, 68)]
        closure: dict = {}

        values, label = next_kn_closure_candidate(search, records, closure)

        self.assertEqual((values["k_h"], values["n_h"]), (3.0, 10.0))
        self.assertIn("closure", label)

    def test_kn_closure_refines_spacing_then_closes(self) -> None:
        search = {"adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.25, "initial_n_step": 1,
            "minimum_k_step": 0.25, "minimum_n_step": 1,
            "minimum_k": 1, "maximum_k": 7,
            "minimum_n": 2, "maximum_n": 40,
        }}
        records = []
        for k in (3.25, 3.5, 3.75):
            for n in (4, 5, 6):
                score = 80 - abs(k - 3.5) - abs(n - 5)
                records.append({"status": "complete",
                    "values": {"k_h": k, "k_v": k, "n_h": n, "n_v": n},
                    "surface_diagnostics": {"score": {"overall_percent": score}}})
        closure: dict = {}

        self.assertIsNone(next_kn_closure_candidate(search, records, closure))
        self.assertEqual(closure["status"], "closed")

    def test_kn_closure_brackets_n_five_above_and_below(self) -> None:
        search = {"adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.25, "initial_n_step": 5,
            "minimum_k_step": 0.25, "minimum_n_step": 1,
            "minimum_k": 1, "maximum_k": 7,
            "minimum_n": 2, "maximum_n": 40,
        }}

        def record(k: float, n: float, score: float) -> dict:
            return {"status": "complete",
                    "values": {"k_h": k, "k_v": k, "n_h": n, "n_v": n},
                    "surface_diagnostics": {"score": {"overall_percent": score}}}

        records = []
        for k in (3.75, 4.0, 4.25):
            records.extend((record(k, 5, 90 - abs(k - 4)),
                            record(k, 10, 85 - abs(k - 4))))
        closure: dict = {}

        values, _ = next_kn_closure_candidate(search, records, closure)
        self.assertEqual((values["k_h"], values["n_h"]), (4.0, 2.5))

        records.append(record(4, 2.5, 86))
        values, _ = next_kn_closure_candidate(search, records, closure)
        self.assertEqual((values["k_h"], values["n_h"]), (4.0, 7.5))

    def test_bad_high_s_high_n_result_rescues_k_with_lower_n_first(self) -> None:
        search = {"adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.5, "initial_n_step": 5,
            "minimum_k_step": 0.25, "minimum_n_step": 1,
            "minimum_k": 1, "maximum_k": 7,
            "minimum_n": 2, "maximum_n": 40,
        }}

        def record(k: float, n: float, s: float, score: float) -> dict:
            return {
                "status": "complete",
                "values": {"k_h": k, "k_v": k, "n_h": n, "n_v": n},
                "derived": {"s_h": s, "s_v": s},
                "surface_diagnostics": {"score": {"overall_percent": score}},
            }

        records = [record(4, 6, 1.5, 88), record(3.5, 10, 2.2, 82)]
        closure: dict = {}

        values, label = next_kn_closure_candidate(search, records, closure)

        self.assertEqual((values["k_h"], values["n_h"]), (3.5, 8.0))
        self.assertIn("rescue", label)
        self.assertEqual(closure["last_rescue"]["from_n"], 10)

    def test_rescue_does_not_fire_without_thresholds(self) -> None:
        search = {"adaptive_kn_closure": {
            "enabled": True, "initial_k_step": 0.5, "initial_n_step": 5,
            "minimum_k_step": 0.25, "minimum_n_step": 1,
            "minimum_k": 1, "maximum_k": 7,
            "minimum_n": 2, "maximum_n": 40,
        }}
        records = [{
            "status": "complete",
            "values": {"k_h": 4, "k_v": 4, "n_h": 10, "n_v": 10},
            "derived": {"s_h": 1.9, "s_v": 1.9},
            "surface_diagnostics": {"score": {"overall_percent": 88}},
        }, {
            "status": "complete",
            "values": {"k_h": 3.5, "k_v": 3.5, "n_h": 10, "n_v": 10},
            "derived": {"s_h": 2.2, "s_v": 2.2},
            "surface_diagnostics": {"score": {"overall_percent": 86}},
        }]
        closure: dict = {}

        _, label = next_kn_closure_candidate(search, records, closure)

        self.assertNotIn("rescue", label)

    def test_kn_pruning_waits_for_local_cross_then_skips_bad_extreme(self) -> None:
        search = {
            "adaptive_kn": {"enabled": True},
            "geometry_context": {"mouth_width_mm": 350, "mouth_height_mm": 350},
        }
        def record(k: float, n: float, score: float) -> dict:
            return {"status": "complete", "values": {"k_h": k, "n_h": n},
                    "surface_diagnostics": {"score": {"overall_percent": score}}}
        records = [record(4, 10, 88), record(3.5, 10, 82)]
        values = {"k_h": 3, "k_v": 3, "n_h": 10, "n_v": 10}

        decision = adaptive_kn_pruning_decision(search, records, values)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_k"], 3)
        records[-1]["surface_diagnostics"]["score"]["overall_percent"] = 87
        self.assertIsNone(adaptive_kn_pruning_decision(search, records, values))

    def test_kn_pruning_uses_measured_axis_effects_for_interactions(self) -> None:
        search = {
            "adaptive_kn": {"enabled": True},
            "geometry_context": {"mouth_width_mm": 350, "mouth_height_mm": 350},
        }
        def record(k: float, n: float, score: float) -> dict:
            return {"status": "complete", "values": {"k_h": k, "n_h": n},
                    "surface_diagnostics": {"score": {"overall_percent": score}}}
        records = [record(4, 10, 88), record(4.5, 10, 82), record(4, 15, 83)]
        values = {"k_h": 4.5, "k_v": 4.5, "n_h": 15, "n_v": 15}

        self.assertIsNotNone(adaptive_kn_pruning_decision(search, records, values))

    def test_adaptive_pruning_skips_only_confidently_declining_s_tail(self) -> None:
        search = {
            "initial_candidates": 8,
            "initial_pool": [
                {"label": f"uniform S={s:g}", "values": {}}
                for s in (1.0, 1.3, 1.6, 1.9, 2.2, 2.5, 2.8, 3.0)
            ],
            "adaptive_pruning": {"enabled": True},
            "geometry_context": {"mouth_width_mm": 300, "mouth_height_mm": 300},
        }
        records = []
        for s, score in zip((0.7, 1.0, 1.3, 1.6, 1.9),
                            (82.0, 80.0, 76.0, 71.0, 66.0)):
            records.append({
                "status": "complete", "derived": {"s_h": s, "s_v": s},
                "surface_diagnostics": {"score": {"overall_percent": score}},
            })
        decision = adaptive_pruning_decision(
            search, records, {"length_mm": 100}, {"s_h": 2.2, "s_v": 2.2})
        self.assertIsNotNone(decision)
        self.assertLess(decision["optimistic_score"], decision["threshold_score"])

        records[-1]["surface_diagnostics"]["score"]["overall_percent"] = 79.0
        self.assertIsNone(adaptive_pruning_decision(
            search, records, {"length_mm": 100}, {"s_h": 2.2, "s_v": 2.2}))

    def test_adaptive_pruning_waits_for_five_real_results(self) -> None:
        search = {
            "initial_candidates": 5,
            "initial_pool": [
                {"label": f"uniform S={s:g}", "values": {}}
                for s in (1.0, 1.3, 1.6, 1.9, 2.2)
            ],
            "geometry_context": {"mouth_width_mm": 300, "mouth_height_mm": 300},
        }
        records = [{
            "status": "complete", "derived": {"s_h": s, "s_v": s},
            "surface_diagnostics": {"score": {"overall_percent": score}},
        } for s, score in zip((0.7, 1.0, 1.3, 1.6), (80, 70, 60, 50))]
        self.assertIsNone(adaptive_pruning_decision(
            search, records, {"length_mm": 100}, {"s_h": 1.9, "s_v": 1.9}))

    def test_bracketed_winner_prunes_after_three_measured_declines(self) -> None:
        search = {
            "initial_candidates": 14,
            "initial_pool": [
                {"label": f"coverage 50°, S={s:g}", "values": {}}
                for s in np.arange(0.75, 4.01, 0.25)
            ],
            "adaptive_pruning": {"enabled": True},
        }
        scores = (63.3, 73.2, 79.6, 81.9, 83.2, 84.5, 85.8,
                  86.6, 86.8, 86.2, 85.2, 83.7)
        records = [{
            "status": "complete", "derived": {"s_h": s, "s_v": s},
            "surface_diagnostics": {"score": {"overall_percent": score}},
        } for s, score in zip(np.arange(0.5, 3.26, 0.25), scores)]

        decision = adaptive_pruning_decision(
            search, records, {"length_mm": 94}, {"s_h": 3.5, "s_v": 3.5})

        self.assertIsNotNone(decision)
        self.assertEqual(decision["best_observed_s"], 2.5)
        self.assertIn("bracketed", decision["reason"])

    def test_adaptive_pruning_recognizes_intermediate_coverage_labels(self) -> None:
        search = {
            "initial_candidates": 7,
            "initial_pool": [
                {"label": f"coverage 40°, S={s:g}, L=100 mm", "values": {}}
                for s in (0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25)
            ],
            "adaptive_pruning": {"enabled": True},
            "geometry_context": {"mouth_width_mm": 300, "mouth_height_mm": 300},
        }
        records = [{
            "status": "complete", "derived": {"s_h": s, "s_v": s},
            "surface_diagnostics": {"score": {"overall_percent": score}},
        } for s, score in ((0.5, 78), (0.75, 86), (1.0, 87.4),
                           (1.25, 87.2), (1.5, 86.2), (1.75, 84.9),
                           (2.0, 83.2))]

        decision = adaptive_pruning_decision(
            search, records, {"length_mm": 114}, {"s_h": 2.25, "s_v": 2.25})

        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_s"], 2.25)

    def test_failed_candidate_retry_only_queues_failed_records(self) -> None:
        state = {"candidates": [
            {"id": "candidate-000", "status": "complete"},
            {"id": "candidate-001", "status": "failed", "reason": "old"},
            {"id": "candidate-002", "status": "queued"},
        ]}

        self.assertEqual(requeue_failed_candidates(state), 1)
        self.assertEqual(
            [candidate["status"] for candidate in state["candidates"]],
            ["complete", "queued", "queued"])
        self.assertIn("retrying", state["candidates"][1]["reason"])

    def test_candidate_artifact_stem_for_matching_axes(self) -> None:
        _, _, seed = load_search(SEARCH)
        config = seed["horncad_config"]
        config["global"].update(mouth_width=250, mouth_height=250, length=179,
                                conical_extension_length=0)
        config["horizontal_basis"].update(coverage_deg=35, k=4, n=10)
        config["vertical_basis"].update(coverage_deg=35, k=4, n=10)
        self.assertEqual(candidate_artifact_stem(seed),
                         "250x250x179_35_K4_N10")

    def test_candidate_artifact_stem_for_independent_axes_and_extension(self) -> None:
        _, _, seed = load_search(SEARCH)
        config = seed["horncad_config"]
        config["global"].update(mouth_width=250, mouth_height=250, length=179,
                                conical_extension_length=12)
        config["horizontal_basis"].update(coverage_deg=35, k=4, n=10)
        config["vertical_basis"].update(coverage_deg=25, k=3, n=8)
        self.assertEqual(candidate_artifact_stem(seed),
                         "250x250x179_E12_H35_K4_N10_V25_K3_N8")

    def test_search_schema_and_materialization_preserve_intent(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["intended_coverage_h_deg"] = 50.0
        search["intended_coverage_v_deg"] = 35.0
        values = seed_values(seed)
        values.update(length_mm=315, extension_mm=10,
                      osse_coverage_h_deg=55, osse_coverage_v_deg=40)
        candidate, derived = materialize_candidate(seed, values, search)
        config = candidate["horncad_config"]
        self.assertEqual(config["global"]["length"], 315)
        self.assertEqual(config["horizontal_basis"]["coverage_deg"], 55)
        self.assertEqual(config["operating_intent"]["horizontal_coverage_deg"], 50)
        feasible, reason = geometry_feasibility(derived)
        self.assertFalse(feasible)
        self.assertIn("negative", reason)

    def test_zero_s_is_feasible_but_negative_s_is_not(self) -> None:
        derived = {"s_h": 0.0, "s_v": 0.0, "other": 1.0}
        self.assertEqual(geometry_feasibility(derived), (True, None))
        derived["s_h"] = -1e-6
        feasible, reason = geometry_feasibility(derived)
        self.assertFalse(feasible)
        self.assertIn("negative", reason)

    def test_seed_then_space_filling_proposals_are_bounded(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["seed_values"] = seed_values(seed)
        config = seed["horncad_config"]
        search["geometry_context"] = {
            "throat_radius_mm": config["global"]["throat_radius"],
            "throat_angle_deg": config["global"]["throat_angle_deg"],
            "mouth_width_mm": config["global"]["mouth_width"],
            "mouth_height_mm": config["global"]["mouth_height"],
            "n_h": config["horizontal_basis"]["n"],
            "n_v": config["vertical_basis"]["n"],
        }
        seed_vector, source = propose_vector(search, [], 0)
        self.assertEqual(source, "seed")
        self.assertTrue(np.all((seed_vector >= 0) & (seed_vector <= 1)))
        sample, source = propose_vector(search, [], 1)
        self.assertEqual(source, "initial-length-N-family")
        self.assertTrue(np.all((sample >= 0) & (sample <= 1)))
        values = {name: search["bounds"][name][0] + sample[index] *
                  (search["bounds"][name][1] - search["bounds"][name][0])
                  for index, name in enumerate(VARIABLES)}
        self.assertIsNotNone(geometry_feature_vector(search, values))
        self.assertEqual(values["extension_mm"], search["seed_values"]["extension_mm"])

    def test_curated_pool_preserves_labels_and_fixed_extension(self) -> None:
        search, _, seed = load_search(ROUND2_SEARCH)
        search["seed_values"] = seed_values(seed)
        vector, source = propose_vector(search, [], 1)
        self.assertEqual(source, "initial-curated")
        values = {name: search["bounds"][name][0] + vector[index] *
                  (search["bounds"][name][1] - search["bounds"][name][0])
                  for index, name in enumerate(VARIABLES)}
        self.assertEqual(values["extension_mm"], 0)
        self.assertEqual(search["initial_pool"][0]["label"], "Moderate-S N low")

    def test_inferior_screen_waits_for_seed_and_sufficient_learning(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["seed_values"] = seed_values(seed)
        self.assertEqual(inferior_to_seed_probability(
            search, [], np.full(len(VARIABLES), 0.5)), 0)

    def test_lever_effects_recover_direction_from_completed_probes(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["seed_values"] = seed_values(seed)
        records = []
        for index, length in enumerate((270, 300, 330, 315)):
            values = dict(search["seed_values"], length_mm=length)
            score = 80 + (length - 300) / 10
            records.append({"status": "complete", "values": values,
                            "proposal_source": "seed" if index == 1 else "probe",
                            "crossover_loading_percent": score,
                            "diagnostics": {"combined": {
                                "coverage_match_percent": score,
                                "coverage_smoothness_percent": score,
                                "waist_stability_percent": score,
                                "window_uniformity_percent": score}}})
        effects = learned_lever_effects(search, records)
        self.assertGreater(effects["length_mm"]["coverage_match_percent"], 0)

    def test_sampling_stability_accepts_frequency_invariant_patterns(self) -> None:
        frequencies = np.geomspace(450, 8000, 49)
        angles = np.linspace(-90, 90, 181)
        horizontal = np.tile(-6 * np.abs(angles) / 50, (len(frequencies), 1))
        vertical = np.tile(-6 * np.abs(angles) / 35, (len(frequencies), 1))
        run = {"frequencies": frequencies, "angles": angles,
               "horizontal": horizontal, "vertical": vertical,
               "impedance": np.ones(len(frequencies), dtype=complex),
               "normalized_impedance": np.ones(len(frequencies), dtype=complex),
               "intended_coverages": {"horizontal": 50, "vertical": 35}}
        stability = sampling_stability(run, np.geomspace(500, 8000, 193), 500, 2)
        self.assertEqual(stability["status"], "stable")
        self.assertLess(stability["maximum_delta_points"], 0.01)

    def test_pareto_set_ignores_informational_loading(self) -> None:
        def record(scores: tuple[float, ...], loading: float) -> dict:
            combined = dict(zip(("coverage_match_percent",
                                 "coverage_smoothness_percent",
                                 "waist_stability_percent",
                                 "window_uniformity_percent"),
                                scores))
            return {"status": "complete", "crossover_loading_percent": loading,
                    "diagnostics": {"combined": combined}}
        records = [record((80, 80, 80, 80), 100),
                   record((70, 70, 70, 70), 100),
                   record((95, 95, 95, 95), 90)]
        self.assertEqual(pareto_indices(records), {2})

    def test_candidate_distance_uses_normalized_authored_parameters(self) -> None:
        search, _, seed = load_search(SEARCH)
        values = seed_values(seed)
        records = [{"values": values}]
        self.assertEqual(candidate_distance(values, records, search["bounds"]), 0)
        changed = dict(values, length_mm=values["length_mm"] + 9)
        self.assertGreater(candidate_distance(changed, records, search["bounds"]), 0)

    def test_candidate_trait_reports_largest_departure_from_seed(self) -> None:
        search, _, seed = load_search(SEARCH)
        values = seed_values(seed)
        self.assertEqual(candidate_trait(values, values, search["bounds"]), "Seed design")
        changed = dict(values, k_h=60)
        self.assertEqual(candidate_trait(changed, values, search["bounds"]),
                         "High horizontal K")

    def test_duplicate_primary_traits_gain_secondary_traits(self) -> None:
        search, _, seed = load_search(SEARCH)
        values = seed_values(seed)
        first = dict(values, k_h=60, extension_mm=10)
        second = dict(values, k_h=60, extension_mm=0,
                      osse_coverage_v_deg=20)
        labels = candidate_traits([{"values": first}, {"values": second}],
                                  values, search["bounds"])
        self.assertEqual(len(set(labels)), 2)
        self.assertTrue(all(" · " in label for label in labels))

    @patch("app.tools.run_bem_search.export_candidate_stl")
    def test_dry_run_materializes_feasible_initial_candidates(self, export_stl) -> None:
        def fake_export(_project: Path, candidate_dir: Path,
                        artifact_stem: str | None = None) -> Path:
            path = candidate_dir / "candidate-surface.STL"
            path.write_bytes(b"test stl")
            return path
        export_stl.side_effect = fake_export
        with tempfile.TemporaryDirectory() as temp:
            state = run_search(SEARCH, Path(temp), None, dry_run=True)
            self.assertEqual(state["status"], "preflight")
            self.assertTrue((Path(temp) / "search_report.html").is_file())
            report = (Path(temp) / "search_report.html").read_text()
            self.assertNotIn("Search range", report)
            self.assertNotIn("Learned lever effects", report)
            self.assertNotIn("Impedance (information only)", report)
            self.assertNotIn("Curvature radius H/V mm", report)
            self.assertIn("sortable-table", report)
            self.assertIn("Mean containment H&nbsp;/ V", report)
            self.assertIn("Profile RMS error H&nbsp;/ V", report)
            self.assertIn("Slice-energy RMS departure H&nbsp;/ V", report)
            self.assertNotIn("Average diagnostic score", report)
            self.assertNotIn("Coverage Match", report)
            self.assertNotIn("Coverage Smoothness", report)
            self.assertNotIn("Waist Stability", report)
            self.assertNotIn("Window Uniformity", report)
            self.assertIn("Length-mouth ratio", report)
            self.assertIn("data-column-toggle='mouth-height'", report)
            self.assertIn("data-column='mouth-height' hidden", report)
            self.assertIn("data-column='mouth-width' hidden", report)
            self.assertIn("&nbsp;/<wbr>", report)
            self.assertIn("main{width:100%", report)
            self.assertIn("--bg:#0c1014", report)
            self.assertIn("color-scheme:dark", report)
            self.assertNotIn("geometry feasible", report)
            self.assertGreaterEqual(len(state["candidates"]), 1)
            self.assertFalse(any(record["status"] == "rejected"
                                 for record in state["candidates"]))
            self.assertGreaterEqual(state["rejected_count"], 0)
            self.assertTrue(all(record["proposal_source"] in
                                {"seed", "initial-length-N-family"}
                                for record in state["candidates"]))
            families = [record for record in state["candidates"]
                        if record["proposal_source"] == "initial-length-N-family"]
            self.assertEqual(sorted({record["values"]["length_mm"] for record in families}),
                             [255.0, 285.0, 315.0, 345.0])
            self.assertEqual({record["values"]["extension_mm"] for record in families},
                             {0.0})
            for length in (255.0, 285.0, 315.0, 345.0):
                matched = [record for record in families
                           if record["values"]["length_mm"] == length]
                self.assertEqual([record["values"]["n_h"] for record in matched],
                                 [2.0, 10.0, 25.0])
                self.assertEqual(len({(record["values"]["osse_coverage_h_deg"],
                                       record["values"]["osse_coverage_v_deg"],
                                       record["values"]["k_h"], record["values"]["k_v"])
                                      for record in matched}), 1)
            self.assertTrue((Path(temp) / "candidates" / "candidate-000" /
                             "project.yaml").is_file())
            self.assertEqual(len(list((Path(temp) / "candidates" / "candidate-000").
                                      glob("*.STL"))), 1)
            candidate_count = len(state["candidates"])
            resumed = run_search(SEARCH, Path(temp), None, dry_run=True)
            self.assertEqual(len(resumed["candidates"]), candidate_count)

            for index, record in enumerate(state["candidates"]):
                record["status"] = "complete"
                score = 50.0 + index
                record["diagnostics"] = {"combined": {
                    "coverage_match_percent": score,
                    "coverage_smoothness_percent": 100 - score,
                    "waist_stability_percent": score,
                    "window_uniformity_percent": score}}
                record["sampling_stability"] = {"status": "stable"}
                plane = {
                    "containment": {
                        "mean_fraction": score / 100,
                        "worst_windows": {"1/3 octave": {
                            "minimum": (score - 5) / 100}}},
                    "distribution": {
                        "rms_profile_error_db": 3.0,
                        "rms_outward_rise_violation_db": 1.0},
                    "slice_energy_stability": {"rms_departure_db": 0.5},
                    "minus_six_line": {"rms_coverage_error_deg": 2.0},
                }
                record["surface_diagnostics"] = {
                    "status": "available", "horizontal": plane,
                    "vertical": plane}
            state["status"] = "complete"
            highlighted = write_report(Path(temp), state).read_text()
            self.assertIn("Final surface score", highlighted)
            self.assertIn("Mean containment H&nbsp;/ V", highlighted)
            self.assertIn("Profile RMS error H&nbsp;/ V", highlighted)
            self.assertIn("Slice-energy RMS departure H&nbsp;/ V", highlighted)
            self.assertNotIn("Coverage Match", highlighted)
            self.assertNotIn("Coverage Smoothness", highlighted)
            self.assertNotIn("Waist Stability", highlighted)
            self.assertNotIn("Window Uniformity", highlighted)
            self.assertNotIn("1/3-oct", highlighted)
            self.assertNotIn("Added-depth cost", highlighted)


if __name__ == "__main__":
    unittest.main()
