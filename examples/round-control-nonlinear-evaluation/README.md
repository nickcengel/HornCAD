# Nonlinear round-surrogate stop result

This simulation-free evaluation asked whether the 1,234 existing unique
development coordinates could support a meaningfully better global round
surrogate than the ten-term quadratic.

Development-only cross-validation selected a quadratic plus Gaussian
radial-basis residual field. Against the unchanged quadratic under identical
folds, it reduced equal-diagnostic normalized error by about 27% and
surface-score MAE by about 26%. The method and selection hash were committed
before the twelve challenge outcomes were loaded.

The locked challenge reversed that result:

| Metric | Nonlinear | Frozen quadratic | Change |
|---|---:|---:|---:|
| Surface-score MAE | 4.5231 | 3.4703 | 30% worse |
| Surface-score p90 absolute error | 7.9009 | 4.6665 | 69% worse |
| Equal-diagnostic normalized MAE | 0.4148 | 0.3763 | 10% worse |

The nonlinear model improved containment, profile-RMS, and −6 dB errors, but
worsened slice-energy and outward-rise errors. Its largest miss remained the
30°/350 mm, L-factor 1.14, K 2.5, N 14 case: observed surface score 50.036,
predicted 71.509.

## Decision

No nonlinear model was released, no challenge-driven retuning was performed,
and no additional round BEM is requested.

The evidence does not support treating any current surrogate as a dependable
interpolating foundation over the full round domain. Primary v1 remains
available as a legacy reference estimator and API compatibility artifact, not a
validated production surrogate. Augmented v1 remains comparison evidence.

Future geometry work must use measured round parents for paired comparisons.
The retained round response archive remains valuable baseline evidence, but
model predictions may be used only for provisional orientation and must not
replace a nearby measured parent.

`development_selection.json` is the outcome-free selection record.
`challenge_results.json` is the locked evaluation and stop decision.
Experimental throat impedance was reported but excluded from selection,
surface score, and release.
