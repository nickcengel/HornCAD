#!/usr/bin/env python3
"""Reproducible 3-D exterior BEM comparison pipeline for HornCAD.

Coordinates are metres.  The geometry origin is the throat centre and radiation
results are referred to the authored mouth centre.  The source is a uniform
axial piston; observers are evaluation points and never part of the boundary.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import multiprocessing
import sys
import tempfile
import time
from typing import Any, Iterable

# Keep JIT and plotting caches writable and shared by spawned frequency workers.
# This avoids recompilation/font scans when the user's home cache is restricted.
_CACHE_ROOT = Path(tempfile.gettempdir()) / "horncad-bem-cache"
os.environ.setdefault("NUMBA_CACHE_DIR", str(_CACHE_ROOT / "numba"))
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT / "xdg"))

import bempp_cl.api as bempp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedFormatter, FixedLocator, NullFormatter
import numpy as np
import trimesh

try:
    from . import export_horncad as geometry
    from .webster_1d import Medium, frequency_grid, horncad_area_profile
except ImportError:
    import export_horncad as geometry
    from webster_1d import Medium, frequency_grid, horncad_area_profile


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
MESH_TIERS = {"preview": 6.0, "production": 6.0, "verification-8": 8.0,
              "verification-10": 10.0,
              "verification-12": 12.0}
CUT_AZIMUTHS = {"horizontal": 0.0, "diagonal": 45.0, "vertical": 90.0}
GEOMETRY_SEED_SIDE_SAMPLES = 12
GEOMETRY_SEED_AXIAL_STATIONS = 16


@dataclass(frozen=True)
class AcousticMedium:
    density_kg_m3: float = 1.2041
    sound_speed_m_s: float = 343.21


@dataclass(frozen=True)
class MeshSettings:
    maximum_frequency_hz: float = 8_000.0
    elements_per_wavelength: float = 6.0
    curvature_tolerance_m: float | None = None
    minimum_angle_deg: float = 0.01
    maximum_aspect_ratio: float = 3_000.0
    surface_mesher: str = "netgen"
    netgen_maxh_factor: float = 0.5

    @property
    def target_edge_m(self) -> float:
        if self.maximum_frequency_hz <= 0 or self.elements_per_wavelength <= 0:
            raise ValueError("maximum frequency and elements per wavelength must be positive")
        return AcousticMedium().sound_speed_m_s / (
            self.maximum_frequency_hz * self.elements_per_wavelength
        )


@dataclass(frozen=True)
class SourceDefinition:
    volume_velocity_m3_s: complex = 1.0 + 0.0j
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)


@dataclass
class MeshReport:
    triangles: int
    vertices: int
    estimated_dofs: int
    minimum_edge_m: float
    mean_edge_m: float
    maximum_edge_m: float
    target_edge_m: float
    minimum_angle_deg: float
    maximum_aspect_ratio: float
    watertight: bool
    winding_consistent: bool
    connected_components: int
    quality_failures: list[str]
    minimum_wavelength_m: float
    supported_maximum_frequency_hz: float
    estimated_dense_matrix_gib: float


@dataclass
class AcousticMesh:
    surface: trimesh.Trimesh
    domain_indices: np.ndarray
    source_area_m2: float
    mouth_center_m: np.ndarray
    mouth_ring_m: np.ndarray
    report: MeshReport
    content_hash: str
    symmetry_factor: int = 1
    symmetry_planes: tuple[str, ...] = ()


@dataclass
class ApertureObserver:
    positions_m: np.ndarray
    normals: np.ndarray
    area_weights_m2: np.ndarray
    projected_xy_m: np.ndarray
    offset_m: float = 0.001


@dataclass
class FrequencyResult:
    frequency_hz: float
    gmres_iterations: int
    dofs: int
    mouth_pressure: np.ndarray
    mouth_normal_velocity: np.ndarray
    full_exterior_pressure: dict[str, np.ndarray]
    ideal_aperture_pressure: dict[str, np.ndarray]
    metrics: dict[str, float]


@dataclass(frozen=True)
class PipelineSettings:
    frequencies_hz: tuple[float, ...]
    angles_deg: tuple[float, ...]
    mesh: MeshSettings = field(default_factory=MeshSettings)
    medium: AcousticMedium = field(default_factory=AcousticMedium)
    source: SourceDefinition = field(default_factory=SourceDefinition)
    observer_offset_m: float = 0.001
    gmres_tolerance: float = 1e-4
    gmres_max_iterations: int = 300
    formulation: str = "combined-field"
    solver_backend: str = "ngsolve-fmm"
    operator_assembler: str = "dense"
    direct_solve_max_dofs: int = 0
    full_sphere: bool = False
    maximum_workers: int = 0
    memory_limit_gib: float | None = None
    geometry_side_samples: int | None = None
    geometry_axial_stations: int | None = None
    fmm_min_order: int = 6
    fmm_order_factor: float = 0.8
    fmm_separation: float = 1.5
    fmm_max_direct: int = 100
    quadrant_symmetry: bool = True


@dataclass(frozen=True)
class ExecutionPlan:
    workers: int
    threads_per_worker: int
    cpu_count: int
    memory_limit_gib: float
    estimated_memory_per_worker_gib: float


def _physical_memory_gib() -> float:
    """Return installed memory without platform-specific subprocesses."""
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 8.0


def execution_plan(settings: PipelineSettings, mesh: AcousticMesh,
                   pending_frequencies: int) -> ExecutionPlan:
    """Allocate cores and memory for whole-solve throughput.

    NGSolve 6.2.2606's asymmetric full-source/quadrant-target hypersingular
    operator is not thread-safe. Quadrant solves therefore use one native
    thread per frequency and recover parallelism across frequency processes.
    """
    cpus = os.cpu_count() or 1
    memory_limit = settings.memory_limit_gib or 0.75 * _physical_memory_gib()
    if settings.solver_backend == "bempp-dense":
        per_worker = max(0.25, 5.0 * mesh.report.estimated_dense_matrix_gib)
    else:
        # Fits measured peaks at 13.8k DOF (1.97 GiB) and 38.9k DOF
        # (2.43 GiB), then adds 15% scheduling headroom.
        integration_dofs = mesh.report.estimated_dofs * mesh.symmetry_factor
        per_worker = 1.15 * (
            1.5 + integration_dofs * 30_000 / 1024 ** 3)
    memory_workers = max(1, int(memory_limit // per_worker))
    serial_quadrant_fmm = (settings.solver_backend == "ngsolve-fmm"
                           and settings.quadrant_symmetry)
    default_workers = (cpus if serial_quadrant_fmm else
                       max(1, cpus // 2) if settings.solver_backend == "ngsolve-fmm"
                       else cpus)
    requested = default_workers if settings.maximum_workers == 0 else max(1, settings.maximum_workers)
    workers = max(1, min(requested, cpus, memory_workers,
                         pending_frequencies or 1))
    threads = 1 if serial_quadrant_fmm else max(1, cpus // workers)
    return ExecutionPlan(workers, threads, cpus, memory_limit, per_worker)


def _jsonable(value: Any) -> Any:
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _hash_arrays(*arrays: np.ndarray, metadata: bytes = b"") -> str:
    digest = hashlib.sha256(metadata)
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        digest.update(str(contiguous.dtype).encode())
        digest.update(str(contiguous.shape).encode())
        digest.update(contiguous.tobytes())
    return digest.hexdigest()


def receiver_directions(angles_deg: np.ndarray, azimuth_deg: float) -> np.ndarray:
    polar = np.radians(angles_deg)
    azimuth = math.radians(azimuth_deg)
    return np.vstack((np.sin(polar) * math.cos(azimuth),
                      np.sin(polar) * math.sin(azimuth), np.cos(polar)))


def _triangle_quality(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    sides = np.sort(np.linalg.norm(mesh.triangles - np.roll(mesh.triangles, 1, axis=1), axis=2), axis=1)
    aspect = sides[:, 2] / np.maximum(sides[:, 0], 1e-15)
    cosine = np.clip((sides[:, 1] ** 2 + sides[:, 2] ** 2 - sides[:, 0] ** 2) /
                     np.maximum(2.0 * sides[:, 1] * sides[:, 2], 1e-30), -1.0, 1.0)
    minimum_angle = np.degrees(np.arccos(cosine))
    return minimum_angle, aspect


def mesh_quality_report(mesh: trimesh.Trimesh, settings: MeshSettings) -> MeshReport:
    edges = np.linalg.norm(mesh.vertices[mesh.edges_unique[:, 0]] - mesh.vertices[mesh.edges_unique[:, 1]], axis=1)
    angles, aspects = _triangle_quality(mesh)
    components = len(mesh.split(only_watertight=False))
    failures: list[str] = []
    tolerance = settings.target_edge_m * 1e-6 + 1e-12
    if float(edges.max()) > settings.target_edge_m + tolerance:
        failures.append("maximum_edge_exceeds_wavelength_limit")
    if float(angles.min()) < settings.minimum_angle_deg:
        failures.append("minimum_angle_below_limit")
    if float(aspects.max()) > settings.maximum_aspect_ratio:
        failures.append("aspect_ratio_above_limit")
    if not mesh.is_watertight:
        failures.append("not_watertight")
    if not mesh.is_winding_consistent:
        failures.append("inconsistent_orientation")
    if components != 1:
        failures.append("not_connected")
    supported = AcousticMedium().sound_speed_m_s / (settings.elements_per_wavelength * float(edges.max()))
    dofs = len(mesh.vertices)
    return MeshReport(len(mesh.faces), len(mesh.vertices), dofs, float(edges.min()),
                      float(edges.mean()), float(edges.max()), settings.target_edge_m,
                      float(angles.min()), float(aspects.max()), bool(mesh.is_watertight),
                      bool(mesh.is_winding_consistent), components, failures,
                      AcousticMedium().sound_speed_m_s / settings.maximum_frequency_hz,
                      supported, (dofs * dofs * 16) / 1024 ** 3)


def _authored_mesh(yaml_path: Path, side_samples: int, axial_stations: int) -> tuple[trimesh.Trimesh, np.ndarray, float]:
    """Create the closed obstacle in millimetres and return its authored mouth ring."""
    horncad_area_profile(yaml_path, 41)
    geometry.SIDE_SAMPLES = side_samples
    geometry.Z_STATIONS = axial_stations
    hp, vp = geometry.profile("h"), geometry.profile("v")
    length = float(geometry.PARAMS["length"])
    mouth_h, mouth_v = hp(length), vp(length)
    extension = max(0.0, float(geometry.PARAMS["throat_extension"]))
    rings: list[list[tuple[float, float, float]]] = []
    if extension > 0:
        count = max(2, round(axial_stations * extension / max(length, 1e-9)) + 1)
        rings.extend(geometry.conical_extension_ring(i / (count - 1)) for i in range(count))
    samples = geometry.adaptive_profile_z_samples(axial_stations, length, hp, vp)
    if extension > 0:
        samples = samples[1:]
    for z in samples:
        rings.append(geometry.ring_at(z / length, hp(z), vp(z), mouth_h, mouth_v))
    mouth_index = len(rings) - 1
    mouth_ring = np.asarray(rings[mouth_index], dtype=float)
    if geometry.PARAMS["mouth_rear_offset"] > 0:
        rings.append(geometry.mouth_rear_ring(rings, mouth_h, mouth_v))
    vertices, faces = geometry.build_body_mesh(rings, mouth_index, mouth_h, mouth_v)
    throat_radius = float(geometry.PARAMS["r0"])
    body = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    throat_z = -extension
    overlap, depth = 0.3, 2.0
    top, bottom = throat_z + overlap, throat_z - depth
    cap = trimesh.creation.cylinder(radius=throat_radius + overlap, height=top - bottom,
        sections=max(32, side_samples * 4), transform=trimesh.transformations.translation_matrix((0, 0, (top + bottom) / 2)))
    combined = trimesh.boolean.union((body, cap), engine="manifold")
    if isinstance(combined, list):
        combined = trimesh.util.concatenate(combined)
    combined.process(validate=True)
    trimesh.repair.fix_normals(combined, multibody=True)
    return combined, mouth_ring, throat_radius


def build_acoustic_mesh(yaml_path: Path, settings: MeshSettings,
                        side_samples: int | None = None, axial_stations: int | None = None) -> AcousticMesh:
    """Build, edge-refine, validate and mark a physically closed acoustic boundary."""
    # Ring density is only a geometry seed; actual acceptance is based on every edge.
    if settings.surface_mesher not in {"netgen", "subdivide"}:
        raise ValueError("surface_mesher must be 'netgen' or 'subdivide'")
    if not 0 < settings.netgen_maxh_factor <= 1:
        raise ValueError("netgen_maxh_factor must be in (0, 1]")
    if settings.surface_mesher == "netgen":
        # This seed describes the authored faceted geometry; Netgen supplies
        # wavelength refinement. Increasing it with frequency creates
        # overlapping lip facets before remeshing on the current exporter.
        side_samples = side_samples or GEOMETRY_SEED_SIDE_SAMPLES
        axial_stations = axial_stations or GEOMETRY_SEED_AXIAL_STATIONS
    else:
        side_samples = side_samples or max(8, int(math.ceil(0.30 / settings.target_edge_m)))
        axial_stations = axial_stations or max(10, int(math.ceil(0.30 / settings.target_edge_m)))
    mesh, mouth_ring_mm, throat_radius_mm = _authored_mesh(yaml_path, side_samples, axial_stations)
    mesh.apply_scale(1e-3)
    throat_z = (-max(0.0, float(geometry.PARAMS["throat_extension"])) + 0.3) * 1e-3
    if settings.surface_mesher == "netgen":
        throat_points = mesh.vertices[
            np.abs(mesh.vertices[:, 2] - throat_z) < 1e-8]
        mesh = _netgen_surface_remesh(
            mesh, settings.target_edge_m * settings.netgen_maxh_factor,
            throat_points,
            min(settings.target_edge_m * settings.netgen_maxh_factor,
                2 * math.pi * throat_radius_mm * 1e-3 / 32))
    else:
        # Selective ``subdivide_to_size`` leaves T-junctions where refined and
        # unrefined faces meet. Conforming global passes preserve closure.
        for _ in range(12):
            edge_lengths = np.linalg.norm(
                mesh.vertices[mesh.edges_unique[:, 0]] - mesh.vertices[mesh.edges_unique[:, 1]], axis=1
            )
            if float(edge_lengths.max()) <= settings.target_edge_m + 1e-12:
                break
            vertices, faces = trimesh.remesh.subdivide(mesh.vertices, mesh.faces)
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
        else:
            raise ValueError("mesh refinement did not reach the wavelength edge limit")
    trimesh.repair.fix_normals(mesh, multibody=True)
    centers, normals = mesh.triangles_center, mesh.face_normals
    # `_authored_mesh` overlaps the throat closure by 0.3 mm so the driven
    # face is the planar top at -extension + overlap.
    radius = np.hypot(centers[:, 0], centers[:, 1])
    planar_throat = np.max(np.abs(mesh.triangles[:, :, 2] - throat_z), axis=1) < 1e-8
    source_faces = planar_throat & (normals[:, 2] > 0.8) & (
        radius < throat_radius_mm * 0.001001)
    if not np.any(source_faces):
        raise ValueError("failed to identify the driven throat piston")
    domains = source_faces.astype(np.uint32)
    report = mesh_quality_report(mesh, settings)
    if report.quality_failures:
        raise ValueError("invalid acoustic mesh: " + ", ".join(report.quality_failures))
    source_area = float(mesh.area_faces[source_faces].sum())
    mouth_ring = mouth_ring_mm * 1e-3
    mouth_center = np.array([0.0, 0.0, float(np.mean(mouth_ring[:, 2]))])
    content_hash = _hash_arrays(mesh.vertices, mesh.faces, domains,
                                metadata=json.dumps(_jsonable(asdict(settings)), sort_keys=True).encode())
    return AcousticMesh(mesh, domains, source_area, mouth_center, mouth_ring, report, content_hash)


def build_quadrant_acoustic_mesh(yaml_path: Path, settings: MeshSettings,
                                  side_samples: int | None = None,
                                  axial_stations: int | None = None) -> AcousticMesh:
    """Cut the validated full mesh to the open +x/+y symmetry quadrant.

    The cut planes are mathematical reflection boundaries, not physical BEM
    faces. ``source_area_m2`` deliberately retains the full piston area so a
    unit total volume velocity produces the same local Neumann data as the
    full-geometry reference.
    """
    full = build_acoustic_mesh(yaml_path, settings, side_samples, axial_stations)
    side_samples = side_samples or GEOMETRY_SEED_SIDE_SAMPLES
    axial_stations = axial_stations or GEOMETRY_SEED_AXIAL_STATIONS
    authored, _, throat_radius_mm = _authored_mesh(
        yaml_path, side_samples, axial_stations)
    authored.apply_scale(1e-3)
    capped = authored
    for normal in (np.asarray([1.0, 0.0, 0.0]),
                   np.asarray([0.0, 1.0, 0.0])):
        capped = trimesh.intersections.slice_mesh_plane(
            capped, normal, np.zeros(3), cap=True)
    # The intersection of the two temporary caps can contain one collinear
    # T-junction: edges a-m, m-z and a-z. Split the face using a-z at m rather
    # than retaining a zero-area triangle that crashes Netgen's STL front-end.
    capped.update_faces(capped.nondegenerate_faces(height=1e-12))
    capped.remove_unreferenced_vertices()
    capped.merge_vertices(digits_vertex=12)
    for _ in range(32):
        edge_keys, incidence = np.unique(capped.edges_sorted, axis=0,
                                         return_counts=True)
        boundary_edges = edge_keys[incidence == 1]
        if not len(boundary_edges):
            break
        boundary_ids = np.unique(boundary_edges)
        repaired = False
        for a, z in boundary_edges:
            start, end = capped.vertices[a], capped.vertices[z]
            direction = end - start
            length_squared = float(np.dot(direction, direction))
            if length_squared <= 1e-24:
                continue
            relative = capped.vertices[boundary_ids] - start
            fraction = relative @ direction / length_squared
            distance = np.linalg.norm(
                relative - fraction[:, None] * direction, axis=1)
            interior = boundary_ids[(fraction > 1e-9) & (fraction < 1 - 1e-9)
                                    & (distance < 1e-10)]
            if not len(interior):
                continue
            face_index = next((index for index, face in enumerate(capped.faces)
                               if a in face and z in face), None)
            if face_index is None:
                continue
            face = list(map(int, capped.faces[face_index]))
            other = next(index for index in face if index not in (a, z))
            ordered = list(interior[np.argsort(
                (capped.vertices[interior] - start) @ direction)])
            chain = [int(a), *map(int, ordered), int(z)]
            if (face.index(a) + 1) % 3 != face.index(z):
                chain.reverse()
            replacement = [(chain[index], chain[index + 1], other)
                           for index in range(len(chain) - 1)]
            capped.faces = np.vstack(
                (np.delete(capped.faces, face_index, axis=0), replacement))
            repaired = True
            break
        if not repaired:
            break
    trimesh.repair.fix_normals(capped, multibody=True)
    if not capped.is_watertight:
        raise ValueError("temporary quadrant meshing caps are not closed")

    throat_z = (-max(0.0, float(geometry.PARAMS["throat_extension"]))
                + 0.3) * 1e-3
    throat_points = capped.vertices[
        np.abs(capped.vertices[:, 2] - throat_z) < 1e-8]
    quadrant = _netgen_surface_remesh(
        capped, settings.target_edge_m * settings.netgen_maxh_factor,
        throat_points,
        min(settings.target_edge_m * settings.netgen_maxh_factor,
            2 * math.pi * throat_radius_mm * 1e-3 / 32))
    cap_faces = ((np.max(np.abs(quadrant.triangles[:, :, 0]), axis=1) < 1e-10)
                 | (np.max(np.abs(quadrant.triangles[:, :, 1]), axis=1) < 1e-10))
    quadrant.update_faces(~cap_faces)
    quadrant.remove_unreferenced_vertices()
    quadrant.merge_vertices(digits_vertex=12)
    quadrant.update_faces(quadrant.unique_faces())
    quadrant.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(quadrant, multibody=True)

    edge_keys, incidence = np.unique(quadrant.edges_sorted, axis=0,
                                     return_counts=True)
    if np.any(incidence > 2):
        raise ValueError("quadrant symmetry cut created non-manifold edges")
    boundary_edges = edge_keys[incidence == 1]
    boundary_vertices = quadrant.vertices[np.unique(boundary_edges)]
    tolerance = max(settings.target_edge_m * 1e-8, 1e-12)
    on_symmetry_plane = ((np.abs(boundary_vertices[:, 0]) <= tolerance)
                         | (np.abs(boundary_vertices[:, 1]) <= tolerance))
    if not np.all(on_symmetry_plane):
        raise ValueError("quadrant has boundary edges away from symmetry planes")
    if (not quadrant.is_winding_consistent
            or len(quadrant.split(only_watertight=False)) != 1):
        raise ValueError("quadrant must be connected and consistently oriented")

    full_source_centers = full.surface.triangles_center[full.domain_indices == 1]
    throat_z = float(np.median(full_source_centers[:, 2]))
    throat_radius = throat_radius_mm * 0.001001
    centers, normals = quadrant.triangles_center, quadrant.face_normals
    planar_throat = np.max(np.abs(quadrant.triangles[:, :, 2] - throat_z),
                           axis=1) <= tolerance
    source_faces = (planar_throat & (normals[:, 2] > 0.8)
                    & (np.hypot(centers[:, 0], centers[:, 1])
                       <= throat_radius + tolerance))
    if not np.any(source_faces):
        raise ValueError("failed to identify quadrant throat source")
    domains = source_faces.astype(np.uint32)
    report = mesh_quality_report(quadrant, settings)
    report.quality_failures = [failure for failure in report.quality_failures
                               if failure != "not_watertight"]
    mouth_ring = full.mouth_ring_m
    content_hash = _hash_arrays(
        quadrant.vertices, quadrant.faces, domains,
        metadata=b"even-even-quadrant-x-y")
    quadrant_source_area = float(
        4.0 * quadrant.area_faces[source_faces].sum())
    return AcousticMesh(quadrant, domains, quadrant_source_area,
                        full.mouth_center_m, mouth_ring, report, content_hash,
                        symmetry_factor=4, symmetry_planes=("x=0", "y=0"))


def _netgen_surface_remesh(source: trimesh.Trimesh, maximum_size_m: float,
                           refinement_points_m: np.ndarray | None = None,
                           refinement_size_m: float | None = None) -> trimesh.Trimesh:
    """Create a watertight, shape-regular triangular surface from an STL shell."""
    from netgen.meshing import MeshingParameters, MeshingStep, Point3d
    from netgen.stl import STLGeometry

    fd, filename = tempfile.mkstemp(prefix="horncad-bem-surface-", suffix=".stl")
    os.close(fd)
    try:
        source.export(filename)
        geometry_stl = STLGeometry(filename)
        if refinement_points_m is not None and refinement_size_m is not None:
            for point in np.asarray(refinement_points_m):
                geometry_stl.RestrictH(Point3d(*map(float, point)), refinement_size_m)
        parameters = MeshingParameters(
            maxh=maximum_size_m, perfstepsend=MeshingStep.MESHSURFACE)
        generated = geometry_stl.GenerateMesh(mp=parameters)
        vertices = np.asarray([[point.p[0], point.p[1], point.p[2]]
                               for point in generated.Points()])
        faces = np.asarray([[vertex.nr - 1 for vertex in element.vertices]
                            for element in generated.Elements2D()], dtype=np.int64)
        result = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
        trimesh.repair.fix_normals(result, multibody=True)
        return result
    finally:
        os.unlink(filename)


def acoustic_body_mesh(yaml_path: Path, side_samples: int = 16, axial_stations: int = 18,
                       maximum_frequency_hz: float | None = None,
                       elements_per_wavelength: float = 8.0) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Compatibility wrapper; new callers should use :func:`build_acoustic_mesh`."""
    if side_samples < 6 or axial_stations < 8:
        raise ValueError("BEM mesh requires at least 6 side samples and 8 axial stations")
    if maximum_frequency_hz is None:
        mesh, _, throat_radius = _authored_mesh(yaml_path, side_samples, axial_stations)
        mesh.apply_scale(1e-3)
        centers, normals = mesh.triangles_center, mesh.face_normals
        radius = np.hypot(centers[:, 0], centers[:, 1])
        domains = ((normals[:, 2] > .8) & (radius < throat_radius * .00098)).astype(np.uint32)
        return mesh, domains
    result = build_acoustic_mesh(yaml_path, MeshSettings(maximum_frequency_hz, elements_per_wavelength),
                                 side_samples, axial_stations)
    return result.surface, result.domain_indices


