import cmath
import unittest

import numpy as np
from netgen.occ import Fuse, Sphere
import trimesh

from app.tools.ngsolve_bem_backend import make_point_evaluator, solve_neumann


class NGSolveBEMBackendTests(unittest.TestCase):
    @staticmethod
    def sphere_surface(maxh: float = 0.3):
        shape = Fuse(Sphere((0, 0, 0), 1).faces)
        mesh = shape.GenerateMesh(maxh=maxh)
        vertices = np.asarray([[vertex.point[0], vertex.point[1], vertex.point[2]]
                               for vertex in mesh.vertices])
        faces = np.asarray([[number.nr - 1 for number in element.vertices]
                            for element in mesh.ngmesh.Elements2D()], dtype=int)
        return vertices, faces, np.ones(len(faces), dtype=np.uint32)

    def test_pulsating_sphere_matches_analytic_neumann_trace(self) -> None:
        vertices, faces, domains = self.sphere_surface()
        solution = solve_neumann(vertices, faces, domains, 1 + 0j,
                                 frequency_hz=2 * 343.21 / (2 * np.pi),
                                 sound_speed_m_s=343.21, tolerance=1e-8)
        from ngsolve import BND, Integrate
        mean = Integrate(solution.trace, solution.mesh, BND) / Integrate(
            1, solution.mesh, BND)
        h0 = lambda z: -1j * cmath.exp(1j * z) / z
        dh0 = lambda z: (cmath.exp(1j * z) / z
                         + 1j * cmath.exp(1j * z) / z ** 2)
        exact = h0(2) / (2 * dh0(2))
        self.assertLess(abs(mean - exact) / abs(exact), 0.015)
        self.assertGreater(solution.iterations, 0)
        self.assertLess(solution.relative_residual, 1.05e-8)

    def test_exterior_potential_is_finite(self) -> None:
        vertices, faces, domains = self.sphere_surface(0.4)
        solution = solve_neumann(vertices, faces, domains, 1 + 0j,
                                 frequency_hz=100, sound_speed_m_s=343.21,
                                 tolerance=1e-4, fmm_min_order=10,
                                 fmm_order_factor=1.5,
                                 fmm_separation=2.0,
                                 regularizer="physical")
        points = np.asarray([[2.0, 0, 0], [0, 0, 2.0]])
        values = make_point_evaluator(solution, points)(points)
        self.assertTrue(np.all(np.isfinite(values)))
        self.assertLess(abs(abs(values[0]) - abs(values[1])), 0.03 * abs(values[0]))

    def test_even_even_quarter_sphere_matches_analytic_trace(self) -> None:
        vertices, faces, _ = self.sphere_surface(0.6)
        quarter = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
        for normal in (np.asarray([1.0, 0.0, 0.0]),
                       np.asarray([0.0, 1.0, 0.0])):
            quarter = trimesh.intersections.slice_mesh_plane(
                quarter, normal, np.zeros(3), cap=False)
            quarter.remove_unreferenced_vertices()
        quarter.merge_vertices(digits_vertex=12)
        quarter.update_faces(quarter.unique_faces())
        quarter.remove_unreferenced_vertices()
        domains = np.ones(len(quarter.faces), dtype=np.uint32)
        solution = solve_neumann(
            quarter.vertices, quarter.faces, domains, 1 + 0j,
            frequency_hz=2 * 343.21 / (2 * np.pi),
            sound_speed_m_s=343.21, tolerance=1e-4,
            symmetry_planes=("x=0", "y=0"))
        from ngsolve import BND, Integrate
        mean = Integrate(solution.trace, solution.mesh, BND) / Integrate(
            1, solution.mesh, BND)
        h0 = lambda z: -1j * cmath.exp(1j * z) / z
        dh0 = lambda z: (cmath.exp(1j * z) / z
                         + 1j * cmath.exp(1j * z) / z ** 2)
        exact = h0(2) / (2 * dh0(2))
        self.assertLess(abs(mean - exact) / abs(exact), 0.02)
        self.assertLess(solution.relative_residual, 1e-4)
        self.assertLess(len(quarter.vertices), len(vertices))


if __name__ == "__main__":
    unittest.main()
