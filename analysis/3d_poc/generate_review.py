"""Regenerate the review figures from the committed mesh and CSV."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import meshio
import numpy as np


ROOT = Path(__file__).resolve().parent


def response_figure() -> None:
    data = np.genfromtxt(ROOT / "sweep.csv", delimiter=",", names=True)
    figure, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    axes[0].plot(data["frequency_hz"], data["radiated_power_w"] / 1000, "o-")
    axes[0].set_ylabel("Radiated power (kW)\nfor 1 m³/s source")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(data["frequency_hz"], data["gmres_iterations"], "o-", label="iterations")
    axes[1].axhline(1000, color="tab:red", linestyle="--", label="iteration limit")
    axes[1].set(xlabel="Frequency (Hz)", ylabel="GMRES iterations")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    figure.suptitle("Resolved 3D interior/aperture proof — not convergence certified")
    figure.tight_layout()
    figure.savefig(ROOT / "figures" / "resolved_sweep.png", dpi=180)
    plt.close(figure)


def mesh_figure() -> None:
    mesh = meshio.read(ROOT / "artifacts" / "interior_5khz_6ppw.msh")
    triangles = next(block.data for block in mesh.cells if block.type == "triangle")
    tags = next(values for block, values in zip(mesh.cells, mesh.cell_data["gmsh:physical"])
                if block.type == "triangle")
    stride = max(1, len(triangles) // 12000)
    triangles, tags = triangles[::stride], tags[::stride]
    colors = np.array([[0.72, 0.74, 0.78, 0.28], [0.85, 0.20, 0.15, 0.9],
                       [0.15, 0.45, 0.85, 0.8]])
    collection = Poly3DCollection(mesh.points[triangles], facecolors=colors[tags - 1],
                                  edgecolors=(0.15, 0.15, 0.15, 0.08), linewidths=0.15)
    figure = plt.figure(figsize=(9, 6))
    axis = figure.add_subplot(111, projection="3d")
    axis.add_collection3d(collection)
    low, high = mesh.points.min(axis=0), mesh.points.max(axis=0)
    axis.set(xlim=(low[0], high[0]), ylim=(low[1], high[1]), zlim=(low[2], high[2]),
             xlabel="x (m)", ylabel="y (m)", zlabel="z (m)")
    axis.set_box_aspect(high - low)
    axis.view_init(elev=22, azim=-55)
    axis.set_title("Acoustic boundary: wall (gray), throat (red), mouth (blue)")
    figure.tight_layout()
    figure.savefig(ROOT / "figures" / "acoustic_mesh.png", dpi=180)
    plt.close(figure)


if __name__ == "__main__":
    response_figure()
    mesh_figure()
