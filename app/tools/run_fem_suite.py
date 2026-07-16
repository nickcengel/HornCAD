"""Run the complete reduced interior FEM review pipeline from HornCAD YAML."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np

try:
    from .acoustic_domain import build_quadrant_acoustic_domain, write_tetwild_volume_mesh
    from .generate_fem_review import generate_review
except ImportError:
    from acoustic_domain import build_quadrant_acoustic_domain, write_tetwild_volume_mesh
    from generate_fem_review import generate_review


SOUND_SPEED_M_S = 343.21
VALIDATED_MAXIMUM_HZ = 8_000.0
DEFAULT_BINARY_CANDIDATES = (
    Path("/private/tmp/horncad-mfem-build/horncad_mfem_interior"),
    Path("build/mfem/horncad_mfem_interior"),
)


def frequency_grid(start_hz: float, stop_hz: float,
                   points_per_octave: float) -> np.ndarray:
    if not 0.0 < start_hz < stop_hz:
        raise ValueError("frequency range must satisfy 0 < start < stop")
    if points_per_octave <= 0.0:
        raise ValueError("points per octave must be positive")
    octaves = math.log2(stop_hz / start_hz)
    intervals = max(1, round(octaves * points_per_octave))
    return np.geomspace(start_hz, stop_hz, intervals + 1)


def find_binary(requested: Path | None) -> Path:
    candidates = (requested,) if requested else DEFAULT_BINARY_CANDIDATES
    for candidate in candidates:
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    checked = ", ".join(str(path) for path in candidates if path is not None)
    raise FileNotFoundError(
        f"MFEM executable not found or executable; checked: {checked}. "
        "Build the source in app/native/mfem or pass --binary.")


def yaml_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_settings(args: argparse.Namespace, frequencies: np.ndarray,
                 binary: Path) -> dict:
    return {
        "yaml_path": str(args.yaml.resolve()),
        "yaml_sha256": yaml_sha256(args.yaml),
        "solver_binary_path": str(binary.resolve()),
        "solver_binary_sha256": yaml_sha256(binary),
        "solver_mpi_ranks": args.mpi_ranks,
        "frequency_start_hz": float(frequencies[0]),
        "frequency_stop_hz": float(frequencies[-1]),
        "frequency_count": len(frequencies),
        "points_per_octave_requested": args.points_per_octave,
        "points_per_octave_actual": ((len(frequencies) - 1) /
                                     math.log2(frequencies[-1] / frequencies[0])),
        "elements_per_wavelength": args.elements_per_wavelength,
        "maximum_edge_m": (SOUND_SPEED_M_S / frequencies[-1] /
                           args.elements_per_wavelength),
        "quadrant_symmetry": True,
        "side_samples": args.side_samples,
        "axial_stations": args.axial_stations,
        "tetwild_edge_factor": args.tetwild_edge_factor,
    }


def prepare_mesh(args: argparse.Namespace, settings: dict, mesh_path: Path,
                 manifest_path: Path) -> dict:
    existing = None
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mesh_path.is_file() and existing == settings:
        print(f"mesh: already complete ({mesh_path})", flush=True)
        report_path = args.output_dir / "mesh_report.json"
        if not report_path.is_file():
            raise FileNotFoundError(report_path)
        return json.loads(report_path.read_text(encoding="utf-8"))
    if mesh_path.exists() or existing is not None:
        raise ValueError(
            "existing mesh/run settings do not match this request; choose a new "
            "--output-dir or pass --force-remesh")

    domain = build_quadrant_acoustic_domain(
        args.yaml, args.side_samples, args.axial_stations)
    diagonal = float(np.linalg.norm(np.ptp(domain.surface.bounds, axis=0)))
    maximum_edge = settings["maximum_edge_m"]
    report = write_tetwild_volume_mesh(
        domain, mesh_path, maximum_edge, threads=args.mesh_threads,
        edge_length_ratio=args.tetwild_edge_factor * maximum_edge / diagonal)
    values = {
        "nodes": report.nodes,
        "tetrahedra": report.tetrahedra,
        "maximum_requested_edge_m": maximum_edge,
        "maximum_tetrahedron_edge_m": report.maximum_tetrahedron_edge_m,
        "maximum_surface_deviation_m": report.maximum_label_match_error_m,
    }
    (args.output_dir / "mesh_report.json").write_text(
        json.dumps(values, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"mesh: {report.nodes} nodes, {report.tetrahedra} tetrahedra", flush=True)
    return values


def solve_frequency(binary: Path, mesh: Path, fields: Path,
                    index: int, frequency: float, mpi_ranks: int = 1) -> str:
    prefix = fields / f"d{index:03d}"
    summary = Path(f"{prefix}_summary.csv")
    mouth = Path(f"{prefix}_mouth.csv")
    throat = Path(f"{prefix}_throat.csv")
    if summary.is_file() and mouth.is_file() and throat.is_file():
        return "already complete"
    command = [str(binary), str(mesh), f"{frequency:.17g}",
               "--output-prefix", str(prefix), "--quadrant-symmetry"]
    if mpi_ranks > 1:
        command = ["mpirun", "-np", str(mpi_ranks), *command]
    result = subprocess.run(command, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else "complete"


def solve_sweep(binary: Path, mesh: Path, fields: Path,
                frequencies: np.ndarray, workers: int, mpi_ranks: int = 1) -> None:
    fields.mkdir(parents=True, exist_ok=True)
    np.savetxt(fields / "frequencies.csv", frequencies, delimiter=",",
               header="frequency_hz", comments="")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {
            executor.submit(solve_frequency, binary, mesh, fields, index,
                            float(frequency), mpi_ranks): (index, frequency)
            for index, frequency in enumerate(frequencies)
        }
        completed = 0
        for future in as_completed(jobs):
            index, frequency = jobs[future]
            completed += 1
            print(f"[{completed}/{len(frequencies)}] d{index:03d} "
                  f"{frequency:.3f} Hz: {future.result()}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", default="Interior FEM")
    parser.add_argument("--start-hz", type=float, default=500.0)
    parser.add_argument("--stop-hz", type=float, default=8_000.0)
    parser.add_argument("--points-per-octave", type=float, default=12.0)
    parser.add_argument("--elements-per-wavelength", type=float, default=8.0)
    parser.add_argument("--workers", type=int,
                        default=min(10, max(1, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--mesh-threads", type=int,
                        default=min(20, os.cpu_count() or 1))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--mpi-ranks", type=int, default=1,
                        help="MPI ranks per frequency (use with the parallel backend)")
    parser.add_argument("--side-samples", type=int, default=32)
    parser.add_argument("--axial-stations", type=int, default=44)
    parser.add_argument("--tetwild-edge-factor", type=float, default=0.46)
    parser.add_argument("--allow-above-validated-limit", action="store_true")
    parser.add_argument("--force-remesh", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if not args.yaml.is_file():
        raise FileNotFoundError(args.yaml)
    if args.workers < 1 or args.mesh_threads < 1 or args.mpi_ranks < 1:
        raise ValueError("worker counts must be positive")
    if args.elements_per_wavelength <= 0.0:
        raise ValueError("elements per wavelength must be positive")
    if args.stop_hz > VALIDATED_MAXIMUM_HZ and not args.allow_above_validated_limit:
        raise ValueError(
            f"the current MFEM/UMFPACK backend is validated only through "
            f"{VALIDATED_MAXIMUM_HZ:g} Hz; pass --allow-above-validated-limit "
            "only for deliberate backend experiments")
    binary = find_binary(args.binary)
    frequencies = frequency_grid(args.start_hz, args.stop_hz,
                                  args.points_per_octave)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = run_settings(args, frequencies, binary)
    manifest_path = args.output_dir / "run_settings.json"
    mesh_path = args.output_dir / "interior_quadrant.msh"
    if args.force_remesh:
        mesh_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        shutil.rmtree(args.output_dir / "fields", ignore_errors=True)
    prepare_mesh(args, settings, mesh_path, manifest_path)
    solve_sweep(binary, mesh_path, args.output_dir / "fields",
                frequencies, args.workers, args.mpi_ranks)
    generate_review(args.output_dir / "fields", args.output_dir, args.title)
    print(f"review: {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
