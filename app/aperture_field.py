"""Shared complex mouth fields and explicit Rayleigh-baffle radiation.

The current reduced FEM uses the ``exp(+i omega t)`` convention and an
infinite-planar-baffle Rayleigh impedance at its computational mouth.  This
module makes the matching review calculation explicit and reusable.  Source
coordinates may be nonplanar, but that does not turn the formulation into a
curved or spherical baffle model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np


TIME_CONVENTION = "exp(+i omega t)"
RADIATION_MODEL = "rayleigh_infinite_planar_baffle_curved_source_coordinates"
FREE_FIELD_MODEL = "free_field_monopole_sheet_curved_source_coordinates"


@dataclass(frozen=True)
class ApertureField:
    """One frequency of area-weighted complex data on a mouth surface."""

    frequency_hz: float
    positions_m: np.ndarray
    area_weights_m2: np.ndarray
    normal_velocity_m_s: np.ndarray
    pressure_pa: np.ndarray | None = None
    normals: np.ndarray | None = None
    time_convention: str = TIME_CONVENTION

    def __post_init__(self) -> None:
        positions = np.asarray(self.positions_m, dtype=float)
        weights = np.asarray(self.area_weights_m2, dtype=float)
        velocity = np.asarray(self.normal_velocity_m_s, dtype=np.complex128)
        if self.frequency_hz <= 0.0:
            raise ValueError("aperture frequency must be positive")
        if positions.ndim != 2 or positions.shape[1] != 3 or len(positions) == 0:
            raise ValueError("aperture positions must be a nonempty Nx3 array")
        if weights.shape != (len(positions),) or velocity.shape != (len(positions),):
            raise ValueError("aperture weights and velocity must match the positions")
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(weights)):
            raise ValueError("aperture geometry must be finite")
        if not np.all(np.isfinite(velocity.real)) or not np.all(np.isfinite(velocity.imag)):
            raise ValueError("aperture velocity must be finite")
        if np.any(weights <= 0.0):
            raise ValueError("aperture area weights must be positive")
        if self.time_convention != TIME_CONVENTION:
            raise ValueError(f"unsupported time convention: {self.time_convention}")
        pressure = self.pressure_pa
        if pressure is not None:
            pressure = np.asarray(pressure, dtype=np.complex128)
            if pressure.shape != (len(positions),):
                raise ValueError("aperture pressure must match the positions")
            if not np.all(np.isfinite(pressure.real)) or not np.all(np.isfinite(pressure.imag)):
                raise ValueError("aperture pressure must be finite")
        normals = self.normals
        if normals is not None:
            normals = np.asarray(normals, dtype=float)
            if normals.shape != positions.shape or not np.all(np.isfinite(normals)):
                raise ValueError("aperture normals must be a finite Nx3 array")
            lengths = np.linalg.norm(normals, axis=1)
            if not np.allclose(lengths, 1.0, atol=1e-6):
                raise ValueError("aperture normals must be unit vectors")
        object.__setattr__(self, "positions_m", positions)
        object.__setattr__(self, "area_weights_m2", weights)
        object.__setattr__(self, "normal_velocity_m_s", velocity)
        object.__setattr__(self, "pressure_pa", pressure)
        object.__setattr__(self, "normals", normals)

    @property
    def area_m2(self) -> float:
        return float(np.sum(self.area_weights_m2))

    @property
    def center_m(self) -> np.ndarray:
        return np.average(self.positions_m, axis=0, weights=self.area_weights_m2)


def read_mfem_mouth_csv(path: Path, frequency_hz: float) -> ApertureField:
    """Read the current MFEM mouth CSV without inventing missing normals."""
    mouth = np.genfromtxt(path, delimiter=",", names=True, ndmin=1)
    required = {
        "x_m", "y_m", "z_m", "area_weight_m2",
        "pressure_real_pa", "pressure_imag_pa",
        "normal_velocity_real_m_s", "normal_velocity_imag_m_s",
    }
    names = set(mouth.dtype.names or ())
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"MFEM mouth CSV is missing columns: {', '.join(missing)}")
    return ApertureField(
        frequency_hz=float(frequency_hz),
        positions_m=np.column_stack([mouth[name] for name in ("x_m", "y_m", "z_m")]),
        area_weights_m2=mouth["area_weight_m2"],
        pressure_pa=mouth["pressure_real_pa"] + 1j * mouth["pressure_imag_pa"],
        normal_velocity_m_s=(mouth["normal_velocity_real_m_s"]
                             + 1j * mouth["normal_velocity_imag_m_s"]),
    )


def plane_directions(angles_deg: np.ndarray, plane: str) -> np.ndarray:
    """Return unit receiver directions in HornCAD horizontal or vertical planes."""
    radians = np.radians(np.asarray(angles_deg, dtype=float))
    if plane == "horizontal":
        directions = np.column_stack((np.sin(radians), np.zeros_like(radians),
                                      np.cos(radians)))
    elif plane == "vertical":
        directions = np.column_stack((np.zeros_like(radians), np.sin(radians),
                                      np.cos(radians)))
    else:
        raise ValueError("plane must be 'horizontal' or 'vertical'")
    return directions


def rayleigh_baffle_pressure(field: ApertureField, observers_m: np.ndarray, *,
                             density_kg_m3: float = 1.2041,
                             sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Evaluate calibrated Rayleigh pressure at finite-distance observers.

    This is the same infinite-planar-baffle kernel used for the reduced FEM
    mouth load.  Actual 3-D source coordinates are retained.  Surface normals
    do not enter this approximation.
    """
    observers = np.asarray(observers_m, dtype=float)
    if observers.ndim != 2 or observers.shape[1] != 3 or len(observers) == 0:
        raise ValueError("observers must be a nonempty Nx3 array")
    if density_kg_m3 <= 0.0 or sound_speed_m_s <= 0.0:
        raise ValueError("medium properties must be positive")
    separation = observers[:, None, :] - field.positions_m[None, :, :]
    distance = np.linalg.norm(separation, axis=2)
    if np.any(distance == 0.0):
        raise ValueError("Rayleigh observers cannot lie on an aperture sample")
    omega = 2.0 * math.pi * field.frequency_hz
    wave_number = omega / sound_speed_m_s
    integral = np.sum(
        field.normal_velocity_m_s[None, :] * field.area_weights_m2[None, :]
        * np.exp(-1j * wave_number * distance) / distance,
        axis=1,
    )
    return 1j * density_kg_m3 * omega / (2.0 * math.pi) * integral