def piston_boundary_values(mesh: AcousticMesh, source: SourceDefinition,
                           frequency_hz: float, medium: AcousticMedium) -> tuple[complex, complex]:
    """Return uniform velocity and Neumann pressure derivative ``dp/dn``."""
    velocity = source.volume_velocity_m3_s / mesh.source_area_m2
    neumann = -1j * 2 * math.pi * frequency_hz * medium.density_kg_m3 * velocity
    return velocity, neumann


def make_aperture_observer(mesh: AcousticMesh, offset_m: float = 0.001) -> ApertureObserver:
    """Triangulate the curved authored mouth opening without adding a boundary."""
    ring = mesh.mouth_ring_m
    centre = mesh.mouth_center_m
    triangles = np.asarray([[centre, ring[i], ring[(i + 1) % len(ring)]] for i in range(len(ring))])
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    flip = cross[:, 2] < 0
    triangles[flip, 1], triangles[flip, 2] = triangles[flip, 2].copy(), triangles[flip, 1].copy()
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1)[:, None], 1e-30)
    positions = triangles.mean(axis=1) + offset_m * normals
    return ApertureObserver(positions, normals, area, positions[:, :2].copy(), offset_m)


def _combined_field_solve(grid: bempp.Grid, neumann_value: complex, frequency_hz: float,
                          medium: AcousticMedium, tolerance: float, max_iterations: int,
                          operator_assembler: str = "dense", direct_solve_max_dofs: int = 0):
    """Regularized Burton-Miller equation for the exterior Neumann problem."""
    space = bempp.function_space(grid, "P", 1)

    @bempp.complex_callable
    def prescribed(_x, _n, domain_index, result):
        result[0] = neumann_value if domain_index == 1 else 0.0

    g = bempp.GridFunction(space, fun=prescribed)
    trace, iterations = _combined_field_solve_grid_function(
        space, g, frequency_hz, medium, tolerance, max_iterations,
        operator_assembler, direct_solve_max_dofs)
    return space, trace, g, iterations


