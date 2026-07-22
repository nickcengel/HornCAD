from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.tools.cleanup_bem_working_data import cleanup


class CleanupBEMWorkingDataTests(unittest.TestCase):
    def test_recovers_archive_then_removes_raw_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "candidate-000" / "bem" / "project-NumCalc-hash"
            raw.mkdir(parents=True)
            np.savez_compressed(raw / "responses.npz", values=np.arange(3))
            (raw / "large.dat").write_bytes(b"raw")

            result = cleanup(root, apply=True)

            self.assertEqual(result["archives_recovered"], 1)
            self.assertFalse(raw.exists())
            self.assertTrue((raw.parent / "responses.npz").is_file())

    def test_incomplete_raw_tree_is_disposable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "candidate-000" / "bem" / "project-NumCalc-hash"
            raw.mkdir(parents=True)
            (raw / "partial.dat").write_bytes(b"partial")

            result = cleanup(root, apply=True)

            self.assertEqual(result["incomplete_raw_directories"], 1)
            self.assertFalse(raw.exists())


if __name__ == "__main__":
    unittest.main()
