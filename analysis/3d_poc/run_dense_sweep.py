"""Run the accepted MFEM mesh on a logarithmic frequency grid in parallel."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--start-hz", type=float, default=500.0)
    parser.add_argument("--stop-hz", type=float, default=5000.0)
    parser.add_argument("--count", type=int, default=81,
                        help="81 gives approximately 24 points/octave over 500–5000 Hz")
    parser.add_argument("--workers", type=int, default=10)
    return parser.parse_args()


def run_one(binary: Path, mesh: Path, output_dir: Path,
            index: int, frequency: float) -> str:
    prefix = output_dir / f"d{index:03d}"
    command = [str(binary), str(mesh), f"{frequency:.17g}",
               "--output-prefix", str(prefix)]
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.stdout.strip()


def main() -> None:
    args = parse_args()
    if args.count < 2 or args.workers < 1:
        raise ValueError("count must be at least 2 and workers must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frequencies = np.geomspace(args.start_hz, args.stop_hz, args.count)
    np.savetxt(args.output_dir / "frequencies.csv", frequencies, delimiter=",",
               header="frequency_hz", comments="")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(run_one, args.binary, args.mesh, args.output_dir,
                                index, float(frequency)): (index, frequency)
                for index, frequency in enumerate(frequencies)}
        for future in as_completed(jobs):
            index, frequency = jobs[future]
            print(f"[{index + 1}/{len(frequencies)}] {frequency:.3f} Hz: {future.result()}",
                  flush=True)


if __name__ == "__main__":
    main()
