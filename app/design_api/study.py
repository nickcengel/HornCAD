"""Read-only access to a study's authoritative planning artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Study:
    root: Path
    manifest: dict[str, Any]
    execution_plan: dict[str, Any] | None

    @classmethod
    def open(cls, root: str | Path) -> Study:
        root = Path(root)
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"study manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text())
        execution_path = root / "execution_plan.json"
        execution_plan = (
            json.loads(execution_path.read_text())
            if execution_path.is_file() else None
        )
        return cls(root=root, manifest=manifest, execution_plan=execution_plan)

    @property
    def study_id(self) -> str:
        return str(self.manifest.get("study_id", self.root.name))

    def assemble_dataset(self, *, role: str = "fit") -> None:
        """Assemble rescored model inputs once the fitting pipeline lands."""
        if role not in {"fit", "locked_validation", "benchmark", "all"}:
            raise ValueError(f"unknown dataset role: {role}")
        raise NotImplementedError(
            "dataset assembly is specified in model_pipeline.md but not yet implemented")