def _combined_field_solve_grid_function(
        space: Any, g: Any, frequency_hz: float, medium: AcousticMedium,
        tolerance: float, max_iterations: int,
        operator_assembler: str = "dense", direct_solve_max_dofs: int = 0):
    """Solve the combined-field equation for an arbitrary Neumann grid function."""
    k = 2 * math.pi * frequency_hz / medium.sound_speed_m_s
    identity = bempp.operators.boundary.sparse.identity(space, space, space)
    if operator_assembler not in {"dense", "fmm"}:
        raise ValueError("operator assembler must be 'dense' or 'fmm'")
    options = {"assembler": operator_assembler}
    double = bempp.operators.boundary.helmholtz.double_layer(space, space, space, k, **options)
    adjoint = bempp.operators.boundary.helmholtz.adjoint_double_layer(space, space, space, k, **options)
    single = bempp.operators.boundary.helmholtz.single_layer(space, space, space, k, **options)
    hyper = bempp.operators.boundary.helmholtz.hypersingular(space, space, space, k, **options)
    # W has inverse-length units, so the dimensionless double-layer term must
    # be scaled by k (not 1/k).  The positive imaginary coupling removes the
    # real-axis interior resonances of either constituent equation.
    eta = 1j * max(k, 1e-12)
    lhs = hyper + eta * (0.5 * identity - double)

    # Exterior Calderon convention:
    #   D p = (-M/2 - K') g,  (M/2 - K) p = -V g.
    # The former positive RHS signs selected the wrong trace branch and fail
    # the analytic pulsating-sphere Neumann problem.
    rhs = (-0.5 * identity - adjoint) * g - eta * single * g
    if direct_solve_max_dofs > 0 and space.global_dof_count <= direct_solve_max_dofs:
        # LU is reserved for deliberately tiny numerical-reference cases.
        trace = bempp.linalg.lu(lhs, rhs)
        iterations = 0
    else:
        trace, info, iterations = bempp.linalg.gmres(lhs, rhs, tol=tolerance,
            maxiter=max_iterations, use_strong_form=True, return_iteration_count=True)
        if info != 0:
            raise RuntimeError(f"combined-field GMRES failed at {frequency_hz:g} Hz: info={info}, iterations={iterations}")
    return trace, iterations


