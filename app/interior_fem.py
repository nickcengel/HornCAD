"""Reference interior FEM coupled to a nonlocal mouth radiation operator.

This serial SciPy/scikit-fem implementation validates the coupled formulation
before the same operator action is distributed through MFEM/MPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import meshio
import numpy as np
from scipy import sparse
from scipy.sparse import linalg as sparse_linalg
from scipy import linalg
from skfem import Basis, BilinearForm, ElementTetP1, asm
from skfem.helpers import dot, grad
from skfem.io import from_meshio

try:
    from .aperture_radiation import RadiationMedium, rayleigh_impedance_matrix
except ImportError:
    from aperture_radiation import RadiationMedium, rayleigh_impedance_matrix


@dataclass
class InteriorFrequencyResult:
    frequency_hz: float
    pressure: np.ndarray
    mouth_nodes: np.ndarray
    mouth_pressure: np.ndarray
    mouth_normal_velocity: np.ndarray
    throat_nodes: np.ndarray
    throat_area_m2: float
    mouth_area_m2: float
    radiated_power_w: float
    relative_residual: float


@BilinearForm
def _stiffness(u, v, _w):
    return dot(grad(u), grad(v))


@BilinearForm
def _mass(u, v, _w):
    return u * v


def _boundary_lumped_weights(mesh, boundary_name: str) -> tuple[np.ndarray, np.ndarray]:
    if not mesh.boundaries or boundary_name not in mesh.boundaries:
        raise ValueError(f"mesh has no '{boundary_name}' boundary")
    facets = mesh.facets[:, mesh.boundaries[boundary_name]].T
    nodes = np.unique(facets)
    local = {int(node): index for index, node in enumerate(nodes)}
    weights = np.zeros(len(nodes), dtype=float)
    for facet in facets:
        points = mesh.p[:, facet].T
        area = 0.5 * np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0]))
        for node in facet:
            weights[local[int(node)]] += area / 3.0
    if np.any(weights <= 0.0):
        raise ValueError(f"'{boundary_name}' contains a zero-area nodal patch")
    return nodes.astype(np.int64), weights


def solve_interior_frequency(mesh_path: Path, frequency_hz: float,
                             volume_velocity_m3_s: complex = 1.0 + 0.0j,
                             medium: RadiationMedium = RadiationMedium()) -> InteriorFrequencyResult:
    """Solve one P1 reference problem with an infinite-baffle mouth operator."""
    if frequency_hz <= 0.0:
        raise ValueError("frequency must be positive")
    mesh = from_meshio(meshio.read(mesh_path))
    basis = Basis(mesh, ElementTetP1())
    stiffness = asm(_stiffness, basis).astype(np.complex128)
    mass = asm(_mass, basis).astype(np.complex128)
    omega = 2.0 * math.pi * frequency_hz
    wave_number = omega / medium.sound_speed_m_s
    system = (stiffness - wave_number * wave_number * mass).tolil()

    mouth_nodes, mouth_weights = _boundary_lumped_weights(mesh, "mouth")
    mouth_points = mesh.p[:, mouth_nodes].T
    impedance = rayleigh_impedance_matrix(mouth_points, mouth_weights,
                                          frequency_hz, medium)
    pressure_to_velocity = linalg.solve(
        impedance, np.eye(len(mouth_nodes), dtype=np.complex128),
        assume_a="gen", check_finite=True)
    mouth_block = (1j * omega * medium.density_kg_m3) * (
        mouth_weights[:, None] * pressure_to_velocity)
    rows, columns = np.meshgrid(mouth_nodes, mouth_nodes, indexing="ij")
    system += sparse.coo_matrix(
        (mouth_block.ravel(), (rows.ravel(), columns.ravel())),
        shape=system.shape).tolil()
    system = system.tocsr()

    throat_nodes, throat_weights = _boundary_lumped_weights(mesh, "throat")
    throat_area = float(throat_weights.sum())
    # Outward fluid normal is -z; positive Q into the horn gives v_n=-Q/A.
    throat_normal_velocity = -volume_velocity_m3_s / throat_area
    prescribed_derivative = -1j * omega * medium.density_kg_m3 * throat_normal_velocity
    right_hand_side = np.zeros(basis.N, dtype=np.complex128)
    right_hand_side[throat_nodes] += prescribed_derivative * throat_weights

    pressure = sparse_linalg.spsolve(system, right_hand_side)
    mouth_pressure = pressure[mouth_nodes]
    mouth_velocity = pressure_to_velocity @ mouth_pressure
    residual = system @ pressure - right_hand_side
    relative_residual = float(np.linalg.norm(residual) /
                              max(np.linalg.norm(right_hand_side), 1e-30))
    radiated_power = 0.5 * float(np.real(np.sum(
        mouth_weights * mouth_pressure * np.conj(mouth_velocity))))
    return InteriorFrequencyResult(
        frequency_hz, pressure, mouth_nodes, mouth_pressure, mouth_velocity,
        throat_nodes, throat_area, float(mouth_weights.sum()), radiated_power,
        relative_residual)

