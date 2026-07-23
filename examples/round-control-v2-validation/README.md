# Unified round-control v2 validation result

This completed study tested whether one globally weighted ten-term quadratic
could replace the primary/augmented v1 pair over the complete 5×5
mouth-diameter/coverage grid.

The frozen candidate JSON predates the terminology cleanup and contains the
legacy descriptive phrase `round symmetric square`. In that frozen metadata,
`square` meant equal H/V dimensions; every geometry in this study is an
axisymmetric round mouth with `mouth_squareness = 0`.

## Outcome

No `round_control_v2` model was released.

Five candidate models were frozen before new outcomes existed. Deterministic
coordinate-grouped cross-validation selected global historical weight 0.25.
Twelve new locked axisymmetric round-mouth BEM cases then covered every
registered mouth diameter and coverage level.

The selected candidate failed the registered release gates:

| Metric | Observed | Limit |
|---|---:|---:|
| Surface-score MAE | 3.4703 | 1.75 |
| Surface-score p90 absolute error | 4.6665 | 3.60 |
| Mean-containment p90 error | 0.2253 | 0.12 |
| −6 dB RMS p90 error | 1.0521 | 0.80 |
| Outward-rise p90 error | 1.1241 | 0.45 |
| Profile-RMS p90 error | 0.3102 | 0.18 |
| Slice-energy p90 error | 0.4438 | 0.18 |

The largest surface-score miss was the valid but evidence-sparse
30°/350 mm, L-factor 1.14, K 2.5, N 14 case: observed 50.036 versus predicted
64.151. Nearby high-length/low-K canonical factorial corners had been
geometry-rejected, so the old rectangular L/K/N support box overstated the
actual joint evidence support.

All other frozen historical weights also failed. The fresh outcomes were not
used to switch candidates or refit, and throat impedance did not participate in
selection or surface score.

The current experimental throat-impedance diagnostic was nevertheless retained
and evaluated for future throat-angle and extension work. For the selected
candidate its fresh-validation score error had MAE 1.8216 and p90 absolute error
2.9905 points. The 50°/400 mm recovery-mesh case was the main impedance outlier
at 9.9702 points; this diagnostic remains provisional and independent of the
radiation surface score.

## Production decision

`round_control_primary_v1` was retained temporarily as the sole round baseline.
A subsequent frozen nonlinear test was also worse on these challenge cases, so
primary v1 is now classified as an API-compatible legacy reference estimator,
not a validated global surrogate. `round_control_augmented_v1` remains research
comparison evidence.

The full 30–50° and 250–450 mm mouth-diameter grid remains of interest.
Predictions in jointly sparse L/K/N regions must be labeled limited-support
even when their individual controls lie inside nominal one-dimensional bounds.

The twelve retained NPZ archives are authoritative challenge evidence for any
future nonlinear round-model version. Such a version must use a new locked
validation set.

## Evidence

- `manifest.json`: outcome-free candidate and coordinate freeze.
- `validation_results.json`: all frozen-candidate errors and release checks.
- `runtime_state.json`: completed two-slot execution ledger.
- `searches/`: project YAML, STL, reports, diagnostic JSON, and retained NPZ.

The 50°/400 mm case required the documented recovery mesh policy after a native
worker abort. Its fixed geometry, frequency grid, wavelength resolution, and
diagnostic evaluation were unchanged.
