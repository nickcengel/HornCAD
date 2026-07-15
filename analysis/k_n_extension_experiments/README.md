# K/N and Conical-Extension FEM Experiments

This study compares eight equal-horizontal/vertical OSSE horns with the current
positive-X/positive-Y interior FEM model. All candidates use a 12.7 mm throat
radius, 6° throat angle, 400 × 400 mm mouth, 60 mm biaxial mouth sag, and the
standard 0.72 mouth-squareness morph. The reduced acoustic model consists of the
internal rigid surface, driven throat, and nonlocal ideal-baffle mouth aperture.

The meshes use the accepted 8-elements-per-wavelength tier at 5 kHz. The sweep
contains 64 logarithmically spaced frequencies from 500 Hz to 5 kHz. Coverage
is calculated from the solved complex mouth velocity; it excludes exterior lip
diffraction.

## Comparison plots

- [Candidates 1–6 coverage](candidates_1_6_coverage_comparison.png)
- [Candidates 1–6 impedance magnitude](candidates_1_6_impedance_comparison.png)
- [Candidates 7–8 coverage](candidates_7_8_coverage_comparison.png)
- [Candidates 7–8 impedance magnitude](candidates_7_8_impedance_comparison.png)
- [Candidates 2, 3, and 5 smoothed coverage trends](candidates_2_3_5_coverage_smoothed.png)

Each `candidate_N` directory contains its authored HornCAD YAML, mesh audit,
compact response array, coverage heatmaps, and magnitude-only throat-impedance
plot. `metrics.csv` contains the extracted impedance and −6 dB half-angle
values for all candidates and frequencies. The reproducible raw field CSVs and
volume meshes are retained locally but ignored by Git because they exceed 1 GB.

Run the resumable workflow from the repository root:

```bash
.venv/bin/python analysis/k_n_extension_experiments/run_study.py setup
.venv/bin/python analysis/k_n_extension_experiments/run_study.py mesh
.venv/bin/python analysis/k_n_extension_experiments/run_study.py solve
.venv/bin/python analysis/k_n_extension_experiments/run_study.py plot
```