def _single_layer_solve(grid: bempp.Grid, neumann_value: complex, frequency_hz: float,
                        medium: AcousticMedium, tolerance: float, max_iterations: int,
                        operator_assembler: str = "dense") -> tuple[Any, Any, int]:
    """Fast preview equation; susceptible to fictitious interior resonances."""
    k = 2 * math.pi * frequency_hz / medium.sound_speed_m_s
    space = bempp.function_space(grid, "P", 1)
    identity = bempp.operators.boundary.sparse.identity(space, space, space)
    adjoint = bempp.operators.boundary.helmholtz.adjoint_double_layer(
        space, space, space, k, assembler=operator_assembler)

    @bempp.complex_callable
    def prescribed(_x, _n, domain_index, result):
        result[0] = neumann_value if domain_index == 1 else 0.0

    rhs = bempp.GridFunction(space, fun=prescribed)
    density, info, iterations = bempp.linalg.gmres(
        -0.5 * identity + adjoint, rhs, tol=tolerance, maxiter=max_iterations,
        use_strong_form=True, return_iteration_count=True)
    if info != 0:
        raise RuntimeError(
            f"single-layer GMRES failed at {frequency_hz:g} Hz: info={info}, iterations={iterations}")
    return space, density, iterations


def ideal_aperture_pressure(observer: ApertureObserver, normal_velocity: np.ndarray,
                            directions: np.ndarray, frequency_hz: float,
                            medium: AcousticMedium, origin_m: np.ndarray) -> np.ndarray:
    """Infinite-baffle Rayleigh integral, retaining calibrated complex pressure."""
    k = 2 * math.pi * frequency_hz / medium.sound_speed_m_s
    phase = np.exp(-1j * k * (directions.T @ (observer.positions_m - origin_m).T))
    direct = np.maximum(0.0, directions.T @ observer.normals.T)
    return 1j * medium.density_kg_m3 * 2 * math.pi * frequency_hz / (2 * math.pi) * (
        phase * direct @ (normal_velocity * observer.area_weights_m2))


def _beamwidth(angles: np.ndarray, pressure: np.ndarray) -> float:
    level = 20 * np.log10(np.maximum(np.abs(pressure) / max(abs(pressure[0]), 1e-30), 1e-15))
    indices = np.flatnonzero(level <= -6)
    if not len(indices):
        return 180.0
    i = int(indices[0])
    if i == 0:
        return 0.0
    crossing = np.interp(-6.0, level[i-1:i+1][::-1], angles[i-1:i+1][::-1])
    return 2 * float(crossing)


def aperture_metrics(observer: ApertureObserver, pressure: np.ndarray, velocity: np.ndarray) -> dict[str, float]:
    weights = observer.area_weights_m2 / observer.area_weights_m2.sum()
    magnitude = np.abs(pressure)
    phase = np.unwrap(np.angle(pressure))
    mean_mag = float(np.sum(weights * magnitude))
    active = float(np.sum(observer.area_weights_m2[magnitude >= 0.5 * max(float(magnitude.max()), 1e-30)]))
    power = 0.5 * float(np.sum(observer.area_weights_m2 * np.real(pressure * np.conj(velocity))))
    return {"mouth_magnitude_cv": float(np.sqrt(np.sum(weights * (magnitude - mean_mag) ** 2)) / max(mean_mag, 1e-30)),
            "mouth_phase_spread_deg": float(np.degrees(phase.max() - phase.min())),
            "mouth_active_area_m2": active, "mouth_active_area_fraction": active / float(observer.area_weights_m2.sum()),
            "mouth_acoustic_power_w": power,
            "mouth_modal_asymmetry": float(abs(np.sum(weights * pressure * np.sign(observer.projected_xy_m[:, 0]))) /
                                             max(abs(np.sum(weights * pressure)), 1e-30))}


