from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.tools.run_fem_suite import frequency_grid, find_binary, parse_args, run_settings


class RunFEMSuiteTests(unittest.TestCase):
    def test_default_sweep_ends_at_8000_hz(self) -> None:
        args = parse_args(["horn.yaml", "--output-dir", "results"])
        self.assertEqual(args.start_hz, 500.0)
        self.assertEqual(args.stop_hz, 8_000.0)

    def test_frequency_grid_uses_requested_points_per_octave(self) -> None:
        frequencies = frequency_grid(500.0, 5_000.0, 12.0)
        self.assertEqual(len(frequencies), 41)
        self.assertEqual(frequencies[0], 500.0)
        self.assertEqual(frequencies[-1], 5_000.0)
        actual = (len(frequencies) - 1) / np.log2(frequencies[-1] / frequencies[0])
        self.assertAlmostEqual(actual, 12.0411998266)

    def test_frequency_grid_rejects_invalid_inputs(self) -> None:
        for values in ((0, 5_000, 12), (5_000, 500, 12), (500, 5_000, 0)):
            with self.assertRaises(ValueError):
                frequency_grid(*values)

    def test_find_binary_accepts_explicit_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "solver"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            self.assertEqual(find_binary(binary), binary.resolve())

    def test_run_settings_fingerprints_yaml_and_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            yaml_path = Path(temporary) / "horn.yaml"
            binary = Path(temporary) / "solver"
            yaml_path.write_text("horncad_config: {}\n", encoding="utf-8")
            binary.write_bytes(b"solver")
            args = Namespace(
                yaml=yaml_path, points_per_octave=12.0,
                elements_per_wavelength=8.0, side_samples=32,
                axial_stations=44, tetwild_edge_factor=0.46, mpi_ranks=4)
            frequencies = frequency_grid(500.0, 5_000.0, 12.0)
            settings = run_settings(args, frequencies, binary)
            self.assertEqual(settings["frequency_count"], 41)
            self.assertEqual(settings["solver_mpi_ranks"], 4)
            self.assertAlmostEqual(settings["maximum_edge_m"], 0.00858025)
            self.assertEqual(len(settings["yaml_sha256"]), 64)
            self.assertEqual(len(settings["solver_binary_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
