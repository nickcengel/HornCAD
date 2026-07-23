"""Audit and assemble the round-control training index."""
from .round_control_model import assemble_dataset


def main() -> None:
    index = assemble_dataset()
    print(f"assembled {len(index['rows'])} unique source rows")


if __name__ == "__main__":
    main()
