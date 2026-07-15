"""Native matrix-free Helmholtz BEM backend for closed HornCAD surfaces.

Python owns geometry and run orchestration. NGSolve performs singular
quadrature, FMM layer-operator products, and Krylov iteration in native code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import resource
import sys
import time
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
    timings_s: dict[str, float]
    peak_rss_gib: float

    def potential(self) -> Any:
        # NGSolve's exterior Calderon convention is u = K p - V g.
        return (self.double_layer.GetPotential(self.trace)
                - self.single_layer.GetPotential(self.neumann))


def _imports() -> dict[str, Any]:
    try:
        from netgen.csg import Pnt
        from netgen.meshing import Element2D, FaceDescriptor, Mesh, MeshPoint
        from ngsolve import (BilinearForm, GridFunction, H1, TaskManager, ds,
                             grad, specialcf, Norm, solvers)
        from ngsolve.bem import HelmholtzDL, HelmholtzSL
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
                  integration_order: int = 7,
                  gmres_restart: int | None = None,
                  fmm_min_order: int = 6,
                  fmm_order_factor: float = 0.8,
                  fmm_separation: float = 1.5,
                  fmm_max_direct: int = 100,
                  regularizer: str = "laplace") -> NGSolveBEMSolution:
    """Solve the resonance-safe direct Burton--Miller Neumann equation.

    With NGSolve's exterior Calderon signs,

      [D + i k (M/2 - K)] p = [-M/2 - K' - i k V] g.

    A Laplace single-layer Calderon regularizer supplies an order-minus-one,
    non-oscillatory left preconditioner.
    """
    if frequency_hz <= 0 or sound_speed_m_s <= 0:
        raise ValueError("frequency and sound speed must be positive")
    started = time.perf_counter()
    timings: dict[str, float] = {}

    def phase(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = now - since
        print(f"BEM {frequency_hz:g} Hz: {name} {timings[name]:.2f}s "
              f"(elapsed {now - started:.2f}s)", flush=True)
        return now

    ng = _imports()
    mesh = surface_mesh(vertices, faces, domain_indices)
    space = ng["H1"](mesh, order=1, complex=True)
    trial, test = space.TnT()
    checkpoint = phase("surface_setup", started)
    k = 2 * math.pi * frequency_hz / sound_speed_m_s
    fmm_options = {"fmm_minorder": fmm_min_order,
                   "fmm_order_factor": fmm_order_factor,
                   "fmm_separation": fmm_separation,
                   "fmm_maxdirect": fmm_max_direct}
    normal = ng["specialcf"].normal(3)
    # The surface curl is n x grad_Gamma. It cannot be replaced by grad_Gamma
    # inside the nonlocal dot product because source and target normals differ.
    from ngsolve import Cross
    trial_rotation = Cross(normal, ng["grad"](trial).Trace())
    test_rotation = Cross(normal, ng["grad"](test).Trace())
    with ng["TaskManager"]():
        single = ng["HelmholtzSL"](trial * ng["ds"], k, **fmm_options) * test * ng["ds"]
        double = ng["HelmholtzDL"](trial * ng["ds"], k, **fmm_options) * test * ng["ds"]
        # Weakly singular regularization of the Helmholtz hypersingular form:
        # <D p,q> = <V curl_Gamma p,curl_Gamma q>
        #             - k^2 <V(n p),n q>.
        # Component-wise scalar potentials avoid the vector-FMM SIMD bug in
        # NGSolve 6.2.2606 and expose the FMM accuracy controls.
        surface_gradient_terms = [
            ng["HelmholtzSL"](trial_rotation[i] * ng["ds"], k, **fmm_options)
            * test_rotation[i] * ng["ds"] for i in range(3)]
        surface_gradient = (surface_gradient_terms[0] + surface_gradient_terms[1]
                            + surface_gradient_terms[2])
        normal_mass_terms = [
            ng["HelmholtzSL"]((normal[i] * trial) * ng["ds"], k, **fmm_options)
            * (normal[i] * test) * ng["ds"] for i in range(3)]
        normal_mass = normal_mass_terms[0] + normal_mass_terms[1] + normal_mass_terms[2]
        hyper = surface_gradient - k * k * normal_mass
        mass = ng["BilinearForm"](trial * test * ng["ds"]).Assemble()
        if regularizer == "physical":
            regularizing_single = single
        elif regularizer == "imaginary":
            regularizing_single = (ng["HelmholtzSL"](
                trial * ng["ds"], 1j * k, **fmm_options) * test * ng["ds"])
        elif regularizer == "laplace":
            regularizing_single = (ng["HelmholtzSL"](
                trial * ng["ds"], 1e-10, **fmm_options) * test * ng["ds"])
        else:
            raise ValueError("regularizer must be 'physical', 'imaginary', or 'laplace'")
    checkpoint = phase("operator_setup", checkpoint)

    prescribed = ng["GridFunction"](space)
    prescribed.Set(neumann_value, definedon=mesh.Boundaries("throat"))
    eta = 1j * k
    lhs = hyper.mat + eta * (0.5 * mass.mat - double.mat)
    rhs = prescribed.vec.CreateVector()
    with ng["TaskManager"]():
        rhs.data = ((-0.5 * mass.mat - double.mat.T) * prescribed.vec
                    - eta * single.mat * prescribed.vec)
    checkpoint = phase("rhs", checkpoint)
    iterations = 0

    def count_iteration(_solution: Any) -> None:
        nonlocal iterations
        iterations += 1
        if iterations == 1 or iterations % 10 == 0:
            print(f"BEM {frequency_hz:g} Hz: GMRES iteration {iterations} "
                  f"(elapsed {time.perf_counter() - started:.2f}s)", flush=True)

    mass_inverse = mass.mat.Inverse()
    # Calderon operator preconditioning: V maps the order +1 principal part
    # of the hypersingular equation back to order zero. The mass inverses
    # convert both weak-form matrices to composable coefficient operators.
    preconditioner = _ThreeMatrixProduct.build(
        mass_inverse, regularizing_single.mat, mass_inverse)
    weighted_rhs = rhs.CreateVector()
    with ng["TaskManager"]():
        weighted_rhs.data = preconditioner * rhs
    rhs_scale = max(float(ng["Norm"](weighted_rhs)), 1e-30)
    scaled_rhs = rhs.CreateVector()
    scaled_rhs.data = rhs
    scaled_rhs *= 1.0 / rhs_scale
    checkpoint = phase("preconditioner_rhs", checkpoint)
    with ng["TaskManager"]():
        vector = ng["solvers"].GMRes(
            A=lhs, b=scaled_rhs, pre=preconditioner,
            tol=0.5 * tolerance, maxsteps=max_iterations,
            restart=gmres_restart, callback=count_iteration,
            printrates=False)
        vector *= rhs_scale
    checkpoint = phase("gmres", checkpoint)
    with ng["TaskManager"]():
        residual = rhs.CreateVector()
        residual.data = rhs - lhs * vector
        weighted_residual = rhs.CreateVector()
        weighted_residual.data = preconditioner * residual
        relative_residual = float(ng["Norm"](weighted_residual)
                                  / max(ng["Norm"](weighted_rhs), 1e-30))
    checkpoint = phase("residual", checkpoint)
    if relative_residual > tolerance * 1.25:
        raise RuntimeError(
            f"NGSolve BEM GMRES failed at {frequency_hz:g} Hz after "
            f"{iterations} iterations: relative residual={relative_residual:.3g}")
    trace = ng["GridFunction"](space)
    trace.vec.data = vector
    timings["total"] = time.perf_counter() - started
    peak_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak_rss_gib = peak_rss / 1024 ** 3 if sys.platform == "darwin" else peak_rss / 1024 ** 2
    return NGSolveBEMSolution(trace, prescribed, single, double, mesh,
                              int(space.ndof), iterations, k, relative_residual,
                              timings, peak_rss_gib)


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
        # Submit all target coordinates together. Calling the potential once
        # per point creates a long serial Python/FMM tail on production meshes.
        mapped = target_mesh(query[:, 0], query[:, 1], query[:, 2])
        return np.asarray(potential(mapped), dtype=complex).reshape(-1)

    return evaluate
