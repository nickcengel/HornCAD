from __future__ import annotations

import unittest

from app.tools.report_round_control_parameter_maps_v2_1 import render


class RoundControlParameterMapsV21Tests(unittest.TestCase):
    def test_render_includes_absolute_and_delta_maps(self) -> None:
        candidate = {
            "id": "candidate",
            "response_sha256": "a" * 64,
            "report_link": "../candidate/report.html",
            "source_path": "response.npz",
            "length_mm": 100.0,
            "k": 4.0,
            "n": 8.0,
            "s": 0.5,
            "score_v1": 75.0,
            "score_v2_1": 80.0,
        }
        cells = {}
        for mouth in (250, 300, 350, 400, 450):
            for coverage in (30, 35, 40, 45, 50):
                cells[f"{coverage}deg-{mouth}mm"] = {
                    "coverage_deg": coverage,
                    "mouth_mm": mouth,
                    "evidence_count": 12,
                    "v1_winner": candidate,
                    "v2_1_winner": candidate,
                    "v2_1_minus_v1_winner": {
                        "length_mm": 0.0,
                        "k": 0.0,
                        "n": 0.0,
                        "s": 0.0,
                        "score": 5.0,
                    },
                    "winner_changed": False,
                }
        document = render({
            "cells": cells,
            "population_count": 300,
            "sources": [{
                "path": "source.json",
                "sha256": "b" * 64,
            }],
            "content_sha256": "c" * 64,
        })
        self.assertIn("surface score v2.1", document)
        self.assertIn("Per-cell parameter deltas", document)
        self.assertIn("Δ Length", document)
        self.assertIn("Δ K", document)
        self.assertIn("Δ N", document)
        self.assertIn("Δ S", document)
        self.assertIn("Cell-by-cell audit", document)


if __name__ == "__main__":
    unittest.main()
