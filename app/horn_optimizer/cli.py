"""Command-line interface for horn_optimizer YAML v1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .optimizer import HornOptimizer
from .schema import load_optimizer_config


def summary(state: dict) -> dict:
    return {
        "status": state["status"],
        "output_dir": state["config"]["output_dir"],
        "next_round": state["next_round"],
        "simulation_accounting": state["accounting"],
        "winner_proposal_hash": state.get("winner_proposal_hash"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "command",
        choices=("init", "status", "propose", "approve", "step", "run",
                 "dry-run", "report"),
    )
    args = parser.parse_args()
    optimizer = HornOptimizer(load_optimizer_config(args.config))
    if args.command == "init":
        state = optimizer.initialize()
    elif args.command == "status":
        state = optimizer.load_state()
    elif args.command == "propose":
        optimizer.propose()
        state = optimizer.load_state()
    elif args.command == "approve":
        approved = optimizer.approve()
        state = optimizer.load_state()
        state = {**state, "approved_candidate_count": approved}
    elif args.command == "step":
        state = optimizer.step()
    elif args.command == "run":
        state = optimizer.run()
    elif args.command == "dry-run":
        state = optimizer.step(dry_run=True)
    else:
        state = optimizer.load_state()
        optimizer.render_report(state)
    print(json.dumps(summary(state), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
