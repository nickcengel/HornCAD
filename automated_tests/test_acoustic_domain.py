from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.tools.acoustic_domain import (
    MOUTH_APERTURE,
    RIGID_WALL,
    THROAT_PISTON,
    build_interior_acoustic_domain,
    write_gmsh_volume_mesh,
    write_tetwild_volume_mesh,
    build_quadrant_acoustic_domain,
)


class InteriorAcousticDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        yaml_path = Path(__file__).parents[1] / "examples" / "osse-400x280-reference" / "project.yaml"
        cls.domain = build_interior_acoustic_domain(yaml_path, 16, 24)

    def test_closure_is_conforming_watertight_and_labeled(self) -> None:
        domain = self.domain
        self.assertTrue(domain.surface.is_watertight)
        self.assertTrue(domain.surface.is_winding_consistent)
        self.assertEqual(set(np.unique(domain.face_domains)),
                         {RIGID_WALL, THROAT_PISTON, MOUTH_APERTURE})
        self.assertTrue(np.array_equal(
            domain.throat_ring_indices, np.arange(len(domain.throat_ring_indices))))
        self.assertEqual(len(domain.mouth_ring_indices), len(domain.throat_ring_indices))

    def test_caps_have_positive_area_and_expected_outward_direction(self) -> None:
        domain = self.domain
        self.assertGreater(domain.throat_area_m2, 0.0)
        self.assertGreater(domain.mouth_area_m2, domain.throat_area_m2)
        throat_normal = np.average(domain.surface.face_normals[domain.throat_faces], axis=0,
                                   weights=domain.surface.area_faces[domain.throat_faces])
        mouth_normal = np.average(domain.surface.face_normals[domain.mouth_faces], axis=0,
                                  weights=domain.surface.area_faces[domain.mouth_faces])
        self.assertLess(throat_normal[2], -0.99)
        self.assertGreater(mouth_normal[2], 0.5)

    def test_unit_inward_volume_flow_has_negative_boundary_normal_velocity(self) -> None:
        normal_velocity = -1.0 / self.domain.throat_area_m2
        self.assertAlmostEqual(-normal_velocity * self.domain.throat_area_m2, 1.0, places=12)

    def test_gmsh_volume_preserves_boundary_physical_groups(self) -> None:
        import meshio
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "interior.msh"
            report = write_gmsh_volume_mesh(self.domain, path, 0.031)
            mesh = meshio.read(path)
        physical = np.concatenate(mesh.cell_data["gmsh:physical"])
        self.assertEqual(set(np.unique(physical)), {1, 2, 3, 4})
        self.assertGreater(report.nodes, 0)
        self.assertGreater(report.tetrahedra, 0)
        self.assertLessEqual(report.maximum_tetrahedron_edge_m, 0.031 * 1.000001)
        self.assertEqual(set(report.boundary_surface_patches),
                         {RIGID_WALL, THROAT_PISTON, MOUTH_APERTURE})
        self.assertLess(report.maximum_label_match_error_m, 1e-6)
        triangle_blocks = [block.data for block in mesh.cells if block.type == "triangle"]
        triangle_tags = [tags for block, tags in zip(mesh.cells, mesh.cell_data["gmsh:physical"])
                         if block.type == "triangle"]
        triangles = np.vstack(triangle_blocks)
        tags = np.concatenate(triangle_tags)
        points = mesh.points[triangles]
        areas = 0.5 * np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                              points[:, 2] - points[:, 0]), axis=1)
        self.assertAlmostEqual(float(areas[tags == 2].sum()), self.domain.throat_area_m2,
                               delta=self.domain.throat_area_m2 * 0.15)
        self.assertAlmostEqual(float(areas[tags == 3].sum()), self.domain.mouth_area_m2,
                               delta=self.domain.mouth_area_m2 * 0.02)

    def test_tetwild_volume_transfers_acoustic_boundaries(self) -> None:
        import meshio
        yaml_path = Path(__file__).parents[1] / "examples" / "osse-400x280-reference" / "project.yaml"
        domain = build_interior_acoustic_domain(yaml_path, 8, 8)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "interior-tetwild.msh"
            report = write_tetwild_volume_mesh(
                domain, path, 0.08, threads=2, edge_length_ratio=0.06)
            mesh = meshio.read(path)
        physical = np.concatenate(mesh.cell_data["gmsh:physical"])
        self.assertEqual(set(np.unique(physical)), {1, 2, 3, 4})
        self.assertLessEqual(report.maximum_tetrahedron_edge_m, 0.08)
        self.assertLess(report.maximum_label_match_error_m, 3e-4)
        triangles = next(block.data for block in mesh.cells if block.type == "triangle")
        tags = next(tags for block, tags in zip(mesh.cells, mesh.cell_data["gmsh:physical"])
                    if block.type == "triangle")
        points = mesh.points[triangles]
        areas = 0.5 * np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                              points[:, 2] - points[:, 0]), axis=1)
        self.assertAlmostEqual(float(areas[tags == 2].sum()), domain.throat_area_m2,
                               delta=domain.throat_area_m2 * 0.05)
        self.assertAlmostEqual(float(areas[tags == 3].sum()), domain.mouth_area_m2,
                               delta=domain.mouth_area_m2 * 0.02)

    def test_quadrant_is_watertight_and_one_quarter_area(self) -> None:
        yaml_path = (Path(__file__).parents[1] / "examples" / "osse-400x280-reference" / "project.yaml")
        full = build_interior_acoustic_domain(yaml_path, 16, 24)
        quadrant = build_quadrant_acoustic_domain(yaml_path, 16, 24)
        self.assertTrue(quadrant.surface.is_watertight)
        self.assertTrue(quadrant.surface.is_winding_consistent)
        self.assertGreaterEqual(float(quadrant.surface.vertices[:, 0].min()), -1e-10)
        self.assertGreaterEqual(float(quadrant.surface.vertices[:, 1].min()), -1e-10)
        self.assertAlmostEqual(quadrant.throat_area_m2 * 4.0,
                               full.throat_area_m2, delta=full.throat_area_m2 * 0.01)
        self.assertAlmostEqual(quadrant.mouth_area_m2 * 4.0,
                               full.mouth_area_m2, delta=full.mouth_area_m2 * 0.01)


if __name__ == "__main__":
    unittest.main()
