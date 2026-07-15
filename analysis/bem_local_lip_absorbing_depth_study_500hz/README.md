# Absorbing-Closure Local-Lip Study at 500 Hz

This package repeats the 25/50/100 mm local-lip study with a Robin aft closure
of `Z=rho*c`. The physical lip and return surfaces remain rigid. A recorded
1 mm axial source-sheet offset avoids coincidence between point-source samples
and lip vertices.

The termination absorbed positive power at every depth, but the study still
failed retained-depth convergence. This shows that reflection from the aft
closure was not the dominant problem. The two-sided monopole source continues
to illuminate the increasing internal-wall area.

## Start here

- `retained_depth_comparison.png` — H/D/V total-pressure overlays.
- `adjacent_convergence.csv` — complex and normalized changes between depths.
- `depth_metrics.csv` — scattering strength, absorbed power, and DOF counts.
- `study.json` — complete machine-readable result and failed acceptance gate.

## Results

| Depth | Absorbed power | Approximate scattered/incident L2 |
|---:|---:|---:|
| 25 mm | 668 W | 0.138 |
| 50 mm | 601 W | 0.247 |
| 100 mm | 478 W | 0.614 |

The 50-to-100 mm change is 83.2% to 89.9% complex L2 across H/D/V, with a
maximum normalized-pattern change of 3.46 dB. No retained depth is accepted.

Each depth folder contains the exact STL, model manifest, calibrated complex
NPZ fields, and source-only versus source-plus-lip comparison plot.
