"""Reduced HornCAD acoustic domain for interior-aperture solvers.

The closed computational surface consists only of the internal rigid horn wall,
the driven throat disk, and the mouth coupling aperture.  The throat and mouth
closures share their perimeter vertices with the wall; they are boundary
interfaces, not printable geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

try:
    from . import export_horncad as geometry
except ImportError:
    import export_horncad as geometry


RIGID_WALL = 0
THROAT_PISTON = 1
MOUTH_APERTURE = 2


@dataclass
class InteriorAcousticDomain:
    surface: trimesh.Trimesh
    face_domains: np.ndarray
    throat_ring_indices: np.ndarray
    mouth_ring_indices: np.ndarray
    throat_center_index: int
    mouth_center_index: int
    throat_area_m2: float
    mouth_area_m2: float

    @property
    def wall_faces(self) -> np.ndarray:
        return self.face_domains == RIGID_WALL

    @property
    def throat_faces(self) -> np.ndarray:
        return self.face_domains == THROAT_PISTON

    @property
    def mouth_faces(self) -> np.ndarray:
        return self.face_domains == MOUTH_APERTURE


def _internal_rings(yaml_path: Path, side_samples: int,
                    axial_stations: int) -> list[list[tuple[float, float, float]]]:
    if side_samples < 8 or axial_stations < 8:
        raise ValueError("acoustic domain requires at least 8 side and axial samples")
    geometry.apply_horncad_yaml(yaml_path)
    geometry.SIDE_SAMPLES = side_samples
    geometry.Z_STATIONS = axial_stations
    hp, vp = geometry.profile("h"), geometry.profile("v")
    length = float(geometry.PARAMS["length"])
    mouth_h, mouth_v = hp(length), vp(length)
    extension = max(0.0, float(geometry.PARAMS["throat_extension"]))
    rings: list[list[tuple[float, float, float]]] = []
    if extension > 0.0:
        count = max(2, round(axial_stations * extension / max(length, 1e-9)) + 1)
        rings.extend(geometry.conical_extension_ring(i / (count - 1)) for i in range(count))
    samples = geometry.adaptive_profile_z_samples(axial_stations, length, hp, vp)
    if extension > 0.0:
        samples = samples[1:]
    rings.extend(geometry.ring_at(z / length, hp(z), vp(z), mouth_h, mouth_v) for z in samples)
    return rings


def build_interior_acoustic_domain(yaml_path: Path, side_samples: int = 32,
                                   axial_stations: int = 32) -> InteriorAcousticDomain:
    """Build a conforming wall/throat/mouth computational closure in metres."""
    rings = _internal_rings(yaml_path, side_samples, axial_stations)
    ring_size = len(rings[0])
    vertices = np.asarray([point for ring in rings for point in ring], dtype=float) * 1e-3
    faces: list[tuple[int, int, int]] = []
    domains: list[int] = []
    for station in range(len(rings) - 1):
        row, next_row = station * ring_size, (station + 1) * ring_size
        for j in range(ring_size):
            k = (j + 1) % ring_size
            faces.extend(((row + j, next_row + j, next_row + k),
                          (row + j, next_row + k, row + k)))
            domains.extend((RIGID_WALL, RIGID_WALL))

    throat_ring = np.arange(ring_size, dtype=np.int64)
    mouth_ring = np.arange((len(rings) - 1) * ring_size,
                           len(rings) * ring_size, dtype=np.int64)
    throat_center = len(vertices)
    mouth_center = throat_center + 1
    vertices = np.vstack((vertices, vertices[throat_ring].mean(axis=0),
                          vertices[mouth_ring].mean(axis=0)))
    for j in range(ring_size):
        k = (j + 1) % ring_size
        faces.append((throat_center, int(throat_ring[k]), int(throat_ring[j])))
        domains.append(THROAT_PISTON)
        faces.append((mouth_center, int(mouth_ring[j]), int(mouth_ring[k])))
        domains.append(MOUTH_APERTURE)

    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)
    trimesh.repair.fix_normals(mesh, multibody=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or len(mesh.split()) != 1:
        raise ValueError("interior acoustic closure is not one watertight oriented component")
    face_domains = np.asarray(domains, dtype=np.uint8)
    throat_area = float(mesh.area_faces[face_domains == THROAT_PISTON].sum())
    mouth_area = float(mesh.area_faces[face_domains == MOUTH_APERTURE].sum())
    return InteriorAcousticDomain(mesh, face_domains, throat_ring, mouth_ring,
                                  throat_center, mouth_center, throat_area, mouth_area)