def free_field_monopole_pressure(field: ApertureField, observers_m: np.ndarray, *,
                                 density_kg_m3: float = 1.2041,
                                 sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Evaluate the free-field monopole-sheet baseline.

    The prescribed velocity-weighted source sheet radiates through the ordinary
    free-space Green function. It is not a rigid zero-thickness screen and has
    no lip boundary or edge diffraction. For the same source field its pressure
    is exactly half the infinite-baffle Rayleigh result.
    """
    return 0.5 * rayleigh_baffle_pressure(
        field, observers_m, density_kg_m3=density_kg_m3,
        sound_speed_m_s=sound_speed_m_s,
    )


def normalized_level_db(pressure: np.ndarray, *, reference: str = "peak",
                        on_axis_index: int | None = None,
                        floor_db: float = -30.0) -> np.ndarray:
    """Normalize complex pressure using an explicitly selected convention."""
    values = np.asarray(pressure, dtype=np.complex128)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("pressure must be a nonempty vector")
    if floor_db >= 0.0:
        raise ValueError("level floor must be negative")
    if reference == "peak":
        scale = float(np.max(np.abs(values)))
    elif reference == "on_axis":
        if on_axis_index is None:
            raise ValueError("on-axis normalization requires an index")
        scale = float(abs(values[on_axis_index]))
    else:
        raise ValueError("reference must be 'peak' or 'on_axis'")
    level = 20.0 * np.log10(np.maximum(np.abs(values) / max(scale, 1e-30), 1e-15))
    return np.maximum(level, floor_db)


def plane_observers(field: ApertureField, angles_deg: np.ndarray, plane: str, *,
                    receiver_radius_m: float = 10.0) -> np.ndarray:
    """Place finite-distance receivers about the area-weighted mouth centre."""
    if receiver_radius_m <= 0.0:
        raise ValueError("receiver radius must be positive")
    angles = np.asarray(angles_deg, dtype=float)
    directions = plane_directions(angles, plane)
    return field.center_m + receiver_radius_m * directions


def rayleigh_baffle_plane_pressure(field: ApertureField, angles_deg: np.ndarray,
                                   plane: str, *, receiver_radius_m: float = 10.0,
                                   density_kg_m3: float = 1.2041,
                                   sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Return calibrated complex pressure for the current Rayleigh reference."""
    observers = plane_observers(field, angles_deg, plane,
                                receiver_radius_m=receiver_radius_m)
    return rayleigh_baffle_pressure(
        field, observers, density_kg_m3=density_kg_m3,
        sound_speed_m_s=sound_speed_m_s,
    )


def free_field_monopole_plane_pressure(
        field: ApertureField, angles_deg: np.ndarray, plane: str, *,
        receiver_radius_m: float = 10.0, density_kg_m3: float = 1.2041,
        sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Return calibrated pressure from the curved free-field monopole sheet."""
    observers = plane_observers(field, angles_deg, plane,
                                receiver_radius_m=receiver_radius_m)
    return free_field_monopole_pressure(
        field, observers, density_kg_m3=density_kg_m3,
        sound_speed_m_s=sound_speed_m_s,
    )


def rayleigh_baffle_plane_level(field: ApertureField, angles_deg: np.ndarray,
                                plane: str, *, receiver_radius_m: float = 10.0,
                                reference: str = "peak",
                                floor_db: float = -30.0,
                                density_kg_m3: float = 1.2041,
                                sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Reproduce the current FEM review coverage with documented conventions."""
    angles = np.asarray(angles_deg, dtype=float)
    pressure = rayleigh_baffle_plane_pressure(
        field, angles, plane, receiver_radius_m=receiver_radius_m,
        density_kg_m3=density_kg_m3, sound_speed_m_s=sound_speed_m_s,
    )
    on_axis = int(np.argmin(np.abs(angles)))
    return normalized_level_db(pressure, reference=reference,
                               on_axis_index=on_axis, floor_db=floor_db)


def free_field_monopole_plane_level(
        field: ApertureField, angles_deg: np.ndarray, plane: str, *,
        receiver_radius_m: float = 10.0, reference: str = "peak",
        floor_db: float = -30.0, density_kg_m3: float = 1.2041,
        sound_speed_m_s: float = 343.21) -> np.ndarray:
    """Normalize the free-field monopole-sheet baseline explicitly."""
    angles = np.asarray(angles_deg, dtype=float)
    pressure = free_field_monopole_plane_pressure(
        field, angles, plane, receiver_radius_m=receiver_radius_m,
        density_kg_m3=density_kg_m3, sound_speed_m_s=sound_speed_m_s,
    )
    on_axis = int(np.argmin(np.abs(angles)))
    return normalized_level_db(pressure, reference=reference,
                               on_axis_index=on_axis, floor_db=floor_db)