def solve_frequency(grid: bempp.Grid, frequency_hz: float, angles_deg: np.ndarray,
                    sound_speed_m_s: float, gmres_tolerance: float,
                    gmres_max_iterations: int, *, acoustic_mesh: AcousticMesh | None = None,
                    observer: ApertureObserver | None = None,
                    medium: AcousticMedium | None = None,
                    source: SourceDefinition | None = None,
                    formulation: str = "combined-field",
                    solver_backend: str = "bempp-dense",
                    operator_assembler: str = "dense",
                    direct_solve_max_dofs: int = 0,
                    fmm_min_order: int = 6, fmm_order_factor: float = 0.8,
                    fmm_separation: float = 1.5,
                    fmm_max_direct: int = 100) -> tuple[dict[str, np.ndarray], int, float] | FrequencyResult:
    """Solve one frequency. Legacy calls receive normalized dB cuts."""
    medium = medium or AcousticMedium(sound_speed_m_s= sound_speed_m_s)
    source = source or SourceDefinition()
    if solver_backend == "ngsolve-fmm":
        if acoustic_mesh is None:
            raise ValueError("ngsolve-fmm requires the labeled AcousticMesh")
        return _solve_frequency_ngsolve(acoustic_mesh, observer, frequency_hz,
            angles_deg, medium, source, gmres_tolerance, gmres_max_iterations,
            fmm_min_order, fmm_order_factor, fmm_separation, fmm_max_direct)
    if solver_backend != "bempp-dense":
        raise ValueError("solver_backend must be 'bempp-dense' or 'ngsolve-fmm'")
    if acoustic_mesh is None:
        # Legacy unit Neumann loading, now using the resonance-safe formulation.
        space, trace, g, iterations = _combined_field_solve(grid, 1 + 0j, frequency_hz, medium,
            gmres_tolerance, gmres_max_iterations, operator_assembler, direct_solve_max_dofs)
        cuts = {}
        k = 2 * math.pi * frequency_hz / medium.sound_speed_m_s
        for name, azimuth in CUT_AZIMUTHS.items():
            directions = receiver_directions(angles_deg, azimuth)
            far_d = bempp.operators.far_field.helmholtz.double_layer(space, directions, k).evaluate(trace)
            far_s = bempp.operators.far_field.helmholtz.single_layer(space, directions, k).evaluate(g)
            pressure = np.asarray(far_d - far_s).reshape(-1)
            cuts[name] = 20 * np.log10(np.maximum(np.abs(pressure) / max(abs(pressure[0]), 1e-15), 1e-15))
        return cuts, iterations, float(space.global_dof_count)
    observer = observer or make_aperture_observer(acoustic_mesh)
    velocity, neumann = piston_boundary_values(acoustic_mesh, source, frequency_hz, medium)
    k = 2 * math.pi * frequency_hz / medium.sound_speed_m_s
    if formulation == "single-layer-preview":
        space, density, iterations = _single_layer_solve(
            grid, neumann, frequency_hz, medium, gmres_tolerance,
            gmres_max_iterations, operator_assembler)

        def evaluate(points: np.ndarray) -> np.ndarray:
            return np.asarray(bempp.operators.potential.helmholtz.single_layer(
                space, points, k).evaluate(density)).reshape(-1)
    elif formulation == "combined-field":
        space, trace, g, iterations = _combined_field_solve(
            grid, neumann, frequency_hz, medium, gmres_tolerance,
            gmres_max_iterations, operator_assembler, direct_solve_max_dofs)

        def evaluate(points: np.ndarray) -> np.ndarray:
            return np.asarray((bempp.operators.potential.helmholtz.double_layer(
                space, points, k).evaluate(trace) -
                bempp.operators.potential.helmholtz.single_layer(
                    space, points, k).evaluate(g))).reshape(-1)
    else:
        raise ValueError("formulation must be 'single-layer-preview' or 'combined-field'")
    points = observer.positions_m.T
    p = evaluate(points)
    # Euler's equation, evaluated by a stable one-sided normal pressure difference.
    epsilon = max(1e-5, observer.offset_m * 0.1)
    points2 = (observer.positions_m + epsilon * observer.normals).T
    p2 = evaluate(points2)
    vn = -(p2 - p) / epsilon / (1j * 2 * math.pi * frequency_hz * medium.density_kg_m3)
    full, ideal = {}, {}
    for name, azimuth in CUT_AZIMUTHS.items():
        directions = receiver_directions(angles_deg, azimuth)
        if formulation == "single-layer-preview":
            far = bempp.operators.far_field.helmholtz.single_layer(
                space, directions, k).evaluate(density)
        else:
            far = (bempp.operators.far_field.helmholtz.double_layer(
                space, directions, k).evaluate(trace) -
                bempp.operators.far_field.helmholtz.single_layer(
                    space, directions, k).evaluate(g))
        full[name] = np.asarray(far).reshape(-1) * np.exp(1j * k * (directions.T @ acoustic_mesh.mouth_center_m))
        ideal[name] = ideal_aperture_pressure(observer, vn, directions, frequency_hz, medium,
                                               acoustic_mesh.mouth_center_m)
    metrics = aperture_metrics(observer, p, vn)
    metrics.update({f"{name}_beamwidth_deg": _beamwidth(angles_deg, full[name]) for name in CUT_AZIMUTHS})
    diffs = np.concatenate([full[n] / max(abs(full[n][0]), 1e-30) - ideal[n] / max(abs(ideal[n][0]), 1e-30)
                            for n in CUT_AZIMUTHS])
    metrics["diffraction_penalty_rms"] = float(np.sqrt(np.mean(np.abs(diffs) ** 2)))
    metrics["source_velocity_m_s"] = float(abs(velocity))
    return FrequencyResult(frequency_hz, iterations, int(space.global_dof_count), p, vn, full, ideal, metrics)


