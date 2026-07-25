from pathlib import Path
import tempfile
import unittest

import yaml

from app.horn_optimizer.schema import load_optimizer_config


class HornOptimizerSchemaTests(unittest.TestCase):
    def write(self, root: Path, updates: dict | None = None) -> Path:
        optimizer = {
            "version": 1,
            "output_dir": "run",
            "intent": {
                "horizontal_coverage_deg": 50,
                "vertical_coverage_deg": 35,
            },
            "throat_angle_deg": 6,
            "mouth_shape": "square",
            "mouth": {"width_mm": [380, 420], "aspect_ratio": [1.3, 1.5]},
            "sag_axes": "none",
            "sag_mm": 0,
            "max_simulations": 24,
            "approval_mode": "autonomous",
        }
        if updates:
            optimizer.update(updates)
        path = root / "optimizer.yaml"
        path.write_text(
            yaml.safe_dump({"horn_optimizer": optimizer}, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def test_scalar_and_range_mouth_values_are_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            config = load_optimizer_config(self.write(Path(temp)))
            self.assertEqual(config.mouth.width_mm.as_list(), [380, 420])
            self.assertEqual(config.mouth.dimensions(), (400, 400 / 1.4))
            self.assertEqual(config.sag_mm.as_list(), [0, 0])

    def test_height_and_aspect_ratio_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write(Path(temp), {"mouth": {
                "width_mm": 400, "height_mm": 280, "aspect_ratio": 1.4,
            }})
            with self.assertRaisesRegex(ValueError, "exactly one"):
                load_optimizer_config(path)

    def test_height_mode_and_permitted_sag_range(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write(Path(temp), {
                "mouth": {"width_mm": 400, "height_mm": [260, 300]},
                "sag_axes": "vertical",
                "sag_mm": [0, 20],
            })
            config = load_optimizer_config(path)
            self.assertEqual(config.mouth.dimensions(), (400, 280))
            self.assertEqual(config.sag_axes, "vertical")
            self.assertEqual(config.sag_mm.as_list(), [0, 20])

    def test_fixed_contract_enums_and_hard_cap_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "mouth_shape"):
                load_optimizer_config(self.write(
                    Path(temp), {"mouth_shape": "ellipse"}))
            with self.assertRaisesRegex(ValueError, "max_simulations"):
                load_optimizer_config(self.write(
                    Path(temp), {"max_simulations": 0}))
            with self.assertRaisesRegex(ValueError, "integer"):
                load_optimizer_config(self.write(
                    Path(temp), {"max_simulations": 3.5}))
            with self.assertRaisesRegex(ValueError, "true or false"):
                load_optimizer_config(self.write(
                    Path(temp), {"ranking": {"enabled": "false"}}))


if __name__ == "__main__":
    unittest.main()
