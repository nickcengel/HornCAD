from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import yaml

from app.tools.run_stage_aware_bem_queue import _run_one, validate_queue
from app.tools.solver_slots import SolverSlotPool


class SolverSlotPoolTests(unittest.TestCase):
    def test_second_process_slot_waits_until_first_is_released(self):
        with tempfile.TemporaryDirectory() as temp:
            pool = SolverSlotPool(Path(temp), capacity=1, poll_seconds=0.005)
            first = pool.acquire()
            acquired = []

            def wait_for_slot():
                with pool.acquire(timeout_s=1.0) as lease:
                    acquired.append(lease.waited_s)

            thread = threading.Thread(target=wait_for_slot)
            thread.start()
            time.sleep(0.03)
            self.assertFalse(acquired)
            first.close()
            thread.join(timeout=1.0)
            self.assertEqual(len(acquired), 1)
            self.assertGreaterEqual(acquired[0], 0.02)


class StageAwareQueueValidationTests(unittest.TestCase):
    @staticmethod
    def write_search(path: Path, workers: int) -> None:
        path.write_text(yaml.safe_dump({
            "bem_candidate_search": {
                "version": 1,
                "solver": {"workers": workers},
            },
        }), encoding="utf-8")

    def test_queue_permits_more_searches_than_solver_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = [root / f"search-{index}.yaml" for index in range(4)]
            for path in paths:
                self.write_search(path, 10)
            audit = validate_queue(
                paths, queue_workers=4, numcalc_processes=20)
        self.assertEqual(audit["queue_workers"], 4)
        self.assertEqual(audit["numcalc_process_capacity"], 20)

    def test_one_search_cannot_exceed_global_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "search.yaml"
            self.write_search(path, 24)
            with self.assertRaisesRegex(ValueError, "above global capacity"):
                validate_queue(
                    [path], queue_workers=4, numcalc_processes=20)

    def test_failed_candidate_is_retried_and_complete_state_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            search = root / "search.yaml"
            self.write_search(search, 10)
            state_path = root / "search_state.json"
            state_path.write_text(
                '{"status":"stopped","candidates":[{"status":"failed"}]}',
                encoding="utf-8",
            )

            def complete(command, **_):
                self.assertIn("--retry-failed", command)
                state_path.write_text(
                    '{"status":"complete","candidates":[{"status":"complete"}]}',
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch(
                "app.tools.run_stage_aware_bem_queue.subprocess.run",
                side_effect=complete,
            ):
                result = _run_one(search, {})
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["retry_failed"])
        self.assertEqual(result["search_status"], "complete")

    def test_zero_exit_with_stopped_search_is_a_queue_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            search = root / "search.yaml"
            self.write_search(search, 10)
            (root / "search_state.json").write_text(
                '{"status":"stopped","candidates":[]}',
                encoding="utf-8",
            )
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch(
                "app.tools.run_stage_aware_bem_queue.subprocess.run",
                return_value=completed,
            ):
                result = _run_one(search, {})
        self.assertEqual(result["returncode"], 2)
        self.assertIn("not 'complete'", result["stderr_tail"])


if __name__ == "__main__":
    unittest.main()
