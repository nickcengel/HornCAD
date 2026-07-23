"""Reveal locked/historical outcomes and validate the frozen primary model."""
from .round_control_model import validate_primary


def main() -> None:
    validation = validate_primary()
    print(f"validated {validation['locked']['count']} locked and "
          f"{validation['historical_challenge']['count']} historical responses")


if __name__ == "__main__":
    main()
