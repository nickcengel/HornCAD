#!/usr/bin/env python3
"""Run one NumCalc process under the shared stage-aware solver semaphore."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

try:
    from .solver_slots import SolverSlotPool
except ImportError:
    # NumCalc launches this file by executable path from a case directory.
    from solver_slots import SolverSlotPool


EXECUTABLE_ENV = "HORNCAD_NUMCALC_EXECUTABLE"
SLOT_DIRECTORY_ENV = "HORNCAD_NUMCALC_SLOT_DIRECTORY"
SLOT_CAPACITY_ENV = "HORNCAD_NUMCALC_SLOT_CAPACITY"


def run(argv: list[str]) -> int:
    executable_value = os.environ.get(EXECUTABLE_ENV)
    directory_value = os.environ.get(SLOT_DIRECTORY_ENV)
    capacity_value = os.environ.get(SLOT_CAPACITY_ENV)
    if not executable_value or not directory_value or not capacity_value:
        raise RuntimeError(
            "stage-aware NumCalc wrapper requires executable, slot directory, "
            "and slot capacity environment variables")
    executable = Path(executable_value)
    if not executable.is_file():
        raise FileNotFoundError(executable)
    capacity = int(capacity_value)
    command = [str(executable), *argv]
    # RAM estimates are short preparation work. Keeping them outside the
    # numerical semaphore lets upcoming cases prepare while solve slots are
    # occupied.
    if "-estimate_ram" in argv:
        return subprocess.run(command, check=False).returncode
    pool = SolverSlotPool(Path(directory_value), capacity)
    with pool.acquire():
        return subprocess.run(command, check=False).returncode


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
