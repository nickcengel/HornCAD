"""Native matrix-free Helmholtz BEM backend for closed HornCAD surfaces.

Python owns geometry and run orchestration. NGSolve performs singular
quadrature, FMM layer-operator products, and Krylov iteration in native code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import numpy as np


class _ThreeMatrixProduct:
    """Factory namespace; concrete BaseMatrix subclass is built lazily."""

    @staticmethod
    def build(left: Any, middle: Any, right: Any) -> Any:
        from ngsolve import BaseMatrix

        class Product(BaseMatrix):
            def __init__(self) -> None:
                super().__init__()
                self.temporary_right = middle.CreateColVector()
                self.temporary_left = middle.CreateRowVector()

            def Height(self) -> int:
                return left.height

            def Width(self) -> int:
                return right.width

            def IsComplex(self) -> bool:
                return True

            def CreateRowVector(self) -> Any:
                return left.CreateRowVector()

            def CreateColVector(self) -> Any:
                return right.CreateColVector()

            def Mult(self, vector: Any, result: Any) -> None:
                self.temporary_right.data = right * vector
                self.temporary_left.data = middle * self.temporary_right
                result.data = left * self.temporary_left

        return Product()


@dataclass
class NGSolveBEMSolution:
    """Exterior Neumann solution and evaluable representation formula."""

    trace: Any
    neumann: Any
    single_layer: Any
    double_layer: Any
    mesh: Any
    dofs: int
    iterations: int
    wavenumber_m1: float
    relative_residual: float

    def potential(self) -> Any:
        # NGSolve's exterior Calderon convention is u = K p - V g.
        return (self.double_layer.GetPotential(self.trace)
                - self.single_layer.GetPotential(self.neumann))


def _imports() -> dict[str, Any]:
    try:
        from netgen.csg import Pnt
        from netgen.meshing import Element2D, FaceDescriptor, Mesh, MeshPoint
        from ngsolve import (BilinearForm, GridFunction, H1, TaskManager, ds, la,
                             Norm, solvers)
        from ngsolve.bem import (HelmholtzDoubleLayerPotentialOperator,
                                 HelmholtzHypersingularOperator,
                                 HelmholtzSingleLayerPotentialOperator)
    except ImportError as exc:  # pragma: no cover - exercised without optional extra
        raise RuntimeError(
            "the ngsolve-fmm backend requires ngsolve>=6.2.2606"
        ) from exc
    return locals()


def surface_mesh(vertices: np.ndarray, faces: np.ndarray,
                 domain_indices: np.ndarray) -> Any:
    """Create a labeled, surface-only NGSolve mesh without STL round-tripping."""
    ng = _imports()
    raw = ng["Mesh"](dim=3)
    points = [raw.Add(ng["MeshPoint"](ng["Pnt"](*map(float, point))))
              for point in np.asarray(vertices)]
    # Netgen boundary-condition numbers are one-based; domain 0 is rigid and
    # domain 1 is the driven throat in HornCAD's acoustic mesh.
    raw.Add(ng["FaceDescriptor"](bc=1))
    raw.Add(ng["FaceDescriptor"](bc=2))
    raw.SetBCName(0, "rigid")
    raw.SetBCName(1, "throat")
    for face, domain in zip(np.asarray(faces), np.asarray(domain_indices)):
        raw.Add(ng["Element2D"](int(domain) + 1,
                                [points[int(index)] for index in face]))
    from ngsolve import Mesh as NGSolveMesh
    return NGSolveMesh(raw)


def solve_neumann(vertices: np.ndarray, faces: np.ndarray,
                  domain_indices: np.ndarray, neumann_value: complex,
                  frequency_hz: float, sound_speed_m_s: float,
                  tolerance: float = 1e-5, max_iterations: int = 300,
                  integration_order: int = 7) -> NGSolveBEMSolution:
    """Solve the resonance-safe direct Burton--Miller Neumann equation.

    With NGSolve's exterior Calderon signs,

      [D + i k (M/2 - K)] p = [-M/2 - K' - i k V] g.

    The diagonal mass inverse is a deliberately inexpensive baseline
    preconditioner. It can later be replaced without changing this interface.
    """
    if frequency_hz <= 0 or sound_speed_m_s <= 0:
        raise ValueError("frequency and sound speed must be positive")
    ng = _imports()
    mesh = surface_mesh(vertices, faces, domain_indices)
    space = ng["H1"](mesh, order=1, complex=True)
    trial, test = space.TnT()
    k = 2 * math.pi * frequency_hz / sound_speed_m_s
    with ng["TaskManager"]():
        single = ng["HelmholtzSingleLayerPotentialOperator"](
            space, space, kappa=k, intorder=integration_order)
        double = ng["HelmholtzDoubleLayerPotentialOperator"](
            space, space, kappa=k, intorder=integration_order)
        hyper = ng["HelmholtzHypersingularOperator"](
            space, space, kappa=k, intorder=integration_order)
        mass = ng["BilinearForm"](trial * test * ng["ds"]).Assemble()

    prescribed = ng["GridFunction"](space)
    prescribed.Set(neumann_value, definedon=mesh.Boundaries("throat"))
    eta = 1j * k
    lhs = hyper.mat + eta * (0.5 * mass.mat - double.mat)
    rhs = prescribed.vec.CreateVector()
    rhs.data = ((-0.5 * mass.mat - double.mat.T) * prescribed.vec
                - eta * single.mat * prescribed.vec)
    iterations = 0

    def count_iteration(_solution: Any) -> None:
        nonlocal iterations
        iterations += 1

    mass_inverse = mass.mat.Inverse()
    # Calderon operator preconditioning: V maps the order +1 principal part
    # of the hypersingular equation back to order zero. The mass inverses
    # convert both weak-form matrices to composable coefficient operators.
    preconditioner = _ThreeMatrixProduct.build(
        mass_inverse, single.mat, mass_inverse)
    with ng["TaskManager"]():
        vector = ng["solvers"].GMRes(
            A=lhs, b=rhs, pre=preconditioner, tol=tolerance,
            maxsteps=max_iterations, callback=count_iteration, printrates=False)
        residual = rhs.CreateVector()
        residual.data = rhs - lhs * vector
        weighted_residual = preconditioner * residual
        weighted_rhs = preconditioner * rhs
        relative_residual = float(ng["Norm"](weighted_residual)
                                  / max(ng["Norm"](weighted_rhs), 1e-30))
    if relative_residual > tolerance * 1.05:
        raise RuntimeError(
            f"NGSolve BEM GMRES failed at {frequency_hz:g} Hz after "
            f"{iterations} iterations: relative residual={relative_residual:.3g}")
    trace = ng["GridFunction"](space)
    trace.vec.data = vector
    return NGSolveBEMSolution(trace, prescribed, single, double, mesh,
                              int(space.ndof), iterations, k, relative_residual)


def make_point_evaluator(solution: NGSolveBEMSolution,
                         points_m: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """Return an evaluator backed by one coarse target volume mesh.

    The target mesh only supplies coordinate transformations to NGSolve's
    potential coefficient function. It is not an acoustic FEM domain.
    """
    from netgen.occ import Box, Pnt

    points = np.asarray(points_m, dtype=float)
    lower = points.min(axis=0)
    upper = points.max(axis=0)
    span = max(float(np.ptp(points, axis=0).max()), 1e-3)
    # A nearly planar point cloud otherwise creates an OCC box with a
    # pathological aspect ratio and can make the auxiliary mesh generator fail.
    padding = max(1e-4, span * 1e-2)
    target_mesh = Box(Pnt(*(lower - padding)), Pnt(*(upper + padding))).GenerateMesh(
        maxh=max(span * 2, 1e-3))
    potential = solution.potential()

    def evaluate(query_points_m: np.ndarray) -> np.ndarray:
        query = np.asarray(query_points_m, dtype=float)
        # Some FMM evaluation paths return a one-entry SIMD container while
        # direct paths return a Python complex. Normalize both to one scalar.
        values = []
        for point in query:
            value = np.asarray(potential(target_mesh(*map(float, point))), dtype=complex)
            values.append(complex(value.reshape(-1)[0]))
        return np.asarray(values, dtype=complex)

    return evaluate
