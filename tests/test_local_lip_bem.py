from pathlib import Path
import unittest

import numpy as np

from app.aperture_field import ApertureField
from app.local_lip_bem import (
    LocalLipSettings,
    build_local_lip_mesh,
    monopole_pressure_gradient,
)


YAML_PATH = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"


class LocalLipBEMTests(unittest.TestCase):
    def test_local_lip_is_closed_and_respects_depth_and_edge_limit(self) -> None:
        settings = LocalLipSettings(retained_depth_m=0.025,
                                    elements_per_wavelength=6.0)
        lip = build_local_lip_mesh(YAML_PATH, 500.0, settings)
        self.assertTrue(lip.surface.is_watertight)
        self.assertTrue(lip.surface.is_winding_consistent)
        self.assertEqual(len(lip.surface.split()), 1)
        self.assertLessEqual(lip.maximum_edge_m, lip.target_edge_m + 1e-12)
        self.assertAlmostEqual(lip.retained_depth_m, 0.025)
        self.assertLess(lip.rear_closure_z_m, lip.surface.bounds[1, 2])
        self.assertGreater(lip.surface.volume, 0.0)
        self.assertGreater(int(np.count_nonzero(lip.rear_face_mask)), 0)
        self.assertGreater(int(np.count_nonzero(lip.rear_vertex_mask)), 0)
        self.assertAlmostEqual(
            float(np.sum(lip.rear_vertex_area_weights_m2)),
            float(np.sum(lip.surface.area_faces[lip.rear_face_mask])), places=12)
        self.assertGreaterEqual(lip.minimum_angle_deg, settings.minimum_angle_deg)
        self.assertLessEqual(lip.maximum_aspect_ratio, settings.maximum_aspect_ratio)
        deeper = build_local_lip_mesh(
            YAML_PATH, 500.0,
            LocalLipSettings(retained_depth_m=0.05, elements_per_wavelength=6.0))
        self.assertAlmostEqual(lip.rear_closure_z_m - deeper.rear_closure_z_m,
                               0.025, places=12)
        self.assertGreater(deeper.surface.volume, lip.surface.volume)

    def test_monopole_gradient_matches_centered_finite_difference(self) -> None:
        field = ApertureField(
            1_000.0,
            np.array([[-0.04, 0.0, 0.0], [0.04, 0.0, 0.01]]),
            np.array([0.01, 0.012]),
            np.array([1.0 + 0.2j, 0.7 - 0.1j]),
        )
        point = np.array([[0.2, -0.1, 0.5]])
        _, gradient = monopole_pressure_gradient(field, point)
        epsilon = 1e-6
        numerical = np.empty(3, dtype=np.complex128)
        for axis in range(3):
            offset = np.zeros((1, 3))
            offset[0, axis] = epsilon
            plus, _ = monopole_pressure_gradient(field, point + offset)
            minus, _ = monopole_pressure_gradient(field, point - offset)
            numerical[axis] = (plus[0] - minus[0]) / (2.0 * epsilon)
        np.testing.assert_allclose(gradient[0], numerical, rtol=2e-8, atol=2e-8)

    def test_source_sheet_singularity_is_rejected(self) -> None:
        field = ApertureField(500.0, np.zeros((1, 3)), np.ones(1),
                              np.ones(1, dtype=np.complex128))
        with self.assertRaisesRegex(ValueError, "singular"):
            monopole_pressure_gradient(field, np.zeros((1, 3)))


if __name__ == "__main__":
    unittest.main()