def _solve_frequency_ngsolve(acoustic_mesh: AcousticMesh,
                             observer: ApertureObserver | None,
                             frequency_hz: float, angles_deg: np.ndarray,
                             medium: AcousticMedium, source: SourceDefinition,
                             tolerance: float, max_iterations: int,
                             fmm_min_order: int, fmm_order_factor: float,
                             fmm_separation: float,
                             fmm_max_direct: int) -> FrequencyResult:
    """Run the same throat-driven problem with native matrix-free operators."""
    try:
        from .ngsolve_bem_backend import make_point_evaluator, solve_neumann
    except ImportError:
        from ngsolve_bem_backend import make_point_evaluator, solve_neumann

    observer = observer or make_aperture_observer(acoustic_mesh)
    velocity, neumann = piston_boundary_values(acoustic_mesh, source, frequency_hz, medium)
    solution = solve_neumann(acoustic_mesh.surface.vertices, acoustic_mesh.surface.faces,
                             acoustic_mesh.domain_indices, neumann, frequency_hz,
                             medium.sound_speed_m_s, tolerance, max_iterations,
                             fmm_min_order=fmm_min_order,
                             fmm_order_factor=fmm_order_factor,
                             fmm_separation=fmm_separation,
                             fmm_max_direct=fmm_max_direct,
                             symmetry_planes=acoustic_mesh.symmetry_planes)
    k = solution.wavenumber_m1
    epsilon = max(1e-5, observer.offset_m * 0.1)
    second_mouth = observer.positions_m + epsilon * observer.normals
    # Evaluate sufficiently far away to recover the 1/r far-field coefficient.
    diameter = max(float(np.ptp(acoustic_mesh.surface.vertices, axis=0).max()), 1e-3)
    far_radius = 100.0 * max(diameter, 2 * math.pi / k)
    far_points: dict[str, np.ndarray] = {}
    directions_by_cut: dict[str, np.ndarray] = {}
    for name, azimuth in CUT_AZIMUTHS.items():
        directions = receiver_directions(angles_deg, azimuth)
        directions_by_cut[name] = directions
        far_points[name] = acoustic_mesh.mouth_center_m + far_radius * directions.T
    all_points = np.vstack((observer.positions_m, second_mouth, *far_points.values()))
    evaluation_started = time.perf_counter()
    evaluate = make_point_evaluator(solution, all_points)
    values = evaluate(all_points)
    evaluation_s = time.perf_counter() - evaluation_started
    print(f"BEM {frequency_hz:g} Hz: batched field evaluation "
          f"{evaluation_s:.2f}s for {len(all_points)} points", flush=True)
    count = len(observer.positions_m)
    p = values[:count]
    p2 = values[count:2 * count]
    vn = -(p2 - p) / epsilon / (1j * 2 * math.pi * frequency_hz * medium.density_kg_m3)
    full, ideal = {}, {}
    cursor = 2 * count
    for name in CUT_AZIMUTHS:
        directions = directions_by_cut[name]
        cut_count = directions.shape[1]
        radial_pressure = values[cursor:cursor + cut_count]
        cursor += cut_count
        full[name] = radial_pressure * far_radius * np.exp(-1j * k * far_radius)
        ideal[name] = ideal_aperture_pressure(observer, vn, directions, frequency_hz,
                                               medium, acoustic_mesh.mouth_center_m)
    metrics = aperture_metrics(observer, p, vn)
    metrics.update({f"{name}_beamwidth_deg": _beamwidth(angles_deg, full[name])
                    for name in CUT_AZIMUTHS})
    differences = np.concatenate([
        full[name] / max(abs(full[name][0]), 1e-30)
        - ideal[name] / max(abs(ideal[name][0]), 1e-30)
        for name in CUT_AZIMUTHS])
    metrics["diffraction_penalty_rms"] = float(np.sqrt(np.mean(np.abs(differences) ** 2)))
    metrics["source_velocity_m_s"] = float(abs(velocity))
    metrics["far_field_evaluation_radius_m"] = far_radius
    metrics["solver_relative_residual"] = solution.relative_residual
    metrics["field_evaluation_s"] = evaluation_s
    metrics["solver_peak_rss_gib"] = solution.peak_rss_gib
    metrics.update({f"solver_{name}_s": value
                    for name, value in solution.timings_s.items()})
    return FrequencyResult(frequency_hz, solution.iterations, solution.dofs, p, vn,
                           full, ideal, metrics)


def _atomic_npz(path: Path, **arrays: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".npz", dir=path.parent)
    os.close(fd)
    try:
        np.savez_compressed(temporary, **arrays)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_jsonable(value), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_frequency(path: Path, result: FrequencyResult) -> None:
    arrays: dict[str, Any] = {"frequency_hz": result.frequency_hz,
        "gmres_iterations": result.gmres_iterations, "dofs": result.dofs,
        "mouth_pressure": result.mouth_pressure, "mouth_normal_velocity": result.mouth_normal_velocity,
        "metrics_json": json.dumps(result.metrics, sort_keys=True)}
    for mode, cuts in (("full", result.full_exterior_pressure), ("ideal", result.ideal_aperture_pressure)):
        arrays.update({f"{mode}_{name}": values for name, values in cuts.items()})
    arrays.update({f"difference_{name}": result.full_exterior_pressure[name] - result.ideal_aperture_pressure[name]
                   for name in CUT_AZIMUTHS})
    _atomic_npz(path, **arrays)


def _load_frequency(path: Path) -> FrequencyResult:
    with np.load(path, allow_pickle=False) as data:
        full = {n: data[f"full_{n}"].copy() for n in CUT_AZIMUTHS}
        ideal = {n: data[f"ideal_{n}"].copy() for n in CUT_AZIMUTHS}
        return FrequencyResult(float(data["frequency_hz"]), int(data["gmres_iterations"]), int(data["dofs"]),
            data["mouth_pressure"].copy(), data["mouth_normal_velocity"].copy(), full, ideal,
            json.loads(str(data["metrics_json"])))


def _solve_frequency_worker(payload: tuple[AcousticMesh, ApertureObserver, PipelineSettings,
                                           float, Path, int]) -> str:
    """Isolated frequency worker; Bempp/Numba state is process-local."""
    mesh, observer, settings, frequency, artifact, threads = payload
    import numba
    numba.set_num_threads(threads)
    if settings.solver_backend == "ngsolve-fmm":
        from ngsolve import SetNumThreads
        SetNumThreads(threads)
    grid = (bempp.Grid(mesh.surface.vertices.T, mesh.surface.faces.T,
                       domain_indices=mesh.domain_indices)
            if settings.solver_backend == "bempp-dense" else None)
    result = solve_frequency(grid, frequency, np.asarray(settings.angles_deg),
        settings.medium.sound_speed_m_s, settings.gmres_tolerance, settings.gmres_max_iterations,
        acoustic_mesh=mesh, observer=observer, medium=settings.medium, source=settings.source,
        formulation=settings.formulation,
        solver_backend=settings.solver_backend,
        operator_assembler=settings.operator_assembler,
        direct_solve_max_dofs=settings.direct_solve_max_dofs,
        fmm_min_order=settings.fmm_min_order,
        fmm_order_factor=settings.fmm_order_factor,
        fmm_separation=settings.fmm_separation,
        fmm_max_direct=settings.fmm_max_direct)
    assert isinstance(result, FrequencyResult)
    _save_frequency(artifact, result)
    return str(artifact)


