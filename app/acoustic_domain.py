"""Reduced HornCAD acoustic domain for interior-aperture solvers.

The closed computational surface consists only of the internal rigid horn wall,
the driven throat disk, and the mouth coupling aperture.  The throat and mouth
closures share their perimeter vertices with the wall; they are boundary
interfaces, not printable geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
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


def _maximum_tetrahedron_edge(vertices: np.ndarray, tetrahedra: np.ndarray) -> float:
    maximum = 0.0
    edge_pairs = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    for start in range(0, len(tetrahedra), 250_000):
        points = vertices[tetrahedra[start:start + 250_000]]
        for first, second in edge_pairs:
            delta = points[:, first] - points[:, second]
            squared = np.einsum("ij,ij->i", delta, delta)
            maximum = max(maximum, math.sqrt(float(np.max(squared))))
    return maximum


def _tetrahedron_boundary(tetrahedra: np.ndarray) -> np.ndarray:
    """Return outward-oriented faces occurring on exactly one tetrahedron."""
    combinations = ((1, 2, 3, 0), (0, 3, 2, 1),
                    (0, 1, 3, 2), (0, 2, 1, 3))
    faces = np.vstack([tetrahedra[:, (a, b, c)] for a, b, c, _ in combinations])
    opposite = np.concatenate([tetrahedra[:, other] for *_, other in combinations])
    keys = np.sort(faces, axis=1)
    _, first, counts = np.unique(keys, axis=0, return_index=True, return_counts=True)
    boundary_index = first[counts == 1]
    return np.column_stack((faces[boundary_index], opposite[boundary_index]))


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


def build_quadrant_acoustic_domain(yaml_path: Path, side_samples: int = 32,
                                   axial_stations: int = 32) -> InteriorAcousticDomain:
    """Build the positive-X/positive-Y symmetry quadrant of the acoustic domain.

    The two Boolean cut faces are assigned to the rigid-wall attribute. For an
    even pressure solution this is the natural zero-normal-gradient symmetry
    condition. Throat and mouth areas are one quarter of the full-domain areas.
    """
    full = build_interior_acoustic_domain(yaml_path, side_samples, axial_stations)
    low, high = full.surface.bounds
    extent = high - low
    # The box starts at both symmetry planes and extends comfortably beyond the
    # positive half of the horn. Manifold supplies a closed, conforming cut.
    box_extents = np.array([2.0 * max(high[0], extent[0]),
                            2.0 * max(high[1], extent[1]),
                            2.0 * extent[2]])
    box_center = np.array([box_extents[0] / 2.0, box_extents[1] / 2.0,
                           0.5 * (low[2] + high[2])])
    box = trimesh.creation.box(
        extents=box_extents,
        transform=trimesh.transformations.translation_matrix(box_center))
    quadrant = trimesh.boolean.intersection([full.surface, box], engine="manifold")
    if quadrant is None or not quadrant.is_watertight or not quadrant.is_winding_consistent:
        raise ValueError("quadrant Boolean did not produce a watertight oriented domain")
    if np.min(quadrant.vertices[:, :2]) < -1e-10:
        raise ValueError("quadrant Boolean crossed a symmetry plane")

    centers = quadrant.triangles_center
    distance_by_label = []
    for label in (RIGID_WALL, THROAT_PISTON, MOUTH_APERTURE):
        patch = trimesh.Trimesh(full.surface.vertices,
                                full.surface.faces[full.face_domains == label],
                                process=False)
        _, distances, _ = trimesh.proximity.closest_point(patch, centers)
        distance_by_label.append(distances)
    face_domains = np.argmin(np.stack(distance_by_label, axis=1), axis=1).astype(np.uint8)
    symmetry = (np.abs(centers[:, 0]) < 1e-10) | (np.abs(centers[:, 1]) < 1e-10)
    face_domains[symmetry] = RIGID_WALL
    areas = quadrant.area_faces
    throat_area = float(areas[face_domains == THROAT_PISTON].sum())
    mouth_area = float(areas[face_domains == MOUTH_APERTURE].sum())
    if not math.isclose(throat_area * 4.0, full.throat_area_m2, rel_tol=0.01):
        raise ValueError("quadrant throat area is not one quarter of the full throat")
    if not math.isclose(mouth_area * 4.0, full.mouth_area_m2, rel_tol=0.01):
        raise ValueError("quadrant mouth area is not one quarter of the full mouth")
    empty = np.array([], dtype=np.int64)
    return InteriorAcousticDomain(quadrant, face_domains, empty, empty, -1, -1,
                                  throat_area, mouth_area)


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


def write_tetwild_volume_mesh(domain: InteriorAcousticDomain, path: Path,
                              maximum_edge_m: float, *, threads: int | None = None,
                              edge_length_ratio: float | None = None) -> VolumeMeshReport:
    """Tetrahedralize with native TetWild and transfer acoustic boundary labels."""
    if maximum_edge_m <= 0.0:
        raise ValueError("maximum tetrahedron edge must be positive")
    import meshio
    import wildmeshing
    from scipy.spatial import cKDTree

    vertices = np.asarray(domain.surface.vertices, dtype=np.float64)
    faces = np.asarray(domain.surface.faces, dtype=np.int32)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    # TetWild's edge_length_r is an ideal length, not a hard maximum. The
    # calibrated safety factor leaves room for its quality optimization; the
    # measured audit below remains authoritative.
    ratio = edge_length_ratio or 0.52 * maximum_edge_m / diagonal
    worker_count = threads or min(20, os.cpu_count() or 1)
    tetrahedralizer = wildmeshing.Tetrahedralizer(
        max_threads=worker_count, edge_length_r=ratio, epsilon=0.0005,
        skip_simplify=True, coarsen=False)
    tetrahedralizer.set_log_level(6)
    tetrahedralizer.set_mesh(vertices, faces)
    tetrahedralizer.tetrahedralize()
    output_vertices, tetrahedra, _ = tetrahedralizer.get_tet_mesh()
    output_vertices = np.asarray(output_vertices, dtype=np.float64)
    tetrahedra = np.asarray(tetrahedra, dtype=np.int64)
    if not len(tetrahedra):
        raise ValueError("TetWild produced no tetrahedra")
    signed_six_volume = np.einsum(
        "ij,ij->i",
        output_vertices[tetrahedra[:, 1]] - output_vertices[tetrahedra[:, 0]],
        np.cross(output_vertices[tetrahedra[:, 2]] - output_vertices[tetrahedra[:, 0]],
                 output_vertices[tetrahedra[:, 3]] - output_vertices[tetrahedra[:, 0]]))
    if np.any(np.abs(signed_six_volume) < 1e-18):
        raise ValueError("TetWild produced a degenerate tetrahedron")

    maximum_actual_edge = _maximum_tetrahedron_edge(output_vertices, tetrahedra)
    if maximum_actual_edge > maximum_edge_m * 1.000001:
        raise ValueError(
            f"TetWild mesh edge {maximum_actual_edge:.6g} m exceeds "
            f"requested limit {maximum_edge_m:.6g} m")

    boundary_with_opposite = _tetrahedron_boundary(tetrahedra)
    boundary = boundary_with_opposite[:, :3].copy()
    boundary_points = output_vertices[boundary]
    opposite_points = output_vertices[boundary_with_opposite[:, 3]]
    normals = np.cross(boundary_points[:, 1] - boundary_points[:, 0],
                       boundary_points[:, 2] - boundary_points[:, 0])
    inward = np.einsum("ij,ij->i", normals,
                       opposite_points - boundary_points.mean(axis=1)) > 0.0
    boundary[inward, 1], boundary[inward, 2] = (boundary[inward, 2].copy(),
                                                boundary[inward, 1].copy())

    boundary_centers = output_vertices[boundary].mean(axis=1)
    distance_by_label = []
    for label in (RIGID_WALL, THROAT_PISTON, MOUTH_APERTURE):
        patch = trimesh.Trimesh(domain.surface.vertices,
                                domain.surface.faces[domain.face_domains == label],
                                process=False)
        _, distances, _ = trimesh.proximity.closest_point(patch, boundary_centers)
        distance_by_label.append(distances)
    distance_by_label = np.stack(distance_by_label, axis=1)
    labels = np.argmin(distance_by_label, axis=1).astype(np.uint8)
    geometric_error = np.min(distance_by_label, axis=1)
    if set(np.unique(labels)) != {RIGID_WALL, THROAT_PISTON, MOUTH_APERTURE}:
        raise ValueError("TetWild boundary label transfer lost an acoustic patch")
    boundary_geometry = output_vertices[boundary]
    boundary_areas = 0.5 * np.linalg.norm(
        np.cross(boundary_geometry[:, 1] - boundary_geometry[:, 0],
                 boundary_geometry[:, 2] - boundary_geometry[:, 0]), axis=1)
    transferred_throat_area = float(boundary_areas[labels == THROAT_PISTON].sum())
    transferred_mouth_area = float(boundary_areas[labels == MOUTH_APERTURE].sum())
    if not math.isclose(transferred_throat_area, domain.throat_area_m2, rel_tol=0.05):
        raise ValueError("TetWild throat area changed by more than 5%")
    if not math.isclose(transferred_mouth_area, domain.mouth_area_m2, rel_tol=0.02):
        raise ValueError("TetWild mouth area changed by more than 2%")

    cells = [("triangle", boundary), ("tetra", tetrahedra)]
    triangle_attributes = labels.astype(np.int32) + 1
    cell_data = {
        "gmsh:physical": [triangle_attributes,
                          np.full(len(tetrahedra), 4, dtype=np.int32)],
        "gmsh:geometrical": [triangle_attributes,
                             np.full(len(tetrahedra), 4, dtype=np.int32)],
    }
    field_data = {"wall": np.array([1, 2]), "throat": np.array([2, 2]),
                  "mouth": np.array([3, 2]), "air": np.array([4, 3])}
    path.parent.mkdir(parents=True, exist_ok=True)
    meshio.write(path, meshio.Mesh(output_vertices, cells, cell_data=cell_data,
                                  field_data=field_data), file_format="gmsh22",
                 binary=False)
    return VolumeMeshReport(len(output_vertices), len(tetrahedra), maximum_actual_edge,
                            {label: [label + 1] for label in range(3)},
                            float(np.max(geometric_error)))
