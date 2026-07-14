from pathlib import Path
import unittest

import numpy as np

from app.acoustic_domain import (
    MOUTH_APERTURE,
    RIGID_WALL,
    THROAT_PISTON,
    build_interior_acoustic_domain,
)


class InteriorAcousticDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        cls.domain = build_interior_acoustic_domain(yaml_path, 16, 12)

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


if __name__ == "__main__":
    unittest.main()
