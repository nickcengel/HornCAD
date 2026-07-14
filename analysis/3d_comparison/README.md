# Dense 3D / Simplified-Model Comparison

This package compares the wavelength-resolved 3D interior/aperture proof with
the repository's earlier simplified models at the same 81 logarithmically
spaced frequencies from 500 Hz through 5 kHz.

The primary model is the horn's interior air volume with a rigid wall, a unit
volume-velocity throat source, and a computational mouth surface coupled to a
nonlocal infinite-baffle radiation-impedance operator. The impedance baseline
is the lossless one-dimensional Webster model with a baffled-piston load. The
coverage baseline is the uniformly driven curved mouth aperture.

## Review first

![Coverage comparison](figures/coverage_comparison.png)

The coverage plot uses logarithmic frequency on x, human-readable 15-degree
angle ticks on y, and a white -6 dB contour. Both predictions use ideal-baffle
radiation. The 3D result includes the solved nonuniform complex mouth velocity;
the simpler baseline assumes uniform velocity. Neither includes lip diffraction
or exterior-body scattering.

![Impedance comparison](figures/impedance_comparison.png)

Only impedance magnitude is plotted. It is normalized by each model's own
throat characteristic impedance, which avoids confusing the small
mesh/authored throat-area difference with an acoustic-model difference.

![Metrics](figures/metrics.png)

The metrics figure compares -6 dB beamwidth, measures complex mouth-velocity
coherence, and records the solver cost across the sweep.

## Data

- `response_comparison.csv`: matched 3D and Webster impedance/power plus solver metrics.
- `coverage_data.npz`: coverage matrices, beamwidths, and mouth coherence.
- `dense_fields.npz`: compressed complex pressure/velocity fields and solver results.
- `manifest.json`: model definitions and limitations.
- `generate_comparison.py`: regeneration script; its argument is the directory
  containing resumable `d000` through `d080` MFEM field exports.

These results use one accepted 6-elements-per-wavelength mesh. They are useful
for comparison with the earlier methods but are not mesh-convergence certified.
