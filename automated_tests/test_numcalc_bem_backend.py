import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from app.tools.helmholtz_bem_3d import AcousticMesh, MeshReport
from app.tools.numcalc_bem_backend import (
    export_numcalc_case, far_field_points, reflect_quadrant_mesh,
)
from app.tools.run_numcalc_sweep import parse_args as parse_numcalc_args, ppo_frequency_grid
from app.tools.run_bem_suite import parse_args as parse_bem_args


class NumCalcBackendTests(unittest.TestCase):
    def test_standard_and_lower_level_sweeps_end_at_8000_hz(self) -> None:
        suite = parse_bem_args(["horn.yaml", "--output-dir", "results"])
        lower = parse_numcalc_args([
            "horn.yaml", "--numcalc", "NumCalc", "--output-dir", "results"])
        self.assertEqual(suite.stop_hz, 8_000.0)
        self.assertEqual(lower.stop_hz, 8_000.0)

    def test_quadrant_export_uses_only_input_faces_and_native_symmetry(self) -> None:
        surface = trimesh.Trimesh(
            vertices=np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                                 [0, 0, 1]], dtype=float),
            faces=np.asarray([[0, 2, 1], [0, 1, 3]], dtype=int), process=False)
        report = MeshReport(2, 4, 4, 1, 1, 1, 1, 30, 2, False, True, 1,
                            [], 1, 1, 0)
        mesh = AcousticMesh(surface, np.asarray([0, 1]), 0.5,
                            np.zeros(3), np.zeros((4, 3)), report, "test",
                            symmetry_factor=4, symmetry_planes=("x=0", "y=0"))
        points, cuts = far_field_points(np.zeros(3), 500, 343.21, (0, 90))
        with tempfile.TemporaryDirectory() as directory:
            case = export_numcalc_case(Path(directory), mesh, 500, points,
                                       method="dense")
            text = (case.source_dir / "NC.inp").read_text()
            elements = (case.root / "ObjectMeshes/Reference/Elements.txt").read_text()
        self.assertIn("SYMMETRY\n1 1 0", text)
        self.assertIn("ELEM 1 TO 1 VELO 2", text)
        self.assertEqual(elements.splitlines()[0], "2")
        self.assertEqual(case.boundary_elements, 2)
        self.assertEqual(cuts["horizontal"], slice(0, 2))

    def test_reflected_full_mesh_reuses_quadrant_panels(self) -> None:
        surface = trimesh.Trimesh(
            vertices=np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
            faces=np.asarray([[0, 1, 2]], dtype=int), process=False)
        report = MeshReport(1, 3, 3, 1, 1, 1, 1, 30, 2, False, True, 1,
                            [], 1, 1, 0)
        quarter = AcousticMesh(surface, np.asarray([1]), 2.0,
                               np.zeros(3), np.zeros((4, 3)), report, "test",
                               symmetry_factor=4,
                               symmetry_planes=("x=0", "y=0"))
        full = reflect_quadrant_mesh(quarter)
        self.assertEqual(len(full.surface.faces), 4)
        self.assertEqual(full.symmetry_factor, 1)
        self.assertEqual(full.symmetry_planes, ())
        self.assertEqual(full.source_area_m2, quarter.source_area_m2)

    def test_default_ppo_grid_uses_about_ten_points_per_octave(self) -> None:
        frequencies = ppo_frequency_grid(500, 5_000, 10)
        self.assertEqual(len(frequencies), 35)
        self.assertEqual(frequencies[0], 500)
        self.assertEqual(frequencies[-1], 5_000)
        actual = (len(frequencies) - 1) / np.log2(10)
        self.assertGreaterEqual(actual, 10)
        self.assertLess(actual, 10.25)


if __name__ == "__main__":
    unittest.main()
