from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.aperture_field import (
    ApertureField,
    RADIATION_MODEL,
    TIME_CONVENTION,
    normalized_level_db,
    plane_directions,
    rayleigh_baffle_plane_level,
    rayleigh_baffle_pressure,
    read_mfem_mouth_csv,
)


class ApertureFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.field = ApertureField(
            frequency_hz=1_000.0,
            positions_m=np.array([[-0.05, 0.0, -0.01], [0.05, 0.0, 0.01]]),
            area_weights_m2=np.array([0.01, 0.02]),
            normal_velocity_m_s=np.array([1.0 + 0.5j, 0.75 - 0.25j]),
            pressure_pa=np.array([2.0 + 1.0j, 3.0 - 1.0j]),
        )

    def test_rayleigh_pressure_matches_explicit_kernel(self) -> None:
        observers = np.array([[0.0, 0.0, 10.0], [1.0, 0.0, 9.0]])
        actual = rayleigh_baffle_pressure(self.field, observers)
        distance = np.linalg.norm(
            observers[:, None, :] - self.field.positions_m[None, :, :], axis=2
        )
        omega = 2.0 * np.pi * self.field.frequency_hz
        expected = 1j * 1.2041 * omega / (2.0 * np.pi) * np.sum(
            self.field.normal_velocity_m_s[None, :]
            * self.field.area_weights_m2[None, :]
            * np.exp(-1j * omega / 343.21 * distance) / distance,
            axis=1,
        )
        np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-13)

    def test_plane_level_reproduces_legacy_peak_normalization(self) -> None:
        angles = np.arange(-90.0, 91.0)
        directions = plane_directions(angles, "horizontal")
        observers = self.field.center_m + 10.0 * directions
        distance = np.linalg.norm(
            observers[:, None, :] - self.field.positions_m[None, :, :], axis=2
        )
        k = 2.0 * np.pi * self.field.frequency_hz / 343.21
        legacy = np.sum(
            self.field.normal_velocity_m_s[None, :]
            * self.field.area_weights_m2[None, :]
            * np.exp(-1j * k * distance) / distance,
            axis=1,
        )
        expected = 20.0 * np.log10(
            np.maximum(np.abs(legacy) / np.max(np.abs(legacy)), 1e-9)
        )
        expected = np.maximum(expected, -30.0)
        actual = rayleigh_baffle_plane_level(self.field, angles, "horizontal")
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=2e-13)

    def test_peak_and_on_axis_normalization_are_explicit(self) -> None:
        pressure = np.array([2.0 + 0j, 1.0 + 0j])
        np.testing.assert_allclose(normalized_level_db(pressure), [0.0, -6.020599913])
        np.testing.assert_allclose(
            normalized_level_db(pressure, reference="on_axis", on_axis_index=1),
            [6.020599913, 0.0],
        )

    def test_mfem_reader_preserves_complex_fields_without_inventing_normals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mouth.csv"
            path.write_text(
                "x_m,y_m,z_m,area_weight_m2,pressure_real_pa,pressure_imag_pa,"
                "normal_velocity_real_m_s,normal_velocity_imag_m_s\n"
                "0.1,0.2,0.3,0.004,2,-3,4,5\n",
                encoding="utf-8",
            )
            field = read_mfem_mouth_csv(path, 500.0)
        self.assertEqual(field.time_convention, TIME_CONVENTION)
        self.assertIsNone(field.normals)
        self.assertEqual(field.pressure_pa[0], 2.0 - 3.0j)
        self.assertEqual(field.normal_velocity_m_s[0], 4.0 + 5.0j)
        self.assertAlmostEqual(field.area_m2, 0.004)

    def test_invalid_geometry_and_unknown_plane_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            ApertureField(1_000.0, np.zeros((1, 3)), np.array([0.0]),
                          np.array([1.0 + 0j]))
        with self.assertRaisesRegex(ValueError, "plane"):
            plane_directions(np.array([0.0]), "diagonal")

    def test_model_identifier_is_unambiguous(self) -> None:
        self.assertEqual(
            RADIATION_MODEL,
            "rayleigh_infinite_planar_baffle_curved_source_coordinates",
        )


if __name__ == "__main__":
    unittest.main()
