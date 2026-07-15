# Local-Lip BEM Retained-Depth Study at 500 Hz

This package contains the one-way 25/50/100 mm retained-depth study discussed
in `tests/bem_plan.md`. It uses the accepted test4 FEM mouth field at 500 Hz as
a prescribed curved free-field monopole sheet and solves rigid scattering from
each closed local-lip solid at six elements per wavelength.

This study is diagnostic, not an accepted free-air result. It failed retained-
depth convergence. The two-sided monopole sheet radiates aft into the retained
inner wall and numerical rear closure, so increasing retained depth changes the
mathematical problem substantially.

## Start here

- `local_lip_meshes.png` shows the three exact scattering meshes side by side;
  blue is retained body and red is the artificial rear closure.
- `retained_depth_comparison.png` overlays peak-normalized total H/D/V pressure
  for all three depths.
- `adjacent_convergence.csv` contains the 25-to-50 and 50-to-100 mm complex and
  normalized-pattern changes.
- `depth_metrics.csv` contains DOF count, scattering strength, and beamwidth for
  each depth.
- `study.json` is the machine-readable study summary.

## Per-depth folders

Each `depth_<N>mm/` directory contains:

- `local_lip.stl` — the exact watertight scattering solid;
- `local_lip_comparison.png` — source-only versus source-plus-lip H/D/V cuts;
- `manifest.json` — geometry, mesh, source, and solver provenance;
- `responses.npz` — calibrated complex incident, scattered, total, and lip-
  difference pressure arrays.

## Main result

| Adjacent depths | Complex L2 change across H/D/V | Maximum normalized change |
|---|---:|---:|
| 25 to 50 mm | 14.3% to 15.3% | 0.255 dB |
| 50 to 100 mm | 85.2% to 89.7% | 3.58 dB |

Scattered-to-incident L2 strength increased from approximately 0.11 at 25 mm,
to 0.23 at 50 mm, to 0.61 at 100 mm. No retained depth is accepted.

The next production-oriented formulation should replace the two-sided source
sheet with a justified one-sided representation or, preferably, a coupled
FEM--BEM mouth interface before repeating this convergence study.
