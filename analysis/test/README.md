# HornCAD FEM Test

This directory contains the requested surface STL and the current reduced
interior FEM suite for `HornCAD-Surface-400x260x270(2).YAML`.

The FEM model uses the positive-X/positive-Y symmetry quadrant, rigid internal
wall, driven throat, and nonlocal ideal-baffle mouth aperture. The mesh enforces
eight elements per wavelength at 5 kHz. The sweep contains 64 logarithmically
spaced frequencies from 500 Hz to 5 kHz.

Review outputs:

- [Coverage heatmaps](figures/coverage_heatmaps.png)
- [Throat impedance magnitude](figures/throat_impedance_magnitude.png)
- [Solver performance](figures/solver_performance.png)
- `metrics.csv`: impedance, power, −6 dB half-angles, and solver metrics
- `responses.npz`: compact complex impedance and H/V coverage arrays
- `fields/`: locally retained solved complex mouth and throat fields (ignored by Git)
- `interior_quadrant_5khz_8ppw.msh`: locally retained acoustic volume mesh (ignored by Git)
- `HornCAD-Surface-400x260x270.STL`: requested open acoustic surface STL

Coverage uses the solved mouth velocity with ideal-baffle radiation and does
not include exterior lip diffraction.

Regenerate the standard figures and compact data with the shared tool:

```bash
python app/generate_fem_review.py analysis/test/fields \
  --output-dir analysis/test --title "400 × 260 test horn"
```
