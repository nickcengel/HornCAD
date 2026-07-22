import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tools.analyze_bem_design_space import (
    Candidate, _study_progress, _transition_summaries, deduplicate, matched_pairs,
)


def candidate(*, length=100.0, s=1.0, k=4.0, n=10.0, score=80.0,
              completed=1.0):
    diagnostics = {
        "score": score, "mean_containment": 90.0,
        "profile_rms_error_db": 2.0, "slice_energy_departure_db": 1.0,
        "outward_rise_violation_db": 0.5, "minus_six_rms_error_deg": 5.0,
        "high_frequency_coverage_error_deg": -2.0,
    }
    return Candidate(None, "report.html", completed, 300.0, 40.0, length,
                     s, k, n, score, diagnostics, 2000.0)


class DesignSpaceAnalysisTests(unittest.TestCase):
    def test_deduplicate_keeps_latest_exact_design(self):
        old = candidate(score=70.0, completed=1.0)
        new = candidate(score=80.0, completed=2.0)
        self.assertEqual(deduplicate([old, new]), [new])

    def test_s_pairs_hold_k_and_n(self):
        items = [
            candidate(length=120, s=1.0, score=70),
            candidate(length=110, s=1.5, score=80),
            candidate(length=105, s=1.8, k=4.5, score=90),
        ]
        pairs = matched_pairs(items, "s")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["delta"]["score"], 10)

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


if __name__ == "__main__":
    unittest.main()
