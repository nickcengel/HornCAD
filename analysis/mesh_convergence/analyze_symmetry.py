"""Record full-domain versus quadrant validation metrics."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from analyze_convergence import beam_metrics, coverage


ROOT = Path(__file__).resolve().parent
POC_FIELDS = ROOT.parent / "3d_poc" / "fields"
FULL_8 = ROOT / "full_reference"
QUADRANT = ROOT / "quadrant_fields"


def load(prefix: Path) -> tuple[np.void, np.ndarray]:
    return (np.genfromtxt(f"{prefix}_summary.csv", delimiter=",", names=True),
            np.genfromtxt(f"{prefix}_mouth.csv", delimiter=",", names=True))


def main() -> None:
    rows = []
    for epw, frequencies in ((6, (500, 5000)), (8, (500, 1000, 2000, 5000))):
        for frequency in frequencies:
            if epw == 6:
                full_prefix = POC_FIELDS / f"f{frequency:04d}"
            else:
                full_prefix = FULL_8 / f"8ppw_f{frequency:04d}"
            quadrant_prefix = QUADRANT / f"{epw}ppw_f{frequency:04d}"
            full_summary, full_mouth = load(full_prefix)
            quadrant_summary, quadrant_mouth = load(quadrant_prefix)
            values = {}
            for name, summary, mouth in (("full", full_summary, full_mouth),
                                         ("quadrant", quadrant_summary, quadrant_mouth)):
                impedance = complex(float(summary["input_impedance_real_pa_s_m3"]),
                                    float(summary["input_impedance_imag_pa_s_m3"]))
                horizontal = coverage(mouth, frequency, "horizontal")
                vertical = coverage(mouth, frequency, "vertical")
                values[name] = {
                    "impedance": abs(impedance), "power": float(summary["radiated_power_w"]),
                    "solve_seconds": float(summary["solve_seconds"]),
                    "horizontal": horizontal, "vertical": vertical,
                    "h_width": beam_metrics(horizontal)[0],
                    "v_width": beam_metrics(vertical)[0],
                }
            full, quadrant = values["full"], values["quadrant"]
            rows.append({
                "elements_per_wavelength": epw, "frequency_hz": frequency,
                "impedance_magnitude_difference_percent":
                    100.0 * (quadrant["impedance"] / full["impedance"] - 1.0),
                "radiated_power_difference_percent":
                    100.0 * (quadrant["power"] / full["power"] - 1.0),
                "horizontal_beamwidth_difference_percent":
                    100.0 * (quadrant["h_width"] / full["h_width"] - 1.0),
                "vertical_beamwidth_difference_percent":
                    100.0 * (quadrant["v_width"] / full["v_width"] - 1.0),
                "horizontal_coverage_rms_difference_db":
                    float(np.sqrt(np.mean((quadrant["horizontal"] - full["horizontal"]) ** 2))),
                "vertical_coverage_rms_difference_db":
                    float(np.sqrt(np.mean((quadrant["vertical"] - full["vertical"]) ** 2))),
                "solver_speedup": full["solve_seconds"] / quadrant["solve_seconds"],
            })
    with (ROOT / "symmetry_validation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
