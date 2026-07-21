from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.tools.run_numcalc_sweep import _pending_cases


class NumCalcSweepSchedulingTests(unittest.TestCase):
    @staticmethod
    def case(frequency: float) -> tuple[float, SimpleNamespace, float]:
        return frequency, SimpleNamespace(root=Path(str(frequency))), 1.0

    def test_pending_cases_put_slowest_low_frequencies_first(self) -> None:
        cases = [self.case(8000), self.case(500), self.case(2000)]

        pending = _pending_cases(cases, resume=False)

        self.assertEqual([item[0] for item in pending], [500, 2000, 8000])

    def test_resume_excludes_completed_cases_before_ordering(self) -> None:
        cases = [self.case(8000), self.case(500), self.case(2000)]

        with patch("app.tools.run_numcalc_sweep._completed",
                   side_effect=lambda root: root == Path("500")):
            pending = _pending_cases(cases, resume=True)

        self.assertEqual([item[0] for item in pending], [2000, 8000])


if __name__ == "__main__":
    unittest.main()
