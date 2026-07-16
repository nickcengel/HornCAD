from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from app.tools.run_bem_search import (
    candidate_distance, candidate_trait, candidate_traits, geometry_feasibility,
    inferior_to_seed_probability, learned_lever_effects, length_cost_percent, load_search,
    materialize_candidate, pareto_indices, propose_vector, repair_k_for_positive_s,
    sampling_stability,
    run_search, seed_values,
)


ROOT = Path(__file__).parents[1]
SEARCH = (ROOT / "examples" / "osse-400x280-reference" / "bem-search" /
          "search.yaml")


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
        self.assertIn("not positive", reason)

    def test_seed_then_space_filling_proposals_are_bounded(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["seed_values"] = seed_values(seed)
        seed_vector, source = propose_vector(search, [], 0)
        self.assertEqual(source, "seed")
        self.assertTrue(np.all((seed_vector >= 0) & (seed_vector <= 1)))
        sample, source = propose_vector(search, [], 1)
        self.assertEqual(source, "sensitivity-length_mm-low")
        self.assertTrue(np.all((sample >= 0) & (sample <= 1)))
        paired, source = propose_vector(search, [], 2)
        self.assertEqual(source, "sensitivity-length_mm-high")
        self.assertNotEqual(sample[0], paired[0])

    def test_inferior_screen_waits_for_seed_and_sufficient_learning(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["seed_values"] = seed_values(seed)
        self.assertEqual(inferior_to_seed_probability(search, [], np.full(6, 0.5)), 0)

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
                                "smoothness_percent": score,
                                "non_narrowing_percent": score}}})
            from app.tools.run_bem_search import update_selection_scores
            update_selection_scores(records[-1], search)
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

    def test_k_repair_moves_repairable_candidate_into_positive_s_region(self) -> None:
        search, _, seed = load_search(SEARCH)
        search["intended_coverage_h_deg"] = 50.0
        search["intended_coverage_v_deg"] = 35.0
        values = {"length_mm": 300.0, "extension_mm": 20.0,
                  "osse_coverage_h_deg": 50.0, "osse_coverage_v_deg": 35.0,
                  "k_h": 5.0, "k_v": 5.0}
        before, before_derived = materialize_candidate(seed, values, search)
        self.assertFalse(geometry_feasibility(before_derived)[0])
        repaired, changes = repair_k_for_positive_s(seed, values, search)
        _, derived = materialize_candidate(seed, repaired, search)
        self.assertTrue(geometry_feasibility(derived)[0])
        self.assertTrue(changes)
        self.assertGreater(repaired["k_h"], values["k_h"])

    def test_pareto_set_uses_only_loading_feasible_candidates(self) -> None:
        def record(scores: tuple[float, float, float], loading: float) -> dict:
            combined = dict(zip(("coverage_match_percent", "smoothness_percent",
                                 "non_narrowing_percent"), scores))
            return {"status": "complete", "crossover_loading_percent": loading,
                    "diagnostics": {"combined": combined}}
        records = [record((80, 80, 80), 100), record((70, 70, 70), 100),
                   record((95, 95, 95), 90)]
        self.assertEqual(pareto_indices(records), {0})

    def test_length_cost_is_steep_beyond_ten_percent(self) -> None:
        self.assertAlmostEqual(length_cost_percent({"length_mm": 300}, 300), 0)
        self.assertAlmostEqual(length_cost_percent({"length_mm": 330}, 300), 4)
        self.assertAlmostEqual(length_cost_percent({"length_mm": 345}, 300), 20)

    def test_candidate_distance_uses_post_repair_normalized_parameters(self) -> None:
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
            self.assertIn("N is not varied in this search", report)
            self.assertNotIn("geometry feasible", report)
            self.assertGreaterEqual(len(state["candidates"]), 1)
            self.assertFalse(any(record["status"] == "rejected"
                                 for record in state["candidates"]))
            self.assertGreater(state["rejected_count"], 0)
            self.assertTrue((Path(temp) / "candidates" / "candidate-000" /
                             "project.yaml").is_file())
            self.assertEqual(len(list((Path(temp) / "candidates" / "candidate-000").
                                      glob("*.STL"))), 1)
            candidate_count = len(state["candidates"])
            resumed = run_search(SEARCH, Path(temp), None, dry_run=True)
            self.assertEqual(len(resumed["candidates"]), candidate_count)


if __name__ == "__main__":
    unittest.main()
