"""Small cross-process file-lock semaphore for native solver processes."""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import time
from typing import IO


@dataclass
class SolverSlotLease:
    """One held solver slot; closing it releases the operating-system lock."""

    index: int
    handle: IO[str]
    waited_s: float

    def close(self) -> None:
        if self.handle.closed:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()

    def __enter__(self) -> SolverSlotLease:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class SolverSlotPool:
    """Limit cooperating processes without a long-lived manager process."""

    def __init__(self, directory: Path, capacity: int,
                 poll_seconds: float = 0.05):
        if capacity < 1:
            raise ValueError("solver slot capacity must be positive")
        if poll_seconds <= 0:
            raise ValueError("solver slot polling interval must be positive")
        self.directory = directory
        self.capacity = capacity
        self.poll_seconds = poll_seconds

    def acquire(self, timeout_s: float | None = None) -> SolverSlotLease:
        self.directory.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        while True:
            for index in range(self.capacity):
                path = self.directory / f"slot-{index:03d}.lock"
                handle = path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(
                        handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                waited = time.monotonic() - started
                handle.seek(0)
                handle.truncate()
                handle.write(json.dumps({
                    "pid": os.getpid(),
                    "acquired_at_unix": time.time(),
                    "waited_s": waited,
                }) + "\n")
                handle.flush()
                return SolverSlotLease(index, handle, waited)
            if timeout_s is not None and time.monotonic() - started >= timeout_s:
                raise TimeoutError(
                    f"no solver slot became available within {timeout_s:g}s")
            time.sleep(self.poll_seconds)
