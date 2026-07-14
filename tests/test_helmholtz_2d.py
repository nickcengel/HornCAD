from pathlib import Path
import unittest

import numpy as np

from app.helmholtz_2d import (
    Medium,
    gmsh_half_domain,
    horncad_plane_geometry,
    solve_plane_sweep,
)


class Helmholtz2DTests(unittest.TestCase):
    def test_coarse_horizontal_smoke_solve_is_finite_and_normalized(self) -> None:
        yaml_path = (
            Path(__file__).parents[1]
            / "test_project"
            / "HornCAD-Body-400x260x250.YAML"
        )
        plane = horncad_plane_geometry(yaml_path, "h", wall_samples=31)
        domain = gmsh_half_domain(plane, max_element_m=0.06, exterior_extent_m=0.4)
        result = solve_plane_sweep(
            domain,
            frequencies_hz=np.array([500.0]),
            angles_deg=np.array([0.0, 45.0, 90.0]),
            receiver_radius_m=0.28,
            medium=Medium(),
            floor_db=-40.0,
        )
        self.assertTrue(np.all(np.isfinite(result)))
        self.assertAlmostEqual(float(result[0, 0]), 0.0, places=12)


if __name__ == "__main__":
    unittest.main()
