from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.acoustic_domain import build_interior_acoustic_domain, write_gmsh_volume_mesh
from app.interior_fem import solve_interior_frequency


class InteriorFEMTests(unittest.TestCase):
    def test_reduced_horn_couples_to_nonlocal_mouth(self) -> None:
        yaml_path = Path(__file__).parents[1] / "test_project" / "HornCAD-Body-400x260x250.YAML"
        domain = build_interior_acoustic_domain(yaml_path, 16, 24)
        with tempfile.TemporaryDirectory() as temporary:
            mesh_path = Path(temporary) / "interior.msh"
            write_gmsh_volume_mesh(domain, mesh_path, 0.031)
            result = solve_interior_frequency(mesh_path, 500.0)
            condensed = solve_interior_frequency(mesh_path, 500.0,
                                                  coupling_method="condensed")
        self.assertLess(result.relative_residual, 1e-9)
        self.assertGreater(result.radiated_power_w, 0.0)
        self.assertAlmostEqual(result.throat_area_m2, domain.throat_area_m2,
                               delta=domain.throat_area_m2 * 0.15)
        self.assertAlmostEqual(result.mouth_area_m2, domain.mouth_area_m2, delta=2e-3)
        self.assertTrue(np.all(np.isfinite(result.mouth_pressure)))
        self.assertTrue(np.all(np.isfinite(result.mouth_normal_velocity)))
        np.testing.assert_allclose(result.pressure, condensed.pressure,
                                   rtol=2e-9, atol=2e-6)
        np.testing.assert_allclose(result.mouth_normal_velocity,
                                   condensed.mouth_normal_velocity,
                                   rtol=2e-9, atol=2e-9)


if __name__ == "__main__":
    unittest.main()
