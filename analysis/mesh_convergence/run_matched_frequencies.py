"""Run selected frequencies on one MFEM mesh with resumable field exports."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--mesh-label", required=True)
    parser.add_argument("--frequencies", default="500,1000,2000,3000,4000,5000")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--quadrant-symmetry", action="store_true")
    return parser.parse_args()


def run_one(binary: Path, mesh: Path, prefix: Path, frequency: float,
            quadrant_symmetry: bool) -> str:
    summary = Path(f"{prefix}_summary.csv")
    if summary.exists():
        return f"{frequency:g} Hz already complete"
    command = [str(binary), str(mesh), f"{frequency:.17g}",
               "--output-prefix", str(prefix)]
    if quadrant_symmetry:
        command.append("--quadrant-symmetry")
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.stdout.strip()


def main() -> None:
    args = parse_args()
    frequencies = [float(value) for value in args.frequencies.split(",")]
    if args.workers < 1 or not frequencies or any(value <= 0 for value in frequencies):
        raise ValueError("workers and frequencies must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {}
        for frequency in frequencies:
            prefix = args.output_dir / f"{args.mesh_label}_f{frequency:04.0f}"
            jobs[executor.submit(run_one, args.binary, args.mesh, prefix, frequency,
                                 args.quadrant_symmetry)] = frequency
        for future in as_completed(jobs):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
