"""Fit and freeze the canonical-only round-control primary model."""
from .round_control_model import fit_primary


def main() -> None:
    model = fit_primary()
    print(model["model_id"], model["model_sha256"])


if __name__ == "__main__":
    main()
