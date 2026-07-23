import json
from pathlib import Path
import tempfile
import unittest

from app.design_api import (
    DesignApplication, DesignConstraints, DesignIntent, DesignPoint, Diagnosis,
    Estimate, ExperimentProposal, Objective, Prediction, Recommendation, Study,
    SupportStatus,
)


class FakeBackend:
    model_id = "test-model"

    def predict(self, design):
        return Prediction(
            design=design,
            diagnostics={"surface_score": Estimate(85.0, 83.0, 87.0)},
            derived_geometry={"s_horizontal": 1.2, "s_vertical": 1.2},
            support=SupportStatus.SUPPORTED,
            model_id=self.model_id,
            nearest_evidence_ids=("coordinate-001",),
        )

    def diagnose(self, design, *, objectives):
        return Diagnosis(
            prediction=self.predict(design),
            issues=("slice energy is bunched",),
            control_sensitivities={"k": {"slice_energy_rms_departure": -0.2}},
        )

    def improve(self, design, *, objectives, constraints, limit):
        return tuple(Recommendation(
            prediction=self.predict(design), expected_deltas={},
            rationale=("test recommendation",),
        ) for _ in range(limit))

    def design(self, intent, *, objectives, constraints, limit):
        design = DesignPoint(
            intent=intent, profile_length_mm=150,
            k_horizontal=4, n_horizontal=8, k_vertical=4, n_vertical=8,
        )
        return self.improve(
            design, objectives=objectives, constraints=constraints, limit=limit)

    def select_experiments(self, intents, *, constraints, budget):
        design = DesignPoint(
            intent=intents[0], profile_length_mm=150,
            k_horizontal=4, n_horizontal=8, k_vertical=4, n_vertical=8,
        )
        return tuple(ExperimentProposal(
            design=design, purpose="reduce interpolation uncertainty",
            acquisition_score=1.0,
        ) for _ in range(budget))


class DesignApiTests(unittest.TestCase):
    def setUp(self):
        self.design = DesignPoint.round(300, 40, 145, 4, 8)
        self.app = DesignApplication(FakeBackend())

    def test_round_constructor_preserves_profile_length_and_axes(self):
        self.assertEqual(self.design.profile_length_mm, 145)
        self.assertEqual(self.design.intent.mouth_width_mm, 300)
        self.assertEqual(self.design.intent.mouth_height_mm, 300)
        self.assertEqual(self.design.k_horizontal, self.design.k_vertical)
        self.assertEqual(self.design.n_horizontal, self.design.n_vertical)

    def test_predict_exposes_score_support_and_derived_s(self):
        result = self.app.predict(self.design)
        self.assertEqual(result.surface_score.mean, 85)
        self.assertEqual(result.support, SupportStatus.SUPPORTED)
        self.assertEqual(result.derived_geometry["s_horizontal"], 1.2)

    def test_decision_calls_return_immutable_results(self):
        objectives = (Objective("slice_energy_rms_departure", "minimize"),)
        self.assertEqual(len(self.app.improve(
            self.design, objectives=objectives, limit=2)), 2)
        self.assertEqual(len(self.app.design(
            DesignIntent.round(350, 45), limit=3)), 3)
        self.assertEqual(len(self.app.select_experiments(
            (DesignIntent.round(300, 40),), budget=4)), 4)

    def test_invalid_coordinates_fail_at_boundary(self):
        with self.assertRaises(ValueError):
            DesignPoint.round(300, 40, -1, 4, 8)
        with self.assertRaises(ValueError):
            DesignConstraints(k=(5, 2))
        with self.assertRaises(ValueError):
            self.app.improve(self.design, limit=0)

    def test_study_reads_authoritative_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({
                "study_id": "round-control-test",
            }))
            study = Study.open(root)
            self.assertEqual(study.study_id, "round-control-test")
            self.assertIsNone(study.execution_plan)


if __name__ == "__main__":
    unittest.main()
