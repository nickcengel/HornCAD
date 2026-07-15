#!/usr/bin/env python3
"""Plot FEM and NumCalc coverage together on identical axes."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter, ScalarFormatter
import numpy as np


def _load(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    data = np.load(path, allow_pickle=False)
    return (np.asarray(data["frequencies_hz"], dtype=float),
            np.asarray(data["angles_deg"], dtype=float),
            {name: np.asarray(data[f"{name}_db"], dtype=float)
             for name in ("horizontal", "vertical")})


def compare(fem_path: Path, bem_path: Path, output_path: Path) -> None:
    fem_frequency, fem_angles, fem = _load(fem_path)
    bem_frequency, bem_angles, bem = _load(bem_path)
    if not (np.isclose(fem_frequency[0], bem_frequency[0]) and
            np.isclose(fem_frequency[-1], bem_frequency[-1])):
        raise ValueError("FEM and BEM frequency bounds must match")
    if not np.allclose(fem_angles, bem_angles):
        raise ValueError("FEM and BEM angle grids must match")

    figure, axes = plt.subplots(2, 2, figsize=(13, 10), sharex=True, sharey=True,
                               constrained_layout=True)
    image = None
    rows = (("FEM — ideal-baffle mouth radiation", fem_frequency, fem),
            ("All BEM — free-air exterior with lip", bem_frequency, bem))
    for row_index, (model, frequencies, cuts) in enumerate(rows):
        for column_index, plane in enumerate(("horizontal", "vertical")):
            axis = axes[row_index, column_index]
            values = cuts[plane]
            image = axis.pcolormesh(frequencies, fem_angles, values.T,
                                    shading="nearest", vmin=-30, vmax=0, cmap="turbo")
            axis.contour(frequencies, fem_angles, values.T, levels=[-6],
                         colors="white", linewidths=1.5)
            axis.set_xscale("log")
            axis.set_xticks([500, 1000, 2000, 5000])
            axis.xaxis.set_major_formatter(ScalarFormatter())
            axis.xaxis.set_minor_formatter(NullFormatter())
            axis.set_yticks(np.arange(-90, 91, 15))
            axis.grid(True, which="both", alpha=.18)
            axis.set_title(f"{model}\n{plane.capitalize()}")
    axes[1, 0].set_xlabel("Frequency (Hz, log scale)")
    axes[1, 1].set_xlabel("Frequency (Hz, log scale)")
    axes[0, 0].set_ylabel("Off-axis angle (degrees)")
    axes[1, 0].set_ylabel("Off-axis angle (degrees)")
    figure.colorbar(image, ax=axes, label="Level relative to on-axis (dB)")
    figure.suptitle("Test4 coverage comparison — FEM versus all BEM", fontsize=16)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fem_responses", type=Path)
    parser.add_argument("bem_responses", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    compare(args.fem_responses, args.bem_responses, args.output)


if __name__ == "__main__":
    main()
