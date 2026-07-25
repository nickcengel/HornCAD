from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class OptimizerDocumentationTests(unittest.TestCase):
    def test_one_active_optimizer_authority_and_archived_predecessors(self):
        authority = ROOT / "docs/plans/design_recommendation_map.md"
        self.assertTrue(authority.is_file())
        document = authority.read_text(encoding="utf-8")
        self.assertIn("single active authority", document)
        self.assertIn("horn_optimizer", document)
        self.assertTrue((
            ROOT / "docs/archive/pre-horn-optimizer-2026-07/plans"
            / "design_recommendation_map.md"
        ).is_file())
        self.assertFalse((
            ROOT / "docs/plans/frequency_energy_bunching_analysis.md"
        ).exists())
        self.assertTrue((
            ROOT / "docs/archive/pre-horn-optimizer-2026-07/plans"
            / "frequency_energy_bunching_analysis.md"
        ).is_file())

    def test_active_index_and_examples_link_to_optimizer(self):
        index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        example = ROOT / "examples/horn-optimizer/example.yaml"
        self.assertIn(
            "[Measured BEM horn optimizer](plans/design_recommendation_map.md)",
            index,
        )
        self.assertIn("run_horn_optimizer", readme)
        self.assertTrue(example.is_file())

    def test_low_level_search_and_portable_api_are_not_competing_optimizers(self):
        search = (
            ROOT / "docs/reference/bem_candidate_search.md"
        ).read_text(encoding="utf-8")
        api = (
            ROOT / "docs/reference/design_application_api.md"
        ).read_text(encoding="utf-8")
        pipeline = (
            ROOT / "examples/control-decoupling/model_pipeline.md"
        ).read_text(encoding="utf-8")
        self.assertIn("is not the measured horn optimizer", search)
        self.assertIn("not alternate implementations", api)
        self.assertIn("not\nalternate optimizer implementations", pipeline)


if __name__ == "__main__":
    unittest.main()
