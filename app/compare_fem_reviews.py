"""Compare two or more compact HornCAD FEM review packages."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np


def log_axis(axis: plt.Axes) -> None:
    axis.set_xscale("log")
    axis.set_xticks([500, 1000, 2000, 5000])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.grid(True, which="both", alpha=0.2)


def load_review(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    responses = np.load(path / "responses.npz")
    metrics = np.genfromtxt(path / "metrics.csv", delimiter=",", names=True)
    frequencies = np.asarray(responses["frequencies_hz"], dtype=float)
    metric_frequencies = np.asarray(metrics["frequency_hz"], dtype=float)
    if not np.allclose(frequencies, metric_frequencies):
        raise ValueError(f"frequency mismatch within review package {path}")
    return (
        frequencies,
        np.asarray(metrics["horizontal_6db_half_angle_deg"], dtype=float),
        np.asarray(metrics["vertical_6db_half_angle_deg"], dtype=float),
        np.abs(np.asarray(responses["impedance"])),
    )


def compare(paths: list[Path], labels: list[str], output_dir: Path) -> None:
    if len(paths) < 2 or len(paths) != len(labels):
        raise ValueError("provide at least two review paths and one label per path")
    reviews = [load_review(path) for path in paths]
    reference = reviews[0][0]
    if any(not np.allclose(review[0], reference) for review in reviews[1:]):
        raise ValueError("review packages must use the same frequency grid")
    output_dir.mkdir(parents=True, exist_ok=True)

    figure, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True,
                               constrained_layout=True)
    for label, (frequencies, horizontal, vertical, _) in zip(labels, reviews):
        axes[0].plot(frequencies, horizontal, linewidth=1.8, label=label)
        axes[1].plot(frequencies, vertical, linewidth=1.8, label=label)
    for axis, plane in zip(axes, ("Horizontal", "Vertical")):
        axis.set_title(plane)
        axis.set_xlabel("Frequency (Hz, log scale)")
        axis.set_ylim(0, 90)
        axis.set_yticks(np.arange(0, 91, 15))
        log_axis(axis)
    axes[0].set_ylabel("−6 dB half-angle (degrees)")
    axes[1].legend()
    figure.suptitle("FEM ideal-baffle coverage comparison")
    figure.savefig(output_dir / "coverage_comparison.png", dpi=180,
                   bbox_inches="tight")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 5), constrained_layout=True)
    for label, (frequencies, _, _, impedance) in zip(labels, reviews):
        axis.plot(frequencies, impedance, linewidth=1.8, label=label)
    axis.set(xlabel="Frequency (Hz, log scale)",
             ylabel="Magnitude (Pa·s/m³)",
             title="FEM throat acoustic impedance magnitude comparison")
    axis.legend()
    log_axis(axis)
    figure.savefig(output_dir / "throat_impedance_comparison.png", dpi=180)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", nargs="+", type=Path,
                        help="Directories containing responses.npz and metrics.csv")
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compare(args.reviews, args.labels, args.output_dir)


if __name__ == "__main__":
    main()
