# HornCAD FEM Test 4

This directory contains the reduced interior FEM suite for
`HornCAD-Body-400x280x300.YAML`.

The acoustic model uses the positive-X/positive-Y symmetry quadrant, rigid
internal wall, driven throat, and nonlocal ideal-baffle mouth aperture. The
mesh enforces eight elements per wavelength at 5 kHz. The sweep contains 41
logarithmically spaced frequencies from 500 Hz to 5 kHz: 40 intervals across
3.322 octaves, or 12.04 intervals per octave. All 41 frequencies converged.

Review outputs:

- `figures/coverage_heatmaps.png`: horizontal and vertical coverage
- `figures/throat_impedance_magnitude.png`: magnitude-only throat impedance
- `figures/solver_performance.png`: iterations and solve time
- `metrics.csv`: impedance, power, −6 dB half-angles, and solver metrics
- `responses.npz`: compact complex impedance and H/V coverage arrays
- `mesh_report.json`: accepted volume-mesh resolution and size
- `HornCAD-Surface-400x280x300.STL`: open acoustic surface generated from the YAML

The raw field CSVs and volume mesh are retained locally and ignored by Git.
Coverage uses ideal-baffle radiation from the solved mouth velocity and does not
include exterior lip diffraction.
