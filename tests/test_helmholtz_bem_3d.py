from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from app.helmholtz_bem_3d import (
    AcousticMedium,
    GEOMETRY_SEED_AXIAL_STATIONS,
    GEOMETRY_SEED_SIDE_SAMPLES,
    MeshSettings,
    SourceDefinition,
    acoustic_body_mesh,
    build_acoustic_mesh,
    build_quadrant_acoustic_mesh,
    make_aperture_observer,
    piston_boundary_values,
    receiver_directions,
    execution_plan,
    parse_args,
    PipelineSettings,
)


class HelmholtzBEM3DTests(unittest.TestCase):
    def test_default_sweep_is_500_to_8000_hz_at_6_epw(self) -> None:
        args = parse_args(["horn.yaml"])
        self.assertEqual(args.start_hz, 500)
        self.assertEqual(args.stop_hz, 8_000)
        self.assertEqual(args.frequencies, 10)
        self.assertEqual(args.mesh_tier, "production")
        self.assertEqual(MeshSettings().maximum_frequency_hz, 8_000)
        self.assertEqual(MeshSettings().elements_per_wavelength, 6)
        self.assertFalse(args.full_geometry)
        self.assertEqual(GEOMETRY_SEED_SIDE_SAMPLES, 12)
        self.assertEqual(GEOMETRY_SEED_AXIAL_STATIONS, 16)
        self.assertTrue(PipelineSettings((500.0,), (0.0,)).quadrant_symmetry)

    def test_acoustic_body_is_closed_and_has_driven_throat_faces(self) -> None:
        yaml_path = (
            Path(__file__).parents[1]
            / "test_project"
            / "HornCAD-Body-400x260x250.YAML"
        )
        body, domains = acoustic_body_mesh(yaml_path, side_samples=6, axial_stations=8)
        self.assertTrue(body.is_watertight)
        self.assertTrue(body.is_winding_consistent)
        self.assertEqual(len(domains), len(body.faces))
        self.assertGreater(int(np.count_nonzero(domains)), 0)

    def test_quadrant_mesh_has_only_open_symmetry_boundaries(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        full = build_acoustic_mesh(yaml_path, MeshSettings(1_000.0, 6.0))
        quadrant = build_quadrant_acoustic_mesh(
            yaml_path, MeshSettings(1_000.0, 6.0))
        self.assertEqual(quadrant.symmetry_factor, 4)
        self.assertEqual(quadrant.symmetry_planes, ("x=0", "y=0"))
        self.assertLess(quadrant.report.vertices, full.report.vertices / 2)
        self.assertFalse(quadrant.surface.is_watertight)
        self.assertTrue(quadrant.surface.is_winding_consistent)
        self.assertEqual(quadrant.report.quality_failures, [])
        self.assertGreater(int(np.count_nonzero(quadrant.domain_indices)), 0)
        self.assertAlmostEqual(
            quadrant.source_area_m2,
            4 * quadrant.surface.area_faces[
                quadrant.domain_indices == 1].sum())
        self.assertLess(abs(quadrant.source_area_m2 - full.source_area_m2),
                        0.1 * full.source_area_m2)
        edges, counts = np.unique(quadrant.surface.edges_sorted, axis=0,
                                  return_counts=True)
        boundary = quadrant.surface.vertices[np.unique(edges[counts == 1])]
        self.assertTrue(np.all((np.abs(boundary[:, 0]) < 1e-10)
                               | (np.abs(boundary[:, 1]) < 1e-10)))

    def test_receiver_axes_follow_horn_coordinates(self) -> None:
        angles = np.array([0.0, 90.0])
        horizontal = receiver_directions(angles, 0.0)
        vertical = receiver_directions(angles, 90.0)
        np.testing.assert_allclose(horizontal[:, 0], [0.0, 0.0, 1.0], atol=1e-12)
        np.testing.assert_allclose(horizontal[:, 1], [1.0, 0.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(vertical[:, 1], [0.0, 1.0, 0.0], atol=1e-12)

    def test_wavelength_mesh_and_unit_volume_velocity(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        settings = MeshSettings(maximum_frequency_hz=1_000.0, elements_per_wavelength=6.0)
        mesh = build_acoustic_mesh(yaml_path, settings, side_samples=8, axial_stations=10)
        self.assertLessEqual(mesh.report.maximum_edge_m, settings.target_edge_m + 1e-10)
        self.assertTrue(mesh.report.watertight)
        self.assertEqual(mesh.report.connected_components, 1)
        self.assertEqual(mesh.report.quality_failures, [])
        velocity, neumann = piston_boundary_values(
            mesh, SourceDefinition(), 1_000.0, AcousticMedium()
        )
        self.assertAlmostEqual((velocity * mesh.source_area_m2).real, 1.0, places=12)
        self.assertAlmostEqual((velocity * mesh.source_area_m2).imag, 0.0, places=12)
        self.assertLess(neumann.imag, 0.0)

    def test_mouth_observer_is_offset_outward_and_area_weighted(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        mesh = build_acoustic_mesh(
            yaml_path, MeshSettings(1_000.0, 6.0), side_samples=8, axial_stations=10
        )
        observer = make_aperture_observer(mesh, 0.001)
        self.assertTrue(np.all(observer.normals[:, 2] > 0.0))
        self.assertTrue(np.all(observer.area_weights_m2 > 0.0))
        self.assertGreater(float(observer.area_weights_m2.sum()), 0.0)
        self.assertEqual(observer.positions_m.shape, observer.normals.shape)

    def test_execution_plan_avoids_cpu_oversubscription(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        mesh = build_acoustic_mesh(
            yaml_path, MeshSettings(1_000.0, 6.0), side_samples=8, axial_stations=10
        )
        settings = PipelineSettings((500.0, 1_000.0), (0.0, 90.0),
                                    mesh=MeshSettings(1_000.0, 6.0),
                                    maximum_workers=0, memory_limit_gib=1.0)
        plan = execution_plan(settings, mesh, 2)
        self.assertLessEqual(plan.workers * plan.threads_per_worker, plan.cpu_count)
        self.assertLessEqual(plan.workers, 2)
        self.assertEqual(settings.formulation, "combined-field")

    def test_fmm_execution_plan_parallelizes_safe_quadrant_frequencies(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        mesh = build_acoustic_mesh(
            yaml_path, MeshSettings(1_000.0, 6.0), side_samples=8,
            axial_stations=10)
        settings = PipelineSettings(tuple(np.linspace(500, 8_000, 10)),
                                    (0.0, 90.0), memory_limit_gib=48.0)
        with patch("app.helmholtz_bem_3d.os.cpu_count", return_value=20):
            plan = execution_plan(settings, mesh, 10)
        self.assertEqual(plan.workers, 10)
        self.assertEqual(plan.threads_per_worker, 1)
        self.assertLess(plan.workers * plan.estimated_memory_per_worker_gib, 48)


if __name__ == "__main__":
    unittest.main()
