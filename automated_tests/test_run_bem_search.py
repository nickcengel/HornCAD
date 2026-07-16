from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from app.tools.run_bem_search import (
    VARIABLES,
    candidate_distance, candidate_trait, candidate_traits, geometry_feasibility,
    geometry_feature_vector, inferior_to_seed_probability, learned_lever_effects,
    length_cost_percent, load_search,
    materialize_candidate, pareto_indices, propose_vector,
    sampling_stability,
    run_search, seed_values, update_selection_scores, write_report,
)


ROOT = Path(__file__).parents[1]
SEARCH = (ROOT / "examples" / "osse-400x280-reference" / "bem-search" /
          "search.yaml")
ROUND2_SEARCH = SEARCH.parent / "round-2" / "search.yaml"


class BEMSearchTests(unittest.TestCase):
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
                                "pattern_fit_percent": score,
                                "pattern_stability_percent": score,
                                "hf_retention_percent": score}}})
            from app.tools.run_bem_search import update_selection_scores
            update_selection_scores(records[-1], search)
        effects = learned_lever_effects(search, records)
        self.assertGreater(effects["length_mm"]["pattern_fit_percent"], 0)

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
        def record(scores: tuple[float, float, float], loading: float) -> dict:
            combined = dict(zip(("pattern_fit_percent", "pattern_stability_percent",
                                 "hf_retention_percent"), scores))
            return {"status": "complete", "crossover_loading_percent": loading,
                    "diagnostics": {"combined": combined}}
        records = [record((80, 80, 80), 100), record((70, 70, 70), 100),
                   record((95, 95, 95), 90)]
        self.assertEqual(pareto_indices(records), {2})

    def test_length_cost_is_steep_beyond_ten_percent(self) -> None:
        self.assertAlmostEqual(length_cost_percent({"length_mm": 300}, 300), 0)
        self.assertAlmostEqual(length_cost_percent({"length_mm": 255}, 300), 0)
        self.assertAlmostEqual(length_cost_percent({"length_mm": 330}, 300), 4)
        self.assertAlmostEqual(length_cost_percent({"length_mm": 345}, 300), 20)

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
        def fake_export(_project: Path, candidate_dir: Path) -> Path:
            path = candidate_dir / "candidate-surface.STL"
            path.write_bytes(b"test stl")
            return path
        export_stl.side_effect = fake_export
        with tempfile.TemporaryDirectory() as temp:
            state = run_search(SEARCH, Path(temp), None, dry_run=True)
            self.assertEqual(state["status"], "preflight")
            self.assertTrue((Path(temp) / "search_report.html").is_file())
            report = (Path(temp) / "search_report.html").read_text()
            self.assertIn("Configured range", report)
            self.assertIn("N is varied explicitly", report)
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
                    "pattern_fit_percent": score,
                    "pattern_stability_percent": 100 - score,
                    "hf_retention_percent": score}}
                record["sampling_stability"] = {"status": "stable"}
                update_selection_scores(record, state["search"])
            state["status"] = "complete"
            highlighted = write_report(Path(temp), state).read_text()
            self.assertEqual(highlighted.count("class='best'"), 3)
            self.assertEqual(highlighted.count("class='worst'"), 3)


if __name__ == "__main__":
    unittest.main()