def run_pipeline(yaml_path: Path, settings: PipelineSettings, output_dir: Path = DEFAULT_OUTPUT_DIR,
                 resume: bool = True) -> dict[str, Any]:
    """Callable staged API. Results contain arrays and artifact paths, never only plots."""
    started = time.monotonic()
    frequencies = np.asarray(settings.frequencies_hz, dtype=float)
    if len(frequencies) == 0 or np.any(frequencies <= 0):
        raise ValueError("at least one positive frequency is required")
    if abs(float(frequencies.max()) - settings.mesh.maximum_frequency_hz) > 1e-9:
        raise ValueError("mesh maximum_frequency_hz must equal the sweep's highest frequency")
    if settings.quadrant_symmetry and settings.solver_backend != "ngsolve-fmm":
        raise ValueError("quadrant symmetry currently requires ngsolve-fmm; "
                         "use full geometry for the dense reference backend")
    mesh_builder = (build_quadrant_acoustic_mesh
                    if settings.quadrant_symmetry else build_acoustic_mesh)
    mesh = mesh_builder(yaml_path, settings.mesh,
                        settings.geometry_side_samples,
                        settings.geometry_axial_stations)
    if (settings.solver_backend == "bempp-dense" and settings.memory_limit_gib is not None
            and mesh.report.estimated_dense_matrix_gib > settings.memory_limit_gib):
        raise ValueError(f"estimated solve cost {mesh.report.estimated_dense_matrix_gib:.3g} GiB exceeds memory limit")
    observer = make_aperture_observer(mesh, settings.observer_offset_m)
    config_hash = hashlib.sha256(yaml_path.read_bytes() + json.dumps(_jsonable(asdict(settings)), sort_keys=True).encode()).hexdigest()
    run_dir = output_dir / f"{yaml_path.stem}-BEM-{config_hash[:12]}"
    frequency_dir = run_dir / "frequencies"
    frequency_dir.mkdir(parents=True, exist_ok=True)
    _atomic_npz(run_dir / "mesh.npz", vertices=mesh.surface.vertices, faces=mesh.surface.faces,
                domain_indices=mesh.domain_indices, mouth_ring_m=mesh.mouth_ring_m,
                mouth_center_m=mesh.mouth_center_m,
                symmetry_factor=mesh.symmetry_factor,
                symmetry_planes=np.asarray(mesh.symmetry_planes))
    _atomic_npz(run_dir / "mouth_observer.npz", positions_m=observer.positions_m,
                normals=observer.normals, area_weights_m2=observer.area_weights_m2,
                projected_xy_m=observer.projected_xy_m)
    artifacts = [frequency_dir / f"{frequency:.9f}.npz" for frequency in frequencies]
    pending = [(float(frequency), artifact) for frequency, artifact in zip(frequencies, artifacts)
               if not (resume and artifact.exists())]
    plan = execution_plan(settings, mesh, len(pending))
    print(f"BEM execution plan: {plan.workers} frequency workers x "
          f"{plan.threads_per_worker} native threads; "
          f"{plan.estimated_memory_per_worker_gib:.2f} GiB/worker estimated; "
          f"{len(pending)} frequencies pending", flush=True)
    used_parallel_workers = plan.workers
    if plan.workers > 1:
        try:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=plan.workers, mp_context=context) as executor:
                # Start the highest frequencies first: they expose convergence
                # and memory failures early, while lower frequencies backfill
                # workers through the executor's dynamic queue.
                futures = [executor.submit(_solve_frequency_worker,
                           (mesh, observer, settings, frequency, artifact, plan.threads_per_worker))
                           for frequency, artifact in sorted(pending, reverse=True)]
                for future in as_completed(futures):
                    future.result()
        except (PermissionError, NotImplementedError):
            # Restricted macOS sandboxes may deny POSIX semaphore discovery.
            # Preserve correctness and use all cores within one Numba process.
            used_parallel_workers = 1
            print("WARNING: multiprocessing unavailable; falling back to one "
                  "frequency process using all native threads", file=sys.stderr,
                  flush=True)
    if pending and (plan.workers == 1 or used_parallel_workers == 1):
        import numba
        numba.set_num_threads(plan.threads_per_worker)
        if settings.solver_backend == "ngsolve-fmm":
            from ngsolve import SetNumThreads
            SetNumThreads(plan.threads_per_worker)
        grid = (bempp.Grid(mesh.surface.vertices.T, mesh.surface.faces.T,
                           domain_indices=mesh.domain_indices)
                if settings.solver_backend == "bempp-dense" else None)
        for frequency, artifact in pending:
            result = solve_frequency(grid, frequency, np.asarray(settings.angles_deg),
                settings.medium.sound_speed_m_s, settings.gmres_tolerance, settings.gmres_max_iterations,
                acoustic_mesh=mesh, observer=observer, medium=settings.medium, source=settings.source,
                formulation=settings.formulation,
                solver_backend=settings.solver_backend,
                operator_assembler=settings.operator_assembler,
                direct_solve_max_dofs=settings.direct_solve_max_dofs,
                fmm_min_order=settings.fmm_min_order,
                fmm_order_factor=settings.fmm_order_factor,
                fmm_separation=settings.fmm_separation,
                fmm_max_direct=settings.fmm_max_direct)
            assert isinstance(result, FrequencyResult)
            _save_frequency(artifact, result)
    results: list[FrequencyResult] = []
    for frequency, artifact in zip(frequencies, artifacts):
        results.append(_load_frequency(artifact))
    manifest = {"schema_version": 1, "status": "complete", "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_yaml": str(yaml_path.resolve()), "configuration_hash": config_hash,
        "normalized_settings": _jsonable(asdict(settings)), "coordinate_references": {
            "geometry_origin_m": [0, 0, 0], "radiation_origin_m": mesh.mouth_center_m.tolist()},
        "source": {**_jsonable(asdict(settings.source)), "area_m2": mesh.source_area_m2,
            "uniform_velocity_m_s": _jsonable(settings.source.volume_velocity_m3_s / mesh.source_area_m2),
            "boundary_condition": "dp/dn=-i*omega*rho*v_n", "driven_domain": 1, "rigid_domain": 0},
        "observer": {"kind": "conformal_mouth_aperture", "offset_m": observer.offset_m,
            "samples": len(observer.positions_m), "alters_boundary": False},
        "mesh_hash": mesh.content_hash, "mesh_report": asdict(mesh.report),
        "solver": {"formulation": settings.formulation,
            "backend": settings.solver_backend,
            "library": "ngsolve" if settings.solver_backend == "ngsolve-fmm" else "bempp-cl",
            "tolerance": settings.gmres_tolerance, "max_iterations": settings.gmres_max_iterations},
        "execution": {**asdict(plan), "workers_used": used_parallel_workers},
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "trimesh": trimesh.__version__},
        "convergence": {"all_solved": True, "mesh_convergence_checked": False},
        "runtime_seconds": time.monotonic() - started,
        "artifact_hashes": {"mesh.npz": _sha256_file(run_dir / "mesh.npz"),
            "mouth_observer.npz": _sha256_file(run_dir / "mouth_observer.npz"),
            **{str((frequency_dir / f"{f:.9f}.npz").relative_to(run_dir)):
               _sha256_file(frequency_dir / f"{f:.9f}.npz") for f in frequencies}},
        "frequency_artifacts": [str((frequency_dir / f"{f:.9f}.npz").relative_to(run_dir)) for f in frequencies]}
    manifest_path = run_dir / "manifest.json"
    _atomic_json(manifest_path, manifest)
    write_summary_csv(run_dir / "metrics.csv", results)
    angles = np.asarray(settings.angles_deg)
    for mode, attribute in (("full-exterior", "full_exterior_pressure"),
                            ("ideal-aperture", "ideal_aperture_pressure")):
        cuts = {name: np.column_stack([getattr(result, attribute)[name] for result in results])
                for name in CUT_AZIMUTHS}
        db = {name: _normalized_db(values) for name, values in cuts.items()}
        plot_cuts(run_dir / f"{mode}-cuts.png", angles, frequencies, db, -40.0)
        plot_heatmaps(run_dir / f"{mode}-heatmap.png", angles, frequencies, db, -40.0)
        for name in CUT_AZIMUTHS:
            write_cut_csv(run_dir / f"{mode}-{name}.csv", angles, frequencies, db[name])
    for result in results:
        plot_mouth_fields(run_dir / f"mouth-{result.frequency_hz:.9f}.png", observer,
                          result.mouth_pressure, result.mouth_normal_velocity, result.frequency_hz)
    return {"mesh": mesh, "observer": observer, "frequencies": results,
            "manifest": manifest, "manifest_path": manifest_path, "run_dir": run_dir}


def convergence_metrics(coarse: list[FrequencyResult], fine: list[FrequencyResult],
                        angles_deg: np.ndarray) -> dict[str, float]:
    """Compare complex fields and robust lobe measures between two mesh tiers."""
    if [r.frequency_hz for r in coarse] != [r.frequency_hz for r in fine]:
        raise ValueError("convergence results must share the same frequency grid")
    relative_errors, beam_errors, phase_errors = [], [], []
    for left, right in zip(coarse, fine):
        for name in CUT_AZIMUTHS:
            a, b = left.full_exterior_pressure[name], right.full_exterior_pressure[name]
            scale = max(float(np.linalg.norm(b)), 1e-30)
            relative_errors.append(float(np.linalg.norm(a - b) / scale))
            beam_errors.append(abs(_beamwidth(angles_deg, a) - _beamwidth(angles_deg, b)))
        phase_errors.append(abs(left.metrics["mouth_phase_spread_deg"] - right.metrics["mouth_phase_spread_deg"]))
    worst = max(relative_errors, default=math.inf)
    return {"maximum_complex_pressure_relative_error": worst,
            "maximum_beamwidth_change_deg": max(beam_errors, default=math.inf),
            "maximum_mouth_phase_spread_change_deg": max(phase_errors, default=math.inf),
            "convergence_confidence": float(max(0.0, 1.0 - worst))}


def candidate_is_acceptable(result: dict[str, Any], *, require_mesh_convergence: bool = True) -> bool:
    """Hard gate used by candidate/optimizer runners."""
    manifest = result.get("manifest", {})
    mesh_report = manifest.get("mesh_report", {})
    convergence = manifest.get("convergence", {})
    return bool(manifest.get("status") == "complete" and not mesh_report.get("quality_failures") and
                convergence.get("all_solved") and
                (not require_mesh_convergence or convergence.get("mesh_convergence_checked")))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_summary_csv(path: Path, results: Iterable[FrequencyResult]) -> None:
    results = list(results)
    keys = sorted({key for result in results for key in result.metrics})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frequency_hz", "gmres_iterations", "dofs", *keys])
        writer.writeheader()
        for result in results:
            writer.writerow({"frequency_hz": result.frequency_hz, "gmres_iterations": result.gmres_iterations,
                             "dofs": result.dofs, **result.metrics})


