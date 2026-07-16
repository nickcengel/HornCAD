#!/usr/bin/env python3
"""Run the complete all-BEM review pipeline from HornCAD YAML."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


REPOSITORY = Path(__file__).resolve().parents[2]
CACHE = REPOSITORY / ".cache"
for directory in (CACHE, CACHE / "matplotlib", CACHE / "fontconfig"):
    directory.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(CACHE / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE))
os.environ.setdefault("FONTCONFIG_PATH", str(CACHE / "fontconfig"))

try:
    from .generate_numcalc_review import generate_review  # noqa: E402
    from .run_numcalc_sweep import ppo_frequency_grid, run_sweep  # noqa: E402
except ImportError:
    from generate_numcalc_review import generate_review  # noqa: E402
    from run_numcalc_sweep import ppo_frequency_grid, run_sweep  # noqa: E402


DEFAULT_NUMCALC_CANDIDATES = (
    Path("/private/tmp/Mesh2HRTF/mesh2hrtf/NumCalc/bin/NumCalc"),
    REPOSITORY / "build/numcalc/NumCalc",
)


def find_numcalc(requested: Path | None) -> Path:
    candidates = (requested,) if requested else DEFAULT_NUMCALC_CANDIDATES
    for candidate in candidates:
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    checked = ", ".join(str(path) for path in candidates if path is not None)
    raise FileNotFoundError(
        f"NumCalc executable not found; checked: {checked}. Pass --binary if needed.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", default="All-BEM free-air exterior")
    parser.add_argument("--start-hz", type=float, default=500.0)
    parser.add_argument("--stop-hz", type=float, default=8_000.0)
    parser.add_argument("--points-per-octave", type=float, default=10.0)
    parser.add_argument("--elements-per-wavelength", type=float, default=6.0)
    parser.add_argument("--workers", type=int, default=0,
                        help="frequency processes; 0 selects automatically")
    parser.add_argument("--angles", type=int, default=91)
    parser.add_argument("--memory-limit-gib", type=float)
    parser.add_argument("--binary", type=Path,
                        help="NumCalc executable; normally detected automatically")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if not args.yaml.is_file():
        raise FileNotFoundError(args.yaml)
    started = time.perf_counter()
    frequencies = ppo_frequency_grid(
        args.start_hz, args.stop_hz, args.points_per_octave)
    manifest = run_sweep(
        args.yaml, find_numcalc(args.binary), args.output_dir, frequencies,
        elements_per_wavelength=args.elements_per_wavelength,
        angles=args.angles, maximum_workers=args.workers,
        memory_limit_gib=args.memory_limit_gib, resume=not args.no_resume)
    run_dir = Path(manifest["run_dir"])
    generate_review(run_dir, title=args.title)
    manifest["workflow_elapsed_s"] = time.perf_counter() - started
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"review: {run_dir}", flush=True)
    print(f"mesh-to-standard-plots wall time: {manifest['workflow_elapsed_s']:.3f}s",
          flush=True)


if __name__ == "__main__":
    main()
