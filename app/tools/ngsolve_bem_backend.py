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
    image_traces: tuple[Any, ...] = ()
    image_neumann: tuple[Any, ...] = ()
    image_single_layers: tuple[Any, ...] = ()
    image_double_layers: tuple[Any, ...] = ()

    def potential(self) -> Any:
        # NGSolve's exterior Calderon convention is u = K p - V g.
        if self.image_traces:
            terms = [
                double.GetPotential(trace) - single.GetPotential(neumann)
                for trace, neumann, single, double in zip(
                    self.image_traces, self.image_neumann,
                    self.image_single_layers, self.image_double_layers)]
            return sum(terms[1:], terms[0])
        return (self.double_layer.GetPotential(self.trace)
                - self.single_layer.GetPotential(self.neumann))


def _imports() -> dict[str, Any]:
    try:
        from netgen.csg import Pnt
        from netgen.meshing import Element2D, FaceDescriptor, Mesh, MeshPoint
        from ngsolve import (BilinearForm, LinearForm, GridFunction, H1,
                             TaskManager, SetNumThreads, ds, grad, specialcf, Norm, solvers,
                             Periodic, Compress)
        from ngsolve.bem import (HelmholtzDL, HelmholtzSL,
                                 HelmholtzHypersingularOperator)
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


