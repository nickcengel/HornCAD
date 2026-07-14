from pathlib import Path
import unittest

import numpy as np

from app.helmholtz_bem_3d import acoustic_body_mesh, receiver_directions


class HelmholtzBEM3DTests(unittest.TestCase):
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

    def test_receiver_axes_follow_horn_coordinates(self) -> None:
        angles = np.array([0.0, 90.0])
        horizontal = receiver_directions(angles, 0.0)
        vertical = receiver_directions(angles, 90.0)
        np.testing.assert_allclose(horizontal[:, 0], [0.0, 0.0, 1.0], atol=1e-12)
        np.testing.assert_allclose(horizontal[:, 1], [1.0, 0.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(vertical[:, 1], [0.0, 1.0, 0.0], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
