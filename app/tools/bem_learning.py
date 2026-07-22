"""Load and enforce the versioned BEM study learning ledger."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LEDGER_RELATIVE_PATH = Path("docs/reference/research/bem_learning_ledger.json")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_learning_ledger(root: Path | None = None) -> dict[str, Any]:
    path = (root or repository_root()) / LEDGER_RELATIVE_PATH
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in ledger.get("rules", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("BEM learning ledger contains duplicate rule ids")
    return ledger


def active_rules(root: Path | None = None) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in load_learning_ledger(root).get("rules", [])
        if item.get("status") == "active"
    }


def merged_candidate_policy(root: Path | None = None) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    for rule in active_rules(root).values():
        for key, value in rule.get("apply", {}).items():
            if key in policy and policy[key] != value:
                raise ValueError(f"conflicting active BEM learning rule for {key}")
            policy[key] = value
    return policy


def nominal_candidate_rejections(
        coverage_deg: float, mouth_mm: float, k: float, n: float,
        root: Path | None = None) -> list[str]:
    """Return ledger rules that reject a proposal before expensive geometry/BEM work."""
    rules = active_rules(root)
    policy = merged_candidate_policy(root)
    rejected: list[str] = []
    if coverage_deg not in policy.get("coverage_deg", []):
        rejected.append("study-domain-v1")
    if mouth_mm not in policy.get("mouth_mm", []):
        rejected.append("study-domain-v1")
    k_step = float(policy.get("minimum_k_step", 0.5))
    n_step = float(policy.get("minimum_n_step", 1.0))
    if abs(k / k_step - round(k / k_step)) > 1e-7:
        rejected.append("coarse-control-grid-v1")
    if abs(n / n_step - round(n / n_step)) > 1e-7:
        rejected.append("coarse-control-grid-v1")
    for boundary in policy.get("reject_strata", []):
        below = (k <= boundary.get("maximum_k", k) and
                 n <= boundary.get("maximum_n", n))
        above = (k >= boundary.get("minimum_k", k) and
                 n >= boundary.get("minimum_n", n))
        if ("maximum_k" in boundary and below) or ("minimum_k" in boundary and above):
            rejected.append("remote-extremes-closed-v1")
    return sorted(set(item for item in rejected if item in rules))