def symmetric_periodic_surface_space(vertices: np.ndarray, faces: np.ndarray,
                                     domain_indices: np.ndarray
                                     ) -> tuple[Any, Any, str, str]:
    """Build connected seam topology and label the independent target quadrant."""
    ng = _imports()
    reflected_vertices: list[np.ndarray] = []
    reflected_faces: list[list[int]] = []
    reflected_domains: list[int] = []
    coordinate_index: dict[tuple[float, float, float], int] = {}
    representatives: list[tuple[float, float, float]] = []
    for image_index, (x_sign, y_sign) in enumerate(
            ((1.0, 1.0), (-1.0, 1.0),
             (1.0, -1.0), (-1.0, -1.0))):
        local_indices = []
        for point in np.asarray(vertices, dtype=float):
            reflected = np.asarray(
                [x_sign * point[0], y_sign * point[1], point[2]])
            reflected[np.abs(reflected) < 5e-13] = 0.0
            key = tuple(np.round(reflected, 12))
            if key not in coordinate_index:
                coordinate_index[key] = len(reflected_vertices)
                reflected_vertices.append(reflected)
                representatives.append(tuple(np.round(
                    [abs(reflected[0]), abs(reflected[1]), reflected[2]], 12)))
            local_indices.append(coordinate_index[key])
        image_faces = (np.asarray(faces)[:, [0, 2, 1]]
                       if x_sign * y_sign < 0 else np.asarray(faces))
        for face, domain in zip(image_faces, domain_indices):
            reflected_faces.append([local_indices[int(index)] for index in face])
            reflected_domains.append(2 * image_index + int(domain))

    raw = ng["Mesh"](dim=3)
    points = [raw.Add(ng["MeshPoint"](ng["Pnt"](*map(float, point))))
              for point in reflected_vertices]
    for image_index in range(4):
        raw.Add(ng["FaceDescriptor"](bc=2 * image_index + 1))
        raw.Add(ng["FaceDescriptor"](bc=2 * image_index + 2))
        raw.SetBCName(2 * image_index, f"rigid_q{image_index}")
        raw.SetBCName(2 * image_index + 1, f"throat_q{image_index}")
    for face, domain in zip(reflected_faces, reflected_domains):
        raw.Add(ng["Element2D"](domain + 1,
                                [points[index] for index in face]))
    for index, representative in enumerate(representatives):
        master = coordinate_index[representative]
        if index != master:
            raw.AddPointIdentification(points[master], points[index], 1)
    from ngsolve import Mesh as NGSolveMesh
    mesh = NGSolveMesh(raw)
    base_space = ng["H1"](mesh, order=1, complex=True)
    periodic = ng["Periodic"](base_space)
    space = ng["Compress"](periodic, active_dofs=periodic.FreeDofs())
    if space.ndof != len(vertices):
        raise RuntimeError(
            f"symmetry compression produced {space.ndof} DOFs for "
            f"{len(vertices)} quadrant vertices")
    return mesh, space, "rigid_q0|throat_q0", "throat_q0"


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
                  regularizer: str = "laplace",
                  symmetry_planes: tuple[str, ...] = ()) -> NGSolveBEMSolution:
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
    if symmetry_planes not in ((), ("x=0", "y=0")):
        raise ValueError("supported symmetry is empty or ('x=0', 'y=0')")
    if symmetry_planes:
        # NGSolve 6.2.2606 races in the asymmetric full-source/q0-target
        # hypersingular apply. Enforce correctness for direct API callers too;
        # the sweep scheduler recovers parallelism across frequency processes.
        ng["SetNumThreads"](1)
        mesh, space, target_boundaries, target_throat = symmetric_periodic_surface_space(
            vertices, faces, domain_indices)
    else:
        mesh = surface_mesh(vertices, faces, domain_indices)
        space = ng["H1"](mesh, order=1, complex=True)
        target_boundaries, target_throat = "rigid|throat", "throat"
    image_specs = ((1.0, 1.0),)
    image_meshes = [mesh]
    image_spaces = [space]
    for x_sign, y_sign in image_specs[1:]:
        reflected_vertices = np.asarray(vertices, dtype=float).copy()
        reflected_vertices[:, 0] *= x_sign
        reflected_vertices[:, 1] *= y_sign
        reflected_faces = np.asarray(faces, dtype=int).copy()
        if x_sign * y_sign < 0:
            reflected_faces = reflected_faces[:, [0, 2, 1]]
        reflected_mesh = surface_mesh(reflected_vertices, reflected_faces,
                                      domain_indices)
        image_meshes.append(reflected_mesh)
        image_spaces.append(ng["H1"](reflected_mesh, order=1, complex=True))
    if any(image_space.ndof != space.ndof for image_space in image_spaces):
        raise RuntimeError("reflected symmetry spaces changed coefficient ordering")
    trial, test = space.TnT()
    target_ds = ng["ds"](target_boundaries)
    checkpoint = phase("surface_setup", started)
    k = 2 * math.pi * frequency_hz / sound_speed_m_s
    fmm_options = {"fmm_minorder": fmm_min_order,
                   "fmm_order_factor": fmm_order_factor,
                   "fmm_separation": fmm_separation,
                   "fmm_maxdirect": fmm_max_direct}
    def image_options(signs: tuple[float, float, float, float]) -> dict[str, Any]:
        # The connected reflected surface already supplies all four source
        # images. Periodic compression retains quadrant unknowns while the
        # stock FMM handles its full source tree and q0 target region.
        return fmm_options
    scalar_options = image_options((1.0, 1.0, 1.0, 1.0))
    normal = ng["specialcf"].normal(3)
    # The surface curl is n x grad_Gamma. It cannot be replaced by grad_Gamma
    # inside the nonlocal dot product because source and target normals differ.
    from ngsolve import Cross
    test_rotation = Cross(normal, ng["grad"](test).Trace())
    singles, doubles, hypers = [], [], []
    add_operators = lambda operators: sum(operators[1:], operators[0])
    with ng["TaskManager"]():
        for image_space in image_spaces:
            image_trial, _ = image_space.TnT()
            trial_rotation = Cross(normal, ng["grad"](image_trial).Trace())
            single_image = (ng["HelmholtzSL"](
                image_trial * ng["ds"], k, **scalar_options) * test * target_ds)
            double_image = (ng["HelmholtzDL"](
                image_trial * ng["ds"], k, **scalar_options) * test * target_ds)
            singles.append(single_image)
            doubles.append(double_image)
            curl_signs = ((1., 1., -1., -1.),
                          (1., -1., 1., -1.),
                          (1., -1., -1., 1.))
            normal_signs = ((1., -1., 1., -1.),
                            (1., 1., -1., -1.),
                            (1., 1., 1., 1.))
            surface_gradient_terms = [
                ng["HelmholtzSL"](trial_rotation[i] * ng["ds"], k,
                                   **image_options(curl_signs[i]))
                * test_rotation[i] * target_ds for i in range(3)]
            normal_mass_terms = [
                ng["HelmholtzSL"]((normal[i] * image_trial) * ng["ds"], k,
                                   **image_options(normal_signs[i]))
                * (normal[i] * test) * target_ds for i in range(3)]
            hypers.append(add_operators(surface_gradient_terms)
                          - k * k * add_operators(normal_mass_terms))
        single = add_operators(singles)
        double = add_operators(doubles)
        hyper = add_operators(hypers)
        mass = ng["BilinearForm"](trial * test * target_ds).Assemble()
        if regularizer == "physical":
            regularizing_single = single
        elif regularizer == "imaginary":
            regularizing_single = add_operators([
                ng["HelmholtzSL"](image_space.TnT()[0] * ng["ds"], 1j * k,
                                   **scalar_options) * test * target_ds
                for image_space in image_spaces])
        elif regularizer == "laplace":
            regularizing_single = add_operators([
                ng["HelmholtzSL"](image_space.TnT()[0] * ng["ds"], 1e-10,
                                   **scalar_options) * test * target_ds
                for image_space in image_spaces])
        else:
            raise ValueError("regularizer must be 'physical', 'imaginary', or 'laplace'")
    checkpoint = phase("operator_setup", checkpoint)

    prescribed = ng["GridFunction"](space)
    throat_load = ng["LinearForm"](
        neumann_value * test * ng["ds"](target_throat)).Assemble()
    prescribed.vec.data = mass.mat.Inverse() * throat_load.vec
    eta = 1j * k
    lhs = hyper.mat + eta * (0.5 * mass.mat - double.mat)
    rhs = prescribed.vec.CreateVector()
    if symmetry_planes:
        probe = prescribed.vec.CreateVector()
        probe.FV().NumPy()[:] = (np.arange(len(probe)) % 17 - 8) + 1j * (
            np.arange(len(probe)) % 11 - 5)
        first = rhs.CreateVector(); second = rhs.CreateVector()
        with ng["TaskManager"]():
            first.data = lhs * probe
            second.data = lhs * probe
        repeat_error = float(ng['Norm'](first-second)/max(ng['Norm'](first),1e-30))
        print(f"BEM {frequency_hz:g} Hz: operator repeat error {repeat_error:.3g}",
              flush=True)
        if repeat_error > 1e-12:
            raise RuntimeError(f"quadrant FMM is not repeatable: {repeat_error:.3g}")
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
            tol=0.1 * tolerance, maxsteps=max_iterations,
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
    image_traces = []
    image_neumann = []
    for image_space in image_spaces:
        image_trace = ng["GridFunction"](image_space)
        image_trace.vec.data = vector
        image_g = ng["GridFunction"](image_space)
        image_g.vec.data = prescribed.vec
        image_traces.append(image_trace)
        image_neumann.append(image_g)
    timings["total"] = time.perf_counter() - started
    peak_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak_rss_gib = peak_rss / 1024 ** 3 if sys.platform == "darwin" else peak_rss / 1024 ** 2
    return NGSolveBEMSolution(trace, prescribed, single, double, mesh,
                              int(space.ndof), iterations, k, relative_residual,
                              timings, peak_rss_gib, tuple(image_traces),
                              tuple(image_neumann), tuple(singles),
                              tuple(doubles))


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
