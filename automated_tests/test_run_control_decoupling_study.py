from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.tools.run_control_decoupling_study import (
    _load_frozen, _run_queue, material_improvement,
)


class ControlDecouplingRunnerTests(unittest.TestCase):
    def test_queue_keeps_running_after_one_search_fails(self) -> None:
        paths = [Path("one"), Path("two"), Path("three")]
        attempted = []
        events = []

        def task(path: Path) -> None:
            attempted.append(path.name)
            if path.name == "two":
                raise ValueError("deliberate")

        _run_queue(paths, 2, task, lambda path, status, error: events.append(
            (path.name, status, error)))
        self.assertCountEqual(attempted, ["one", "two", "three"])
        self.assertEqual(sum(status == "failed" for _, status, _ in events), 1)
        self.assertTrue(any(name == "three" and status == "complete"
                            for name, status, _ in events))

    def test_materialized_plan_is_locked_to_manifest(self) -> None:
        root = Path(__file__).resolve().parents[1] / "examples" / "control-decoupling"
        _, plan, digest = _load_frozen(root)
        self.assertEqual(plan["manifest_sha256"], digest)

    def test_closure_requires_practical_score_or_diagnostic_change(self) -> None:
        center = {"score": 80.0, "containment_percent": 90.0,
                  "profile_rms_db": 1.0, "slice_rms_db": 1.0,
                  "outward_rise_db": 1.0, "minus_six_rms_deg": 3.0}
        noise = dict(center, score=80.2, profile_rms_db=0.95)
        score_gain = dict(center, score=80.5)
        diagnostic_gain = dict(center, slice_rms_db=0.89)
        self.assertFalse(material_improvement(noise, center))
        self.assertTrue(material_improvement(score_gain, center))
        self.assertTrue(material_improvement(diagnostic_gain, center))


if __name__ == "__main__":
    unittest.main()
