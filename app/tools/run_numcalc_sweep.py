#!/usr/bin/env python3
"""Resource-aware native NumCalc frequency sweep for HornCAD."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import trimesh

try:
    from .generate_numcalc_review import generate_review
except ImportError:
    from generate_numcalc_review import generate_review

try:
    from .helmholtz_bem_3d import (
        AcousticMesh, MeshReport, MeshSettings, build_quadrant_acoustic_mesh,
    )
    from .numcalc_bem_backend import (
        NumCalcCase, estimate_numcalc_ram, export_numcalc_case,
        far_field_points, read_evaluation_pressure, run_numcalc,
    )
except ImportError:
    from helmholtz_bem_3d import (
        AcousticMesh, MeshReport, MeshSettings, build_quadrant_acoustic_mesh,
    )
    from numcalc_bem_backend import (
        NumCalcCase, estimate_numcalc_ram, export_numcalc_case,
        far_field_points, read_evaluation_pressure, run_numcalc,
    )


NUMCALC_PRODUCTION_EPW = 6.0


def ppo_frequency_grid(start_hz: float, stop_hz: float,
                       points_per_octave: float) -> np.ndarray:
    if not (0 < start_hz < stop_hz) or points_per_octave <= 0:
        raise ValueError("require 0 < start < stop and positive points per octave")
    intervals = int(math.ceil(math.log2(stop_hz / start_hz)
                              * points_per_octave))
    return np.geomspace(start_hz, stop_hz, intervals + 1)


def _physical_memory_gib() -> float:
    try:
        return (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
                / 1024 ** 3)
    except (ValueError, OSError):
        return 8.0


def _case_from_root(root: Path) -> NumCalcCase:
    metadata = json.loads((root / "horncad-numcalc.json").read_text())
    source_dir = root / "NumCalc/source_1"
    domains = np.loadtxt(root / "ObjectMeshes/Reference/Elements.txt",
                         skiprows=1, dtype=int)
    # Export orders the driven throat last. Recover its range from NC.inp only
    # for reporting; NumCalc itself consumes the already-authored input.
    throat = [line for line in (source_dir / "NC.inp").read_text().splitlines()
              if " VELO " in line and not line.endswith("VELO 0.0 -1 0.0 -1")]
    parts = throat[-1].split()
    return NumCalcCase(root, source_dir, len(domains),
                       len(metadata["evaluation_points_m"]),
                       int(parts[1]), int(parts[3]), metadata["velocity_m_s"])


def _run_worker(payload: tuple[Path, Path, int]) -> dict[str, float | int | bool]:
    root, executable, max_iterations = payload
    run = run_numcalc(_case_from_root(root), executable, max_iterations)
    return {"root": str(root), **asdict(run)}


def _completed(root: Path) -> bool:
    try:
        run = json.loads((root / "run.json").read_text())
        return bool(run["converged"] and
                    (root / "NumCalc/source_1/be.out/be.1/pEvalGrid").exists())
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return False


def run_sweep(yaml_path: Path, executable: Path, output_dir: Path,
              frequencies_hz: np.ndarray, *, elements_per_wavelength: float = 8.0,
              angles: int = 91, maximum_workers: int = 0,
              memory_limit_gib: float | None = None, max_iterations: int = 250,
              resume: bool = True, dry_run: bool = False) -> dict:
    started = time.perf_counter()
    maximum_frequency = float(np.max(frequencies_hz))
    run_hash = hashlib.sha256(
        yaml_path.read_bytes() + Path(__file__).read_bytes()
        + Path(build_quadrant_acoustic_mesh.__code__.co_filename).read_bytes()
        + np.asarray(frequencies_hz, dtype=float).tobytes()
        + f"{elements_per_wavelength}:{angles}".encode()).hexdigest()[:12]
    root = output_dir / f"{yaml_path.stem}-NumCalc-{run_hash}"
    root.mkdir(parents=True, exist_ok=True)
    mesh_npz = root / "quadrant_mesh.npz"
    mesh_json = root / "quadrant_mesh.json"
    if resume and mesh_npz.exists() and mesh_json.exists():
        with np.load(mesh_npz, allow_pickle=False) as data:
            metadata = json.loads(mesh_json.read_text())
            report = MeshReport(**metadata["report"])
            mesh = AcousticMesh(
                trimesh.Trimesh(vertices=data["vertices"], faces=data["faces"],
                                process=False),
                data["domain_indices"], metadata["source_area_m2"],
                data["mouth_center_m"], data["mouth_ring_m"], report,
                metadata["content_hash"], symmetry_factor=4,
                symmetry_planes=("x=0", "y=0"))
    else:
        mesh = build_quadrant_acoustic_mesh(
            yaml_path, MeshSettings(maximum_frequency, elements_per_wavelength))
        np.savez_compressed(
            mesh_npz, vertices=mesh.surface.vertices, faces=mesh.surface.faces,
            domain_indices=mesh.domain_indices,
            mouth_center_m=mesh.mouth_center_m, mouth_ring_m=mesh.mouth_ring_m)
        mesh_json.write_text(json.dumps({
            "source_area_m2": mesh.source_area_m2,
            "content_hash": mesh.content_hash,
            "report": asdict(mesh.report),
        }, indent=2, sort_keys=True) + "\n")

    cases: list[tuple[float, NumCalcCase, float]] = []
    for frequency in frequencies_hz:
        case_root = root / "frequencies" / f"{float(frequency):.9f}"
        if resume and _completed(case_root):
            case = _case_from_root(case_root)
            case_metadata = json.loads(
                (case_root / "horncad-numcalc.json").read_text())
            estimate = float(case_metadata["estimated_ram_gib"])
        else:
            points, _ = far_field_points(mesh.mouth_center_m, float(frequency),
                                         343.21, np.linspace(0, 90, angles))
            case = export_numcalc_case(case_root, mesh, float(frequency), points,
                                       method="mlfmm",
                                       shared_object_dir=root / "SharedMesh")
            estimate = estimate_numcalc_ram(case, executable)
        cases.append((float(frequency), case, estimate))

    pending = [(frequency, case, estimate) for frequency, case, estimate in cases
               if not (resume and _completed(case.root))]
    cpus = os.cpu_count() or 1
    memory_limit = memory_limit_gib or 0.75 * _physical_memory_gib()
    peak_estimate = max(estimate for _, _, estimate in cases) * 1.15
    memory_workers = max(1, int(memory_limit // peak_estimate))
    requested = cpus if maximum_workers == 0 else max(1, maximum_workers)
    workers = max(1, min(requested, cpus, memory_workers, len(pending) or 1))
    print(f"NumCalc plan: {workers} single-thread frequency processes; "
          f"{peak_estimate:.3f} GiB/process including headroom; "
          f"{memory_limit:.1f} GiB limit; {len(pending)} pending", flush=True)

    records: list[dict] = []
    if pending and not dry_run:
        payloads = [(case.root, executable, max_iterations)
                    for _, case, _ in sorted(pending, reverse=True,
                                              key=lambda item: item[0])]
        if workers == 1:
            for payload in payloads:
                record = _run_worker(payload)
                records.append(record)
                print(f"completed {Path(record['root']).name} Hz in "
                      f"{record['wall_time_s']:.2f}s", flush=True)
        else:
            # Threads only supervise independent native NumCalc subprocesses;
            # all numerical work remains in separate OS processes. This avoids
            # Python's POSIX-semaphore dependency in restricted macOS shells.
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(_run_worker, payload)
                           for payload in payloads]
                for future in as_completed(futures):
                    record = future.result()
                    records.append(record)
                    print(f"completed {Path(record['root']).name} Hz in "
                          f"{record['wall_time_s']:.2f}s", flush=True)

    results = []
    for frequency, case, estimate in cases:
        run_path = case.root / "run.json"
        run = json.loads(run_path.read_text()) if run_path.exists() else None
        results.append({
            "frequency_hz": frequency, "case": str(case.root.relative_to(root)),
            "estimated_ram_gib": estimate, "run": run,
        })
    manifest = {
        "schema_version": 1, "backend": "numcalc-native-symmetry",
        "run_dir": str(root),
        "yaml": str(yaml_path), "numcalc": str(executable),
        "frequencies_hz": list(map(float, frequencies_hz)),
        "elements_per_wavelength": elements_per_wavelength,
        "mesh_maximum_frequency_hz": maximum_frequency,
        "mesh_quadrant_panels": len(mesh.surface.faces), "angles": angles,
        "workers": workers, "memory_limit_gib": memory_limit,
        "peak_estimated_ram_gib": peak_estimate,
        "status": "planned" if dry_run else "complete",
        "elapsed_s": time.perf_counter() - started, "results": results,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--numcalc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-hz", type=float, default=500.0)
    parser.add_argument("--stop-hz", type=float, default=8_000.0)
    parser.add_argument("--points-per-octave", type=float, default=10.0)
    parser.add_argument("--points", type=int,
                        help="explicit logarithmic point count for a smoke run")
    parser.add_argument("--elements-per-wavelength", type=float,
                        default=NUMCALC_PRODUCTION_EPW)
    parser.add_argument("--angles", type=int, default=91)
    parser.add_argument("--maximum-workers", type=int, default=0)
    parser.add_argument("--memory-limit-gib", type=float)
    parser.add_argument("--max-iterations", type=int, default=250)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    workflow_started = time.perf_counter()
    frequencies = (np.geomspace(args.start_hz, args.stop_hz, args.points)
                   if args.points else
                   ppo_frequency_grid(args.start_hz, args.stop_hz,
                                      args.points_per_octave))
    manifest = run_sweep(
        args.yaml, args.numcalc, args.output_dir, frequencies,
        elements_per_wavelength=args.elements_per_wavelength,
        angles=args.angles, maximum_workers=args.maximum_workers,
        memory_limit_gib=args.memory_limit_gib,
        max_iterations=args.max_iterations, resume=not args.no_resume,
        dry_run=args.dry_run)
    if not args.dry_run:
        run_root = Path(manifest["run_dir"])
        generate_review(run_root)
        manifest["workflow_elapsed_s"] = time.perf_counter() - workflow_started
        (run_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: manifest[key] for key in (
        "status", "mesh_quadrant_panels", "workers", "elapsed_s")}, indent=2))
    if not args.dry_run:
        print(f"mesh-to-standard-plots wall time: {manifest['workflow_elapsed_s']:.3f}s")


if __name__ == "__main__":
    main()
