#!/usr/bin/env python3
"""Run several BEM searches while globally limiting native NumCalc processes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

import yaml

from .numcalc_slot_wrapper import (
    EXECUTABLE_ENV, SLOT_CAPACITY_ENV, SLOT_DIRECTORY_ENV,
)
from .run_bem_suite import find_numcalc


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = Path(__file__).with_name("numcalc_slot_wrapper.py")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _solver_workers(search_path: Path) -> int:
    document = yaml.safe_load(search_path.read_text(encoding="utf-8"))
    search = document["bem_candidate_search"]
    return int(search.get("solver", {}).get("workers", 0))


def validate_queue(search_paths: list[Path], queue_workers: int,
                   numcalc_processes: int) -> dict[str, Any]:
    if queue_workers < 1:
        raise ValueError("queue workers must be positive")
    if numcalc_processes < 1:
        raise ValueError("NumCalc process capacity must be positive")
    if not search_paths:
        raise ValueError("at least one search YAML is required")
    resolved = [path.resolve() for path in search_paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate search YAML in stage-aware queue")
    workers = {}
    for path in resolved:
        if not path.is_file():
            raise FileNotFoundError(path)
        configured = _solver_workers(path)
        if configured < 1:
            raise ValueError(f"{path}: solver workers must be explicit")
        if configured > numcalc_processes:
            raise ValueError(
                f"{path}: one search requests {configured} NumCalc processes, "
                f"above global capacity {numcalc_processes}")
        workers[str(path)] = configured
    return {
        "search_count": len(resolved),
        "queue_workers": queue_workers,
        "numcalc_process_capacity": numcalc_processes,
        "configured_workers": workers,
    }


def _search_state(search_path: Path) -> dict[str, Any] | None:
    state_path = search_path.parent / "search_state.json"
    if not state_path.is_file():
        return None
    value = json.loads(state_path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _run_one(search_path: Path, environment: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    initial_state = _search_state(search_path)
    retry_failed = bool(initial_state and any(
        row.get("status") == "failed"
        or "retrying previously failed" in row.get("reason", "")
        for row in initial_state.get("candidates", [])
    ))
    command = [
        sys.executable,
        "-m",
        "app.tools.run_bem_search",
        str(search_path),
        "--output-dir",
        str(search_path.parent),
        "--binary",
        str(WRAPPER),
    ]
    if retry_failed:
        command.append("--retry-failed")
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    final_state = _search_state(search_path)
    state_status = final_state.get("status") if final_state else None
    returncode = result.returncode
    stderr = result.stderr
    if returncode == 0 and state_status != "complete":
        returncode = 2
        stderr += (
            f"\nsearch process exited successfully but state is "
            f"{state_status!r}, not 'complete'\n"
        )
    return {
        "search_yaml": str(search_path),
        "returncode": returncode,
        "retry_failed": retry_failed,
        "search_status": state_status,
        "started_at_unix": started,
        "completed_at_unix": time.time(),
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def run_queue(
    search_paths: list[Path],
    runtime_path: Path,
    *,
    queue_workers: int = 4,
    numcalc_processes: int = 20,
    slot_directory: Path | None = None,
    binary: Path | None = None,
) -> dict[str, Any]:
    audit = validate_queue(search_paths, queue_workers, numcalc_processes)
    executable = find_numcalc(binary)
    slots = slot_directory or (
        Path(tempfile.gettempdir())
        / f"horncad-numcalc-slots-{os.getuid()}"
    )
    environment = dict(os.environ)
    environment.update({
        EXECUTABLE_ENV: str(executable),
        SLOT_DIRECTORY_ENV: str(slots),
        SLOT_CAPACITY_ENV: str(numcalc_processes),
    })
    state: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_unix": time.time(),
        "scheduler": audit,
        "slot_directory": str(slots),
        "events": [],
    }
    _write_json(runtime_path, state)
    failures = []
    with ThreadPoolExecutor(max_workers=queue_workers) as executor:
        futures = {
            executor.submit(_run_one, path.resolve(), environment): path
            for path in search_paths
        }
        for future in as_completed(futures):
            result = future.result()
            state["events"].append(result)
            if result["returncode"]:
                failures.append(result)
            _write_json(runtime_path, state)
    state.update(
        status="failed" if failures else "complete",
        completed_at_unix=time.time(),
        failure_count=len(failures),
    )
    _write_json(runtime_path, state)
    if failures:
        raise RuntimeError(
            "stage-aware BEM searches failed: "
            + ", ".join(item["search_yaml"] for item in failures))
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search_yaml", nargs="+", type=Path)
    parser.add_argument("--runtime-state", required=True, type=Path)
    parser.add_argument("--queue-workers", type=int, default=4)
    parser.add_argument("--numcalc-processes", type=int, default=20)
    parser.add_argument("--slot-directory", type=Path)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    result = run_queue(
        args.search_yaml,
        args.runtime_state,
        queue_workers=args.queue_workers,
        numcalc_processes=args.numcalc_processes,
        slot_directory=args.slot_directory,
        binary=args.binary,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
