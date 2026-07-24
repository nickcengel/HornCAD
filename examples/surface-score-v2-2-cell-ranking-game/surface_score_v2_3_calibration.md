# Surface score v2.3 calibration

Status: experimental, calibrated, not independently validated

V2.3 preserves v2.2 as the broad-quality baseline and adds a guarded
local-ranking refinement. It is emitted side by side and does not replace the
primary v1 search score.

## Frozen formula

`v2.3 = 0.80 * v2.2 + 0.20 * guarded_core`

Local-core weights:

| Component | Weight |
| --- | ---: |
| Profile RMS | 40.8608% |
| Slice-energy stability | 29.3908% |
| Full-band -6 dB target | 10.7227% |
| Three-contour beamwidth | 19.0257% |

The local branch receives full credit at or above
75% mean containment and
60% outward-rise score.
Below those floors it is multiplied by containment ratio exponent
1 and outward-rise ratio exponent
0.125.

## Ranking evidence

| Population | V2.2 rho | V2.3 rho | V2.2 pairs | V2.3 pairs | V2.2 top | V2.3 top |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Broad rounds | 0.902 | 0.898 | 89.1% | 88.7% | 6 | 6 |
| Close-score rounds | 0.402 | 0.491 | 66.7% | 70.0% | 6 | 5 |
| Per-cell rankings | 0.546 | 0.579 | 70.8% | 72.5% | 8 | 8 |

Whole-cell leave-one-out fitting gives v2.3 mean per-cell rho
0.576.
Nested broad-round guardrail selection gives mean broad rho
0.898.

## Paired uncertainty

| Population | Mean rho change | Whole-group bootstrap 95% interval |
| --- | ---: | ---: |
| Broad rounds | -0.004 | -0.018 to +0.010 |
| Close-score rounds | +0.088 | +0.008 to +0.188 |
| Per-cell rankings | +0.033 | +0.013 to +0.055 |

## Guardrail activity

| Population | Candidates triggering either guardrail |
| --- | ---: |
| Broad rounds | 19 / 100 |
| Close-score rounds | 24 / 100 |
| Per-cell rankings | 3 / 250 |

## Interpretation

The broad difference is consistent with no change. Close-score and per-cell
ordering improve on the completed evidence. These are calibration results, not
new blinded validation, because the same ranking programs informed component
or parameter selection.

See [`docs/plans/surface_diagnostic_v2_3.md`](../../docs/plans/surface_diagnostic_v2_3.md)
for the design, selection constraints, semantics, and release policy.
