# Surface diagnostic v2.3: general-purpose guarded refinement

Status: implemented and calibrated on all existing ranking evidence; experimental
and not independently validated; v1 remains the primary search score

## Problem

The v2.2 diagnostic preserves broad quality discrimination and coverage-target
behavior, but its ordering among the ten high-scoring candidates in each
mouth/coverage cell is weaker than the four-component weight fit derived from
the completed per-cell ranking game. That local fit cannot be used directly as
a general score: containment and outward-rise receive zero weight in the
already-good pool, and the resulting formula loses broad-range agreement.

V2.3 therefore does not replace v2.2 with the local fit. It treats the two
results as complementary:

- v2.2 remains the broad-quality baseline, including its coverage-dependent
  mixture of window containment, outward-rise, target accuracy, profile,
  energy, and multiscale contour quality;
- a small local-ranking branch refines acceptable candidates;
- explicit one-sided guardrails reduce that branch when containment or
  outward-rise quality falls below an acceptable floor.

Throat impedance remains a separate diagnostic and does not contribute to this
surface score.

## Frozen formula

The local core is an arithmetic score with weights fitted by nonnegative
pairwise logistic regression on the 25 completed per-cell rankings:

| Component | Weight |
| --- | ---: |
| In-window profile RMS | 40.8608% |
| Slice-energy stability | 29.3908% |
| Full-band -6 dB target accuracy | 10.7227% |
| Three-contour beamwidth quality | 19.0257% |

For each plane, define:

`containment_factor = min(1, containment_percent / 75) ** 1`

`outward_factor = min(1, outward_rise_score / 60) ** 0.125`

`guarded_core = local_core * containment_factor * outward_factor`

The final plane score is:

`v2.3 = 0.80 * v2.2 + 0.20 * guarded_core`

Horizontal and vertical scores retain the existing mouth-dimension weighting.
The JSON result exposes the baseline, unguarded core, guarded core, factors,
triggered guardrails, constants, and final score.

The containment threshold means that at least 75% of relative angular energy
must remain in the intended coverage window before the local branch receives
full credit. The outward-rise threshold corresponds to approximately 1.63 dB
RMS outward-rise violation under the existing inverse-error mapping. These are
soft floors, not pass/fail rejection boundaries. V2.2 still supplies its
ordinary continuous containment and outward-rise terms above the floors.

## Candidate selection

The calibration evaluated a finite grid:

- local-core fraction: 10%, 20%, 30%, 40%, or 50%;
- containment floor: 75%, 80%, 85%, or 90%;
- outward-rise score floor: 60%, 70%, 80%, or 90%;
- each guardrail exponent: 0.125, 0.25, 0.5, or 1.

A candidate was ineligible if any of the broad, close-score, or per-cell
populations lost more than 0.005 mean Spearman correlation or pairwise
agreement relative to v2.2. Eligible candidates were ordered by mean agreement
across the three populations, with simpler/weaker corrections breaking exact
ties.

This search is intentionally bounded. It is not unrestricted continuous
optimization of the same rankings used for evaluation.

## Calibration result

Across the existing rankings:

| Population | Metric | V2.2 | V2.3 |
| --- | --- | ---: | ---: |
| Broad, 10 rounds | Mean Spearman | 0.902 | 0.898 |
| Broad, 10 rounds | Pair agreement | 89.1% | 88.7% |
| Close-score, 10 rounds | Mean Spearman | 0.402 | 0.491 |
| Close-score, 10 rounds | Pair agreement | 66.7% | 70.0% |
| Per-cell, 25 cells | Mean Spearman | 0.546 | 0.579 |
| Per-cell, 25 cells | Pair agreement | 70.8% | 72.5% |

V2.3 retains all six broad exact winners and all eight per-cell exact winners
from v2.2. It selects five rather than six exact close-round winners; exact
winner count is therefore not uniformly improved even though the close-round
order improves.

Paired whole-group bootstrap intervals place the broad Spearman change at
−0.018 to +0.010, the close-score improvement at +0.008 to +0.188, and the
per-cell improvement at +0.013 to +0.055. The observed broad difference is
therefore consistent with no change; the two finer-ordering improvements are
positive on this evidence. These intervals do not remove calibration reuse.

The guardrails activate for 19 of 100 broad candidates, 24 of 100 close-score
candidates, and 3 of 250 per-cell candidates. This is the intended behavior:
they protect the broad population without spending much ranking range among
the already-good cell candidates.

## Validation limits and release policy

This is a better calibrated general-purpose candidate, not an independent
validation result:

- the broad rankings previously influenced the beamwidth-quality component;
- the per-cell rankings fit the local-core weights;
- all ranking games forced total orders without ties or confidence;
- the completed evidence does not contain a newly blinded mixed-quality set.

V2.3 is therefore emitted and displayed side by side but does not replace the
primary v1 score or silently rewrite retained reports. Promotion requires a new
blinded ranking set containing both obvious failures and close high scorers,
with ties/confidence allowed, followed by a frozen evaluation.

Rebuild the calibration:

```sh
.venv/bin/python -m app.tools.calibrate_surface_score_v2_3
```

The complete machine-readable result is
[`surface_score_v2_3_calibration.json`](../../examples/surface-score-v2-2-cell-ranking-game/surface_score_v2_3_calibration.json).
