import base64
import tempfile
from pathlib import Path
import unittest

import numpy as np

from app.tools.generate_surface_score_rank_comparison import (
    HEATMAP_FLOOR_DB,
    HEATMAP_STEP_DB,
    _document,
    _encode_heatmap,
    write,
)


class SurfaceScoreRankComparisonTests(unittest.TestCase):
    @staticmethod
    def artifact():
        grid = {
            "frequencies_hz": [500.0, 1000.0],
            "angles_deg": [0.0, 45.0, 90.0],
            "rows": 2,
            "columns": 3,
        }
        candidates = []
        for index, (v1, v2, mouth, coverage) in enumerate((
            (90.0, 80.0, 250.0, 30.0),
            (80.0, 90.0, 300.0, 40.0),
        )):
            candidates.append({
                "id": f"candidate-{index}",
                "aliases": [f"candidate-{index}"],
                "response_sha256": str(index) * 64,
                "source_path": f"source-{index}.npz",
                "report_link": f"report-{index}.html",
                "provenance": "test",
                "role": "fit",
                "mouth_mm": mouth,
                "coverage_deg": coverage,
                "length_mm": 100.0,
                "k": 4.0,
                "n": 8.0,
                "s": 0.5,
                "score_v1": v1,
                "score_v2": v2,
                "indexed_v1_delta": 0.0,
                "grid_id": "grid",
                "heatmap_b64": _encode_heatmap(np.array([
                    [0.0, -6.0, -12.0],
                    [0.0, -5.0, -10.0],
                ])),
            })
        return {
            "schema_version": 1,
            "study_id": "test",
            "status": "complete",
            "source_index": "index.json",
            "source_index_sha256": "a" * 64,
            "diagnostic_implementation_sha256": "b" * 64,
            "deduplication": "response_sha256",
            "population_count": 2,
            "top_rank_count": 25,
            "quantiles": [0.5],
            "heatmap_encoding": {
                "floor_db": HEATMAP_FLOOR_DB,
                "step_db": HEATMAP_STEP_DB,
                "dtype": "uint8",
                "order": "frequency-major row-major",
            },
            "grids": {"grid": grid},
            "candidates": candidates,
            "content_sha256": "c" * 64,
        }

    def test_heatmap_encoding_is_clipped_and_quarter_db(self):
        encoded = _encode_heatmap(np.array([[-40.0, -6.0, 1.0]]))
        values = np.frombuffer(base64.b64decode(encoded), dtype=np.uint8)
        self.assertEqual(values.tolist(), [0, 96, 120])

    def test_document_has_hold_navigation_quantiles_and_cell_filters(self):
        document = _document(self.artifact())
        self.assertIn("Press and hold the plot for v2", document)
        self.assertIn('id="mouth"', document)
        self.assertIn('id="coverage"', document)
        self.assertIn('id="higher"', document)
        self.assertIn('id="lower"', document)
        self.assertIn("pointercancel", document)
        self.assertIn("lostpointercapture", document)
        self.assertIn("score_v1", document)
        self.assertIn("score_v2", document)
        self.assertIn("−3 dB", document)
        self.assertIn("−6 dB", document)
        self.assertIn("−9 dB", document)
        self.assertIn("Which plot is better?", document)
        self.assertIn('data-choice="plot_1"', document)
        self.assertIn('data-choice="plot_2"', document)
        self.assertIn('data-choice="tie"', document)
        self.assertIn("localStorage.setItem", document)
        self.assertIn("Export selections JSON", document)
        self.assertIn("Import selections JSON", document)
        self.assertIn("artifact_content_sha256", document)

    def test_write_is_deterministic(self):
        artifact = self.artifact()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            json_path, html_path = write(output, artifact)
            first = (json_path.read_bytes(), html_path.read_bytes())
            write(output, artifact)
            second = (json_path.read_bytes(), html_path.read_bytes())
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
