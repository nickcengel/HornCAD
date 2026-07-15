#!/usr/bin/env python3
"""Export and run native NumCalc exterior-acoustics comparison cases."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import subprocess
import time
from typing import Iterable

import numpy as np
import trimesh

try:
    from .helmholtz_bem_3d import (
        AcousticMesh, MeshSettings, build_acoustic_mesh,
        build_quadrant_acoustic_mesh, receiver_directions,
    )
except ImportError:
    from helmholtz_bem_3d import (
        AcousticMesh, MeshSettings, build_acoustic_mesh,
        build_quadrant_acoustic_mesh, receiver_directions,
    )


@dataclass(frozen=True)
class NumCalcCase:
    root: Path
    source_dir: Path
    boundary_elements: int
    evaluation_points: int
    throat_start: int
    throat_end: int
    velocity_m_s: float


@dataclass(frozen=True)
class NumCalcRun:
    wall_time_s: float
    equations: int
    iterations: int
    relative_error: float
    converged: bool


def reflect_quadrant_mesh(mesh: AcousticMesh) -> AcousticMesh:
    """Build an exact connected full mesh from a positive-X/Y quadrant."""
    if mesh.symmetry_planes != ("x=0", "y=0"):
        raise ValueError("expected an x/y quadrant mesh")
    vertices: list[np.ndarray] = []
    faces: list[list[int]] = []
    domains: list[int] = []
    coordinate_index: dict[tuple[float, float, float], int] = {}
    source_vertices = np.asarray(mesh.surface.vertices, dtype=float)
    source_faces = np.asarray(mesh.surface.faces, dtype=int)
    for x_sign, y_sign in ((1.0, 1.0), (-1.0, 1.0),
                           (1.0, -1.0), (-1.0, -1.0)):
        local = []
        for point in source_vertices:
            reflected = np.asarray(
                [x_sign * point[0], y_sign * point[1], point[2]])
            reflected[np.abs(reflected) < 5e-13] = 0.0
            key = tuple(np.round(reflected, 12))
            if key not in coordinate_index:
                coordinate_index[key] = len(vertices)
                vertices.append(reflected)
            local.append(coordinate_index[key])
        image_faces = (source_faces[:, [0, 2, 1]]
                       if x_sign * y_sign < 0 else source_faces)
        for face, domain in zip(image_faces, mesh.domain_indices):
            faces.append([local[int(index)] for index in face])
            domains.append(int(domain))
    surface = trimesh.Trimesh(vertices=np.asarray(vertices),
                              faces=np.asarray(faces), process=False)
    if not surface.is_winding_consistent:
        raise ValueError("reflected NumCalc control mesh has inconsistent winding")
    return AcousticMesh(surface, np.asarray(domains, dtype=np.uint32),
                        mesh.source_area_m2, mesh.mouth_center_m,
                        mesh.mouth_ring_m, mesh.report,
                        mesh.content_hash + "-reflected-full")


def _write_nodes(path: Path, identifiers: np.ndarray,
                 points: np.ndarray) -> None:
    lines = [str(len(points))]
    lines.extend(
        f"{int(identifier)} {point[0]:.17g} {point[1]:.17g} {point[2]:.17g}"
        for identifier, point in zip(identifiers, points))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_elements(path: Path, identifiers: np.ndarray, faces: np.ndarray,
                    *, property_id: int, group_id: int) -> None:
    lines = [str(len(faces))]
    lines.extend(
        f"{int(identifier)} {int(face[0])} {int(face[1])} {int(face[2])} "
        f"{property_id} 0 {group_id}"
        for identifier, face in zip(identifiers, faces))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evaluation_mesh(points: np.ndarray, first_node: int = 1_000_000,
                     first_element: int = 2_000_000
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Make tiny disconnected evaluation triangles containing exact points."""
    points = np.asarray(points, dtype=float)
    scale = max(float(np.max(np.linalg.norm(points, axis=1))), 1.0) * 1e-7
    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    requested_indices: list[int] = []
    for point in points:
        radial = point / max(float(np.linalg.norm(point)), 1e-30)
        seed = np.asarray([0.0, 0.0, 1.0])
        if abs(float(radial @ seed)) > 0.9:
            seed = np.asarray([0.0, 1.0, 0.0])
        tangent = np.cross(radial, seed)
        tangent /= np.linalg.norm(tangent)
        bitangent = np.cross(radial, tangent)
        base = len(vertices)
        requested_indices.append(base)
        vertices.extend((point, point + scale * tangent,
                         point + scale * bitangent))
        faces.append((first_node + base, first_node + base + 1,
                      first_node + base + 2))
    node_ids = np.arange(first_node, first_node + len(vertices), dtype=int)
    element_ids = np.arange(first_element, first_element + len(faces), dtype=int)
    return (np.asarray(vertices), np.asarray(faces, dtype=int), node_ids,
            element_ids), np.asarray(requested_indices, dtype=int)


