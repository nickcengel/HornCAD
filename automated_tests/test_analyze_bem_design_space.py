import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tools.analyze_bem_design_space import (
    Candidate, _domain_mapping_meta, _phase_three_audit, _study_progress,
    _transition_summaries,
    deduplicate, matched_pairs,
)


def candidate(*, length=100.0, s=1.0, k=4.0, n=10.0, score=80.0,
              completed=1.0, search_path=None, mouth=300.0, coverage=40.0,
              diagnostic_updates=None):
    diagnostics = {
        "score": score, "mean_containment": 90.0,
        "profile_rms_error_db": 2.0, "slice_energy_departure_db": 1.0,
        "outward_rise_violation_db": 0.5, "minus_six_rms_error_deg": 5.0,
        "high_frequency_coverage_error_deg": -2.0,
    }
    diagnostics.update(diagnostic_updates or {})
    return Candidate(search_path, "report.html", completed, mouth, coverage, length,
                     s, k, n, score, diagnostics, 2000.0)


class DesignSpaceAnalysisTests(unittest.TestCase):
    def test_deduplicate_keeps_latest_exact_design(self):
        old = candidate(score=70.0, completed=1.0)
        new = candidate(score=80.0, completed=2.0)
        self.assertEqual(deduplicate([old, new]), [new])

    def test_length_pairs_hold_k_and_n(self):
        items = [
            candidate(length=120, s=1.0, score=70),
            candidate(length=110, s=1.5, score=80),
            candidate(length=105, s=1.8, k=4.5, score=90),
        ]
        pairs = matched_pairs(items, "length_mm")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["from"], 110)
        self.assertEqual(pairs[0]["delta"]["score"], -10)

    def test_k_pairs_hold_length_and_n(self):
        items = [candidate(k=3.5, score=75), candidate(k=4.0, score=80)]
        pairs = matched_pairs(items, "k")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["from"], 3.5)

    def test_transition_summary_preserves_individual_steps(self):
        pairs = matched_pairs([
            candidate(n=2, score=60), candidate(n=5, score=80),
            candidate(n=10, score=78),
        ], "n")
        summaries = _transition_summaries(pairs)
        self.assertEqual([(item["from"], item["to"]) for item in summaries],
                         [(2, 5), (5, 10)])
        self.assertEqual(summaries[0]["median_score_delta"], 20)

    def test_remote_meta_stops_distributed_low_value_corner(self):
        items = []
        for index, (coverage, mouth) in enumerate(
                ((25, 250), (25, 300), (35, 250),
                 (35, 300), (50, 250), (50, 300))):
            items.append(candidate(
                score=90, completed=1, mouth=mouth, coverage=coverage,
                length=mouth / 2, search_path=Path(
                    f"{coverage}deg/{mouth}x{mouth}-s-grid/search_state.json")))
            items.append(candidate(
                score=84, completed=3, mouth=mouth, coverage=coverage,
                length=mouth / 1.2, s=0.1, k=1, n=2,
                search_path=Path(
                    f"{coverage}deg/{mouth}x{mouth}-domain-map-b01/search_state.json")))
        meta = _domain_mapping_meta(items, 2)
        self.assertEqual(meta["completed_remote_candidates"], 6)
        self.assertEqual(meta["classification_counts"]["boundary-confirmation"], 6)
        self.assertEqual(meta["strata"][0]["recommendation"],
                         "stop stratum: low-value boundary established")

    def test_remote_meta_retains_competitive_remote_region(self):
        baseline = candidate(
            score=90, completed=1, search_path=Path(
                "40deg/300x300-s-grid/search_state.json"))
        remote = candidate(
            score=90.2, completed=3, length=180, s=3, k=7, n=20,
            search_path=Path(
                "40deg/300x300-domain-map-b01/search_state.json"))
        meta = _domain_mapping_meta([baseline, remote], 2)
        self.assertEqual(meta["assessment"], "remote competitive region found")
        self.assertEqual(meta["classification_counts"]["new-cell-winner"], 1)

    def test_study_progress_tracks_live_phase_and_closure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "study_program_state.json").write_text(json.dumps({
                "status": "running", "phase": "coupled-closure",
            }))
            (root / "s_boundary_closure.json").write_text(json.dumps({
                "status": "complete",
                "results": [
                    {"status": "closed"},
                    {"status": "geometry-limited"},
                ],
            }))
            progress = _study_progress(root)
        self.assertEqual(progress["program_phase"], "coupled-closure")
        self.assertEqual(progress["s_closure_status"], "complete")
        self.assertEqual(progress["s_closure_counts"], {
            "closed": 1, "geometry-limited": 1,
        })

    def test_phase_three_audit_quantifies_quarter_step_value(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            search = root / "45deg" / "400x400-coupled-r01-kn"
            search.mkdir(parents=True)
            records = []
            for index, (k, score) in enumerate(((4.0, 88), (4.25, 88.1),
                                                (4.5, 88.08))):
                records.append({
                    "id": f"candidate-{index:03d}", "status": "complete",
                    "values": {"k_h": k, "n_h": 8},
                    "surface_diagnostics": {
                        "score": {"overall_percent": score}},
                })
            (search / "search_state.json").write_text(json.dumps({
                "status": "complete", "candidates": records,
            }))

            audit = _phase_three_audit(root)

        self.assertEqual(audit["search_count"], 1)
        self.assertEqual(audit["completed_candidate_count"], 3)
        self.assertEqual(audit["quarter_step_k_candidate_count"], 1)
        self.assertAlmostEqual(
            audit["maximum_winner_advantage_over_nearby_k"], 0.02)

    def test_phase_three_audit_marks_small_round_limit_boundary_gain(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            kn = root / "50deg" / "400x400-coupled-r03-kn"
            kn.mkdir(parents=True)
            (kn / "search_state.json").write_text(json.dumps({
                "candidates": [{
                    "status": "complete", "values": {"k_h": 5, "n_h": 8},
                    "surface_diagnostics": {"score": {"overall_percent": 85}},
                }],
            }))
            for round_number in (1, 2, 3):
                search = root / "50deg" / f"400x400-coupled-r{round_number:02d}-s"
                search.mkdir(parents=True)
                records = [{
                    "status": "complete",
                    "derived": {"s_h": s},
                    "values": {"length_mm": 120 - s, "k_h": 5, "n_h": 8},
                    "surface_diagnostics": {
                        "score": {"overall_percent": score}},
                } for s, score in ((1.0, 85.3), (1.3, 85.0), (1.6, 84.5))]
                (search / "search_state.json").write_text(json.dumps({
                    "candidates": records,
                }))

            audit = _phase_three_audit(root)

        anchor = audit["anchor_gains"][0]
        self.assertEqual(anchor["local_s_status"],
                         "practical-stop-unbracketed")
        self.assertAlmostEqual(anchor["local_s_gain_over_center_points"], 0.3)


if __name__ == "__main__":
    unittest.main()
