"""Reduced HornCAD acoustic domain for interior-aperture solvers.

The closed computational surface consists only of the internal rigid horn wall,
the driven throat disk, and the mouth coupling aperture.  The throat and mouth
closures share their perimeter vertices with the wall; they are boundary
interfaces, not printable geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import tempfile

import numpy as np
import trimesh
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import Delaunay

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


@dataclass(frozen=True)
class VolumeMeshReport:
    nodes: int
    tetrahedra: int
    maximum_tetrahedron_edge_m: float
    boundary_surface_patches: dict[int, list[int]]
    maximum_label_match_error_m: float


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


def _append_cap(vertices: list[np.ndarray], boundary: np.ndarray,
                faces: list[tuple[int, int, int]], domains: list[int],
                domain: int) -> int:
    """Triangulate a cap with graded interior rings and an exact outer boundary."""
    boundary_points = np.asarray([vertices[index] for index in boundary])
    center = boundary_points.mean(axis=0)
    surface_height = LinearNDInterpolator(boundary_points[:, :2], boundary_points[:, 2])
    cap_indices = list(int(index) for index in boundary)
    cap_points = list(boundary_points)
    radial_layers = max(2, math.ceil(len(boundary) / (2.0 * math.pi)))
    for layer in range(1, radial_layers):
        fraction = layer / radial_layers
        sample_count = max(6, round(len(boundary) * fraction))
        parameters = np.arange(sample_count, dtype=float) * len(boundary) / sample_count
        lower = np.floor(parameters).astype(int)
        blend = parameters - lower
        perimeter = ((1.0 - blend[:, None]) * boundary_points[lower]
                     + blend[:, None] * boundary_points[(lower + 1) % len(boundary)])
        interior_xy = center[:2] + fraction * (perimeter[:, :2] - center[:2])
        interior_z = np.asarray(surface_height(interior_xy))
        if np.any(~np.isfinite(interior_z)):
            raise ValueError("cap interpolation left the aperture projection")
        for point in np.column_stack((interior_xy, interior_z)):
            cap_indices.append(len(vertices))
            cap_points.append(point)
            vertices.append(point)
    center_index = len(vertices)
    center[2] = np.asarray(surface_height(center[:2])).item()
    vertices.append(center)
    cap_indices.append(center_index)
    cap_points.append(center)
    for triangle in Delaunay(np.asarray(cap_points)[:, :2]).simplices:
        faces.append(tuple(cap_indices[index] for index in triangle))
        domains.append(domain)
    return center_index


def build_interior_acoustic_domain(yaml_path: Path, side_samples: int = 32,
                                   axial_stations: int = 32) -> InteriorAcousticDomain:
    """Build a conforming wall/throat/mouth computational closure in metres."""
    rings = _internal_rings(yaml_path, side_samples, axial_stations)
    ring_size = len(rings[0])
    vertices = [point for point in
                np.asarray([point for ring in rings for point in ring], dtype=float) * 1e-3]
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
    throat_center = _append_cap(vertices, throat_ring, faces, domains, THROAT_PISTON)
    mouth_center = _append_cap(vertices, mouth_ring, faces, domains, MOUTH_APERTURE)

    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=False)
    trimesh.repair.fix_normals(mesh, multibody=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or len(mesh.split()) != 1:
        raise ValueError("interior acoustic closure is not one watertight oriented component")
    face_domains = np.asarray(domains, dtype=np.uint8)
    throat_area = float(mesh.area_faces[face_domains == THROAT_PISTON].sum())
    mouth_area = float(mesh.area_faces[face_domains == MOUTH_APERTURE].sum())
    return InteriorAcousticDomain(mesh, face_domains, throat_ring, mouth_ring,
                                  throat_center, mouth_center, throat_area, mouth_area)


def write_gmsh_volume_mesh(domain: InteriorAcousticDomain, path: Path,
                           maximum_edge_m: float) -> VolumeMeshReport:
    """Tetrahedralize the closed air volume and preserve its boundary labels.

    Gmsh physical attributes are 1=wall, 2=throat, 3=mouth, and 4=air volume.
    """
    if maximum_edge_m <= 0.0:
        raise ValueError("maximum tetrahedron edge must be positive")
    import gmsh
    from scipy.spatial import cKDTree

    path.parent.mkdir(parents=True, exist_ok=True)
    source_centers = domain.surface.triangles_center
    source_tree = cKDTree(source_centers)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        with tempfile.TemporaryDirectory(prefix="horncad-acoustic-") as temporary:
            stl_path = Path(temporary) / "closure.stl"
            domain.surface.export(stl_path)
            gmsh.merge(str(stl_path))
        gmsh.model.mesh.classifySurfaces(math.radians(35.0), True, False,
                                         math.pi, True)
        gmsh.model.mesh.createGeometry()
        surface_tags = [tag for dim, tag in gmsh.model.getEntities(2)]
        patches: dict[int, list[int]] = {RIGID_WALL: [], THROAT_PISTON: [], MOUTH_APERTURE: []}
        maximum_match_error = 0.0
        for tag in surface_tags:
            element_types, _, element_nodes = gmsh.model.mesh.getElements(2, tag)
            barycenters: list[np.ndarray] = []
            for element_type, nodes in zip(element_types, element_nodes):
                properties = gmsh.model.mesh.getElementProperties(element_type)
                nodes_per_element = properties[3]
                for row in np.asarray(nodes).reshape(-1, nodes_per_element):
                    coordinates = np.asarray([
                        gmsh.model.mesh.getNode(int(node))[0] for node in row])
                    barycenters.append(coordinates.mean(axis=0))
            distances, indices = source_tree.query(np.asarray(barycenters))
            maximum_match_error = max(maximum_match_error, float(np.max(distances)))
            labels = domain.face_domains[indices]
            label = int(np.bincount(labels, minlength=3).argmax())
            patches[label].append(tag)

        surface_loop = gmsh.model.geo.addSurfaceLoop(surface_tags)
        volume = gmsh.model.geo.addVolume([surface_loop])
        gmsh.model.geo.synchronize()
        names = {RIGID_WALL: "wall", THROAT_PISTON: "throat", MOUTH_APERTURE: "mouth"}
        for label, tags in patches.items():
            physical = gmsh.model.addPhysicalGroup(2, tags, label + 1)
            gmsh.model.setPhysicalName(2, physical, names[label])
        physical_volume = gmsh.model.addPhysicalGroup(3, [volume], 4)
        gmsh.model.setPhysicalName(3, physical_volume, "air")
        # Gmsh's characteristic size is not a longest-edge guarantee. Use a
        # conservative conversion, then enforce the public contract below.
        gmsh.option.setNumber("Mesh.MeshSizeMax", maximum_edge_m / 2.5)
        gmsh.option.setNumber("Mesh.MeshSizeMin", maximum_edge_m / 8.0)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(path))

        node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
        coordinates = np.asarray(coordinates).reshape(-1, 3)
        tetrahedron_blocks: list[np.ndarray] = []
        for element_type, _, nodes in zip(*gmsh.model.mesh.getElements(3, volume)):
            properties = gmsh.model.mesh.getElementProperties(element_type)
            if properties[1] != 3 or properties[3] != 4:
                continue
            tetrahedron_blocks.append(np.asarray(nodes, dtype=np.int64).reshape(-1, 4))
        tetrahedron_tags = np.vstack(tetrahedron_blocks)
        tag_to_index = np.full(int(np.max(node_tags)) + 1, -1, dtype=np.int64)
        tag_to_index[np.asarray(node_tags, dtype=np.int64)] = np.arange(len(node_tags))
        tetrahedron_indices = tag_to_index[tetrahedron_tags]
        maximum_actual_edge = 0.0
        edge_pairs = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
        for start in range(0, len(tetrahedron_indices), 250_000):
            points = coordinates[tetrahedron_indices[start:start + 250_000]]
            for first, second in edge_pairs:
                delta = points[:, first] - points[:, second]
                squared = np.einsum("ij,ij->i", delta, delta)
                maximum_actual_edge = max(maximum_actual_edge,
                                          math.sqrt(float(np.max(squared))))
        if maximum_actual_edge > maximum_edge_m + maximum_edge_m * 1e-6:
            raise ValueError(
                f"tetrahedral mesh edge {maximum_actual_edge:.6g} m exceeds "
                f"requested limit {maximum_edge_m:.6g} m")
        return VolumeMeshReport(len(node_tags), len(tetrahedron_tags), maximum_actual_edge,
                                patches, maximum_match_error)
    finally:
        gmsh.finalize()