def far_field_points(mouth_center_m: np.ndarray, frequency_hz: float,
                     sound_speed_m_s: float, angles_deg: Iterable[float]
                     ) -> tuple[np.ndarray, dict[str, slice]]:
    angles = np.asarray(tuple(angles_deg), dtype=float)
    radius = max(20.0 * sound_speed_m_s / frequency_hz,
                 20.0 * float(np.linalg.norm(mouth_center_m)) + 1.0)
    blocks = []
    cuts: dict[str, slice] = {}
    for name, azimuth in (("horizontal", 0.0), ("diagonal", 45.0),
                          ("vertical", 90.0)):
        start = sum(len(block) for block in blocks)
        block = mouth_center_m + radius * receiver_directions(angles, azimuth).T
        blocks.append(block)
        cuts[name] = slice(start, start + len(block))
    return np.vstack(blocks), cuts


def export_numcalc_case(root: Path, mesh: AcousticMesh, frequency_hz: float,
                        evaluation_points_m: np.ndarray, *, method: str = "mlfmm",
                        linear_solver: str = "iterative",
                        sound_speed_m_s: float = 343.21,
                        density_kg_m3: float = 1.2041) -> NumCalcCase:
    """Write a standalone NumCalc project from a HornCAD acoustic mesh."""
    method_ids = {"dense": 0, "fmm": 1, "mlfmm": 4}
    if method not in method_ids:
        raise ValueError(f"unknown NumCalc method {method!r}")
    if linear_solver not in ("iterative", "direct"):
        raise ValueError(f"unknown NumCalc linear solver {linear_solver!r}")
    if linear_solver == "direct" and method != "dense":
        raise ValueError("NumCalc direct solve is available only for dense BEM")
    source_dir = root / "NumCalc" / "source_1"
    object_dir = root / "ObjectMeshes" / "Reference"
    evaluation_dir = root / "EvaluationGrids" / "FarField"
    for directory in (source_dir, object_dir, evaluation_dir):
        directory.mkdir(parents=True, exist_ok=True)

    rigid = np.flatnonzero(np.asarray(mesh.domain_indices) == 0)
    throat = np.flatnonzero(np.asarray(mesh.domain_indices) == 1)
    if not len(throat):
        raise ValueError("NumCalc export requires driven throat elements")
    order = np.concatenate((rigid, throat))
    faces = np.asarray(mesh.surface.faces, dtype=int)[order]
    vertices = np.asarray(mesh.surface.vertices, dtype=float)
    boundary_node_ids = np.arange(len(vertices), dtype=int)
    boundary_element_ids = np.arange(len(faces), dtype=int)
    _write_nodes(object_dir / "Nodes.txt", boundary_node_ids, vertices)
    _write_elements(object_dir / "Elements.txt", boundary_element_ids,
                    faces, property_id=0, group_id=1)

    (eval_vertices, eval_faces, eval_node_ids, eval_element_ids), requested = (
        _evaluation_mesh(evaluation_points_m))
    _write_nodes(evaluation_dir / "Nodes.txt", eval_node_ids, eval_vertices)
    _write_elements(evaluation_dir / "Elements.txt", eval_element_ids,
                    eval_faces, property_id=2, group_id=2)

    symmetry = len(mesh.symmetry_planes)
    if symmetry not in (0, 2):
        raise ValueError("NumCalc adapter supports full geometry or x/y quadrant")
    velocity = 1.0 / mesh.source_area_m2
    throat_start = len(rigid)
    throat_end = len(faces) - 1
    total_nodes = len(vertices) + len(eval_vertices)
    total_elements = len(faces) + len(eval_faces)
    symmetry_text = ("SYMMETRY\n1 1 0\n0.0 0.0 0.0\n"
                     if symmetry else "# SYMMETRY\n# 0 0 0\n# 0.0 0.0 0.0\n")
    nc_input = f"""## HornCAD native NumCalc case
Mesh2HRTF 1.3.0
##
HornCAD exterior radiation
##
## Controlparameter I
0 0 0 0 7 0
##
## Controlparameter II
1 1 0.000001 0.0 1 0 0
##
## Load Frequency Curve
0 2
0.000000 0.000000e+00 0.0
0.000001 {frequency_hz:.17g} 0.0
##
## 1. Main Parameters I
2 {total_elements} {total_nodes} 0 {symmetry} 2 1 {method_ids[method]} {4 if linear_solver == "direct" else 0}
##
## 2. Main Parameters II
0 0 0 0.0 1 0 0
##
## 3. Main Parameters III
0 0 0 0
##
## 4. Main Parameters IV
{sound_speed_m_s:.17g} {density_kg_m3:.17g} 1.0 0.0 0.0 0.0 0.0
##
NODES
../../ObjectMeshes/Reference/Nodes.txt
../../EvaluationGrids/FarField/Nodes.txt
##
ELEMENTS
../../ObjectMeshes/Reference/Elements.txt
../../EvaluationGrids/FarField/Elements.txt
##
{symmetry_text}##
BOUNDARY
ELEM 0 TO {throat_start - 1} VELO 0.0 -1 0.0 -1
ELEM {throat_start} TO {throat_end} VELO {velocity:.17g} -1 0.0 -1
RETU
##
# CURVES
##
POST PROCESS
##
END
"""
    (source_dir / "NC.inp").write_text(nc_input, encoding="utf-8")
    metadata = {
        "frequency_hz": frequency_hz, "method": method,
        "linear_solver": linear_solver,
        "symmetry_planes": list(mesh.symmetry_planes),
        "boundary_vertices": len(vertices), "boundary_elements": len(faces),
        "source_area_m2": mesh.source_area_m2, "velocity_m_s": velocity,
        "evaluation_points_m": np.asarray(evaluation_points_m).tolist(),
        "evaluation_requested_node_offsets": requested.tolist(),
    }
    (root / "horncad-numcalc.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return NumCalcCase(root, source_dir, len(faces), len(evaluation_points_m),
                       throat_start, throat_end, velocity)


