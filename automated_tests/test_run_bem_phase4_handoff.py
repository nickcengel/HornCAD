from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.tools.run_bem_phase4_handoff import batch_one_handoff_ready


class BemPhaseFourHandoffTests(unittest.TestCase):
    def test_handoff_requires_published_batch_two_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "domain_mapping_state.json"
            state.write_text(json.dumps({"phase": "domain-map-batch-1"}))
            self.assertFalse(batch_one_handoff_ready(root))
            state.write_text(json.dumps({"phase": "domain-map-batch-2"}))
            self.assertTrue(batch_one_handoff_ready(root))


if __name__ == "__main__":
    unittest.main()
