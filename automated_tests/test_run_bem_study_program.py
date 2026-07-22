from pathlib import Path
import tempfile
import unittest

from app.tools.run_bem_study_program import run_dynamic_queue, search_status


class BEMStudyProgramTests(unittest.TestCase):
    def test_missing_state_is_not_started(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(search_status(Path(temp)), "not-started")

    def test_dynamic_queue_runs_every_available_task(self):
        paths = [Path("a"), Path("b"), Path("c")]
        seen = []
        results = run_dynamic_queue(
            paths, lambda path: seen.append(path.name) or path.name,
            workers=2, poll_seconds=0.01, count_external_running=False)
        self.assertCountEqual(seen, ["a", "b", "c"])
        self.assertCountEqual(results, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
