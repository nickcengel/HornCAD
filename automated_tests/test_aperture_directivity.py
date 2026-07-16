import unittest

import numpy as np

from app.tools.aperture_directivity import normalized_plane_directivity


class ApertureDirectivityTests(unittest.TestCase):
    def test_each_frequency_is_normalized_on_axis(self) -> None:
        transverse = np.linspace(-0.1, 0.1, 501)
        axial = np.zeros_like(transverse)
        frequencies = np.array([250.0, 1000.0, 10_000.0])
        angles = np.array([0.0, 30.0, 60.0, 90.0])
        result = normalized_plane_directivity(
            transverse, axial, frequencies, angles, 343.21
        )
        np.testing.assert_allclose(result[0], 0.0, atol=1e-12)
        self.assertTrue(np.all(result <= 1e-12))


if __name__ == "__main__":
    unittest.main()