def write_cut_csv(path: Path, angles_deg: np.ndarray, frequencies_hz: np.ndarray, values: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("angle_deg", *[float(v) for v in frequencies_hz]))
        writer.writerows((float(a), *[float(v) for v in row]) for a, row in zip(angles_deg, values))


def _normalized_db(pressure: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(np.abs(pressure) / np.maximum(np.abs(pressure[0:1]), 1e-30), 1e-15))


def plot_mouth_fields(path: Path, observer: ApertureObserver, pressure: np.ndarray,
                      velocity: np.ndarray, frequency_hz: float) -> None:
    """Planar mouth-view projection; the plotted plane is not a boundary."""
    impedance = pressure / np.where(np.abs(velocity) > 1e-30, velocity, np.nan + 0j)
    fields = ((np.abs(pressure), "|p| (Pa)"), (np.degrees(np.angle(pressure)), "phase(p) (deg)"),
              (np.abs(velocity), "|vₙ| (m/s)"), (np.degrees(np.angle(velocity)), "phase(vₙ) (deg)"),
              (np.real(impedance), "Re(p/vₙ) (Pa·s/m)"))
    figure, axes = plt.subplots(1, 5, figsize=(19, 4), constrained_layout=True)
    xy = observer.projected_xy_m * 1e3
    sizes = 30 + 400 * observer.area_weights_m2 / max(float(observer.area_weights_m2.max()), 1e-30)
    for axis, (values, label) in zip(axes, fields):
        image = axis.scatter(xy[:, 0], xy[:, 1], c=values, s=sizes, cmap="viridis")
        axis.set_aspect("equal"); axis.set_xlabel("x (mm)"); axis.set_title(label)
        figure.colorbar(image, ax=axis, shrink=.8)
    axes[0].set_ylabel("y (mm)")
    figure.suptitle(f"Conformal mouth fields — {frequency_hz:g} Hz")
    figure.savefig(path, dpi=160); plt.close(figure)


def plot_cuts(path: Path, angles_deg: np.ndarray, frequencies_hz: np.ndarray,
              cuts: dict[str, np.ndarray], floor_db: float) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(17, 5.8), sharey=True, constrained_layout=True)
    colors = plt.cm.viridis(np.linspace(0, 1, len(frequencies_hz)))
    for axis, name in zip(axes, CUT_AZIMUTHS):
        for i, frequency in enumerate(frequencies_hz):
            axis.plot(angles_deg, np.maximum(cuts[name][:, i], floor_db), color=colors[i], label=f"{frequency:g} Hz")
        axis.axhline(-6, color="black", alpha=.3, linestyle="--"); axis.grid(True, alpha=.25)
        axis.set(xlim=(0, 90), ylim=(floor_db, 3), xlabel="Off-axis angle (degrees)", title=f"{name.capitalize()} plane")
    axes[0].set_ylabel("Level relative to on-axis (dB)"); axes[-1].legend(fontsize=8)
    figure.savefig(path, dpi=180); plt.close(figure)


def plot_heatmaps(path: Path, angles_deg: np.ndarray, frequencies_hz: np.ndarray,
                  cuts: dict[str, np.ndarray], floor_db: float) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(17, 6), sharey=True, constrained_layout=True)
    image = None
    for axis, name in zip(axes, CUT_AZIMUTHS):
        image = axis.pcolormesh(frequencies_hz, angles_deg, np.maximum(cuts[name], floor_db), shading="nearest", cmap="turbo", vmin=floor_db, vmax=0)
        if (len(frequencies_hz) >= 2 and len(angles_deg) >= 2
                and float(np.nanmin(cuts[name])) <= -6 <= float(np.nanmax(cuts[name]))):
            contour = axis.contour(frequencies_hz, angles_deg, cuts[name], levels=[-6], colors="black")
            axis.clabel(contour, fmt={-6: "−6 dB"})
        axis.set_xscale("log"); axis.set_title(f"{name.capitalize()} plane")
    axes[0].set_ylabel("Off-axis angle (degrees)"); figure.colorbar(image, ax=axes, label="Level relative to on-axis (dB)")
    figure.savefig(path, dpi=180); plt.close(figure)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path); parser.add_argument("--start-hz", type=float, default=500)
    parser.add_argument("--stop-hz", type=float, default=8_000); parser.add_argument("--frequencies", type=int, default=10)
    parser.add_argument("--angles", type=int, default=91); parser.add_argument("--floor-db", type=float, default=-40)
    parser.add_argument("--mesh-tier", choices=MESH_TIERS, default="production")
    parser.add_argument("--elements-per-wavelength", type=float); parser.add_argument("--maximum-frequency-hz", type=float)
    parser.add_argument("--surface-mesher", choices=("netgen", "subdivide"), default="netgen")
    parser.add_argument("--netgen-maxh-factor", type=float, default=0.5)
    parser.add_argument("--sound-speed", type=float, default=343.21); parser.add_argument("--density", type=float, default=1.2041)
    parser.add_argument("--gmres-tolerance", type=float, default=1e-4); parser.add_argument("--gmres-max-iterations", type=int, default=300)
    parser.add_argument("--formulation", choices=("single-layer-preview", "combined-field"),
                        default="combined-field")
    parser.add_argument("--solver-backend", choices=("bempp-dense", "ngsolve-fmm"),
                        default="ngsolve-fmm")
    parser.add_argument("--operator-assembler", choices=("dense", "fmm"), default="dense")
    parser.add_argument("--direct-solve-max-dofs", type=int, default=0,
                        help="use cubic LU at or below this DOF count; 0 always uses GMRES")
    parser.add_argument("--observer-offset-mm", type=float, default=1); parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--maximum-workers", type=int, default=0,
                        help="concurrent frequencies; 0 selects a CPU/memory-safe value")
    parser.add_argument("--memory-limit-gib", type=float)
    parser.add_argument("--geometry-side-samples", type=int,
                        help="optional geometry seed; wavelength refinement still applies")
    parser.add_argument("--geometry-axial-stations", type=int,
                        help="optional geometry seed; wavelength refinement still applies")
    parser.add_argument("--fmm-min-order", type=int, default=6)
    parser.add_argument("--fmm-order-factor", type=float, default=0.8)
    parser.add_argument("--fmm-separation", type=float, default=1.5)
    parser.add_argument("--fmm-max-direct", type=int, default=100)
    parser.add_argument("--full-geometry", action="store_true",
                        help="disable default x/y quadrant symmetry for a reference solve")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.frequencies == 1:
        frequencies = np.asarray([args.stop_hz], dtype=float)
    else:
        frequencies = frequency_grid(args.start_hz, args.stop_hz, args.frequencies, "log")
    maximum = args.maximum_frequency_hz or float(frequencies.max())
    if abs(maximum - float(frequencies.max())) > 1e-9:
        raise SystemExit("--maximum-frequency-hz must equal the highest requested frequency")
    epw = args.elements_per_wavelength or MESH_TIERS[args.mesh_tier]
    settings = PipelineSettings(tuple(frequencies), tuple(np.linspace(0, 90, args.angles)),
        MeshSettings(maximum, epw, surface_mesher=args.surface_mesher,
                     netgen_maxh_factor=args.netgen_maxh_factor),
        observer_offset_m=args.observer_offset_mm * 1e-3,
        gmres_tolerance=args.gmres_tolerance, gmres_max_iterations=args.gmres_max_iterations,
        formulation=args.formulation,
        solver_backend=args.solver_backend,
        operator_assembler=args.operator_assembler,
        direct_solve_max_dofs=args.direct_solve_max_dofs,
        maximum_workers=args.maximum_workers, memory_limit_gib=args.memory_limit_gib,
        geometry_side_samples=args.geometry_side_samples,
        geometry_axial_stations=args.geometry_axial_stations,
        fmm_min_order=args.fmm_min_order,
        fmm_order_factor=args.fmm_order_factor,
        fmm_separation=args.fmm_separation,
        fmm_max_direct=args.fmm_max_direct,
        quadrant_symmetry=not args.full_geometry)
    result = run_pipeline(args.yaml, settings, args.output_dir, not args.no_resume)
    print(result["manifest_path"])


if __name__ == "__main__":
    main()