def run_numcalc(case: NumCalcCase, executable: Path,
                max_iterations: int = 250) -> NumCalcRun:
    started = time.perf_counter()
    result = subprocess.run(
        [str(executable), "-nitermax", str(max_iterations)], cwd=case.source_dir,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    elapsed = time.perf_counter() - started
    equation_match = re.search(r"Number of equations = (\d+)", result.stdout)
    iteration_match = re.search(
        r"CGS solver: number of iterations = (\d+), relative error = ([0-9.eE+-]+)",
        (case.source_dir / "NC.out").read_text(encoding="utf-8"))
    metadata = json.loads((case.root / "horncad-numcalc.json").read_text())
    direct = metadata["linear_solver"] == "direct"
    equations = int(equation_match.group(1)) if equation_match else 0
    iterations = int(iteration_match.group(1)) if iteration_match else 0
    relative_error = (float(iteration_match.group(2)) if iteration_match
                      else 0.0 if direct else math.nan)
    converged = (result.returncode == 0
                 and "Maximum number of iterations is reached" not in result.stdout
                 and math.isfinite(relative_error)
                 and (direct or relative_error < 1e-6))
    run = NumCalcRun(elapsed, equations, iterations, relative_error, converged)
    (case.root / "run.json").write_text(json.dumps({
        "command": [str(executable), "-nitermax", str(max_iterations)],
        "returncode": result.returncode, "wall_time_s": elapsed,
        "equations": equations, "iterations": iterations,
        "relative_error": relative_error, "converged": converged,
        "stdout": result.stdout,
    }, indent=2) + "\n", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"NumCalc failed with code {result.returncode}:\n{result.stdout}")
    if not converged:
        raise RuntimeError(
            f"NumCalc did not converge: iterations={iterations}, "
            f"relative_error={relative_error:.3g}")
    return run


def read_evaluation_pressure(case_root: Path) -> np.ndarray:
    """Return pressure at the first vertex of each tiny evaluation triangle."""
    values = np.loadtxt(
        case_root / "NumCalc/source_1/be.out/be.1/pEvalGrid", skiprows=3)
    pressure = values[:, 1] + 1j * values[:, 2]
    metadata = json.loads((case_root / "horncad-numcalc.json").read_text())
    return pressure[np.asarray(metadata["evaluation_requested_node_offsets"], dtype=int)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path)
    parser.add_argument("--numcalc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frequency", type=float, default=500.0)
    parser.add_argument("--mesh-maximum-frequency", type=float)
    parser.add_argument("--elements-per-wavelength", type=float, default=6.0)
    parser.add_argument("--geometry", choices=("quadrant", "mirrored-full", "full"),
                        default="quadrant")
    parser.add_argument("--method", choices=("dense", "fmm", "mlfmm"), default="mlfmm")
    parser.add_argument("--linear-solver", choices=("iterative", "direct"),
                        default="iterative")
    parser.add_argument("--angles", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = MeshSettings(args.mesh_maximum_frequency or args.frequency,
                            args.elements_per_wavelength)
    if args.geometry == "quadrant":
        mesh = build_quadrant_acoustic_mesh(args.yaml, settings)
    elif args.geometry == "mirrored-full":
        mesh = reflect_quadrant_mesh(
            build_quadrant_acoustic_mesh(args.yaml, settings))
    else:
        mesh = build_acoustic_mesh(args.yaml, settings)
    points, _ = far_field_points(mesh.mouth_center_m, args.frequency, 343.21,
                                 np.linspace(0.0, 90.0, args.angles))
    case = export_numcalc_case(args.output_dir, mesh, args.frequency, points,
                               method=args.method,
                               linear_solver=args.linear_solver)
    run_numcalc(case, args.numcalc, args.max_iterations)
    print(case.root)


if __name__ == "__main__":
    main()
