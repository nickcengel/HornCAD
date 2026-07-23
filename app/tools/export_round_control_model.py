"""Fit the post-validation augmented model and export both portable releases."""
from .round_control_model import export_release, fit_augmented


def main() -> None:
    model = fit_augmented()
    export_release()
    print(model["model_id"], model["model_sha256"])


if __name__ == "__main__":
    main()
