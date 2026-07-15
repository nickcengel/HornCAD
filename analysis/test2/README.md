# HornCAD FEM Test 2

This directory contains the current reduced interior FEM suite for
`HornCAD-Surface-400x260x300.YAML`, plus direct comparisons with `analysis/test`.

The run uses the positive-X/positive-Y symmetry quadrant, rigid internal wall,
driven throat, nonlocal ideal-baffle mouth aperture, eight elements per
wavelength at 5 kHz, and 64 logarithmically spaced frequencies from 500 Hz to
5 kHz. All 64 frequencies converged.

Review outputs:

- `figures/coverage_heatmaps.png`: test2 horizontal and vertical coverage
- `figures/throat_impedance_magnitude.png`: test2 impedance magnitude
- `figures/solver_performance.png`: test2 solver cost
- `figures/coverage_comparison.png`: test versus test2 −6 dB half-angle
- `figures/throat_impedance_comparison.png`: test versus test2 impedance magnitude
- `metrics.csv`: compact scalar metrics
- `responses.npz`: compact complex impedance and H/V coverage arrays
- `mesh_report.json`: accepted volume-mesh resolution and size

The raw field CSVs and volume mesh are retained locally and ignored by Git.
Coverage uses ideal-baffle radiation from the solved mouth velocity and does not
include exterior lip diffraction.
