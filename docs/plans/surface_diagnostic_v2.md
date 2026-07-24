# Surface diagnostic v2: multiscale contour quality

Status: completed and released

Release outcome: the contour-forward top-level weighting passed every promotion
criterion and was selected in all 20 initial leave-one-round-out folds. The
initial reference values preserved useful ordering but compressed all measured
beamwidth-quality scores into 4–28%. As permitted below, one uniform reference
sensitivity pass evaluated 1×, 1.5×, 2×, 2.5×, and 3× values with nested held-out
round selection. The 3× scale was selected in 15 held-out folds and by the
complete evidence; 1.5× was selected in four folds and 1× in one. The released
3× references produce a measured 22–74% range; final broad-round Spearman
agreement is 0.879 and close-round agreement is 0.459. Formulas and component
weights were not changed.

## Purpose

The completed blinded ranking experiment showed two distinct results:

- the existing surface score discriminates broad quality differences well;
- among close existing scores, human preference follows frequency-to-frequency
  beamwidth smoothness substantially better than the existing total score.

The current implementation already records movement of the -6 dB crossing, but
does not include that movement in the score. Directly scoring RMS movement is
not sufficient: it penalizes a harmless smooth global slope along with local
ripple. Version 2 must reward simple smooth contour shapes, penalize narrowing
more strongly than widening, tolerate a smooth global offset or trend, and
still require adequate high-frequency coverage.

No additional BEM is part of this work. The completed 200-plot human ranking
experiment is the calibration and validation evidence.

## Compatibility and release policy

1. Preserve the existing score as `surface_score_v1`.
2. Add `surface_score_v2` and report v1 and v2 side by side during validation.
3. Keep throat impedance separate from both surface scores.
4. Promote v2 to the normal `surface_score()` result only if leave-one-round-out
   validation improves close-score agreement and retains broad discrimination.
5. Store the version, component weights, reference values, calibration evidence,
   and implementation hash with released results.
6. Do not rewrite or stage the active extension/throat-angle study while it is
   running. Its reports can be refreshed after that study reaches a checkpoint.

## Contour traces

For each principal plane and frequency, find the first outward-going crossings
of -3, -6, and -9 dB. Under the existing linear target profile their nominal
half-angles are:

| Contour | Nominal half-angle |
| --- | ---: |
| -3 dB | `0.5 * coverage` |
| -6 dB | `1.0 * coverage` |
| -9 dB | `1.5 * coverage` |

Represent every valid trace as normalized width

`q_c(x) = crossing_angle_c(x) / nominal_angle_c`

on log-frequency coordinate `x = log2(frequency)`. This makes the shape terms
comparable across coverage cells and contours. Absolute angles remain in the
diagnostic output.

Missing crossings are never silently interpolated across a sustained gap.
Metrics may interpolate isolated internal samples only for a window that
retains at least 80% valid support. Missing fraction and longest missing run are
reported, and completeness caps the contour score.

## Shape measurements

### 1. Multiscale ripple

Compare each normalized trace with centered moving means at 1/12, 1/6, 1/3,
2/3, 1, and 2 octave scales, clipped to the available band. A linear trace has
zero centered residual away from boundaries, regardless of global slope.

Record RMS residual separately at every scale and their fixed-weight aggregate.
The aggregate penalizes ripple from fine through broad scales; no single
smoothing width can hide an otherwise visible disturbance.

### 2. Low-complexity trend

Smooth the trace over 1/3 octave, differentiate with respect to log frequency,
and subtract its net band slope. Integrate the absolute remaining slope
variation. This is zero for a straight widening or narrowing trend and grows
with bends, reversals, and broad undulations.

Also report the robust number of slope reversals after suppressing changes below
the angular-resolution floor. Reversal count is explanatory and is not a
discontinuous score input.

### 3. Local narrowing

At every multiscale window calculate the positive deficit

`d_s(x) = max(0, moving_mean_s(q_c)(x) - q_c(x))`.

Use the worst supported 95th-percentile deficit across scales. This adds an
asymmetric penalty for a local dip. Local widening still contributes to
multiscale ripple and trend complexity, but does not receive the extra narrowing
penalty.

### 4. High-frequency adequacy

Average normalized width over the upper one-third octave. Give full credit
inside a symmetric deadband around 1.0. Outside the deadband, score only the
excess error. This prevents an artificial reward for exact target coincidence
while rejecting a smooth trace that finishes materially too narrow or wide.

### 5. Completeness

Report missing fraction and longest missing span in octaves for every contour.
Completeness multiplies, rather than averages into, the other contour terms so
a missing crossing cannot be hidden by good behavior elsewhere.

## Beamwidth-quality score

Map ripple, trend complexity, local narrowing, and high-frequency excess to
0–100 with the existing bounded inverse-error mapping:

`100 / (1 + (error / reference)^2)`.

The preregistered internal weights are:

- 30% multiscale ripple;
- 25% low-complexity trend;
- 30% local narrowing;
- 15% high-frequency adequacy.

Combine these four terms geometrically, then multiply by crossing completeness.
The geometric combination makes a serious localized failure difficult to hide
with unrelated good averages.

Combine contour scores geometrically with weights:

- 25% at -3 dB;
- 50% at -6 dB;
- 25% at -9 dB.

The -6 dB line remains primary, while -3 and -9 dB prevent a smooth central
crossing from concealing malformed shoulders.

Initial normalized reference values are deliberately interpretable:

- ripple RMS: 0.04 of nominal width;
- trend slope variation: 0.12 of nominal width per octave;
- local narrowing: 0.06 of nominal width;
- high-frequency deadband: 0.10 of nominal width;
- high-frequency excess reference: 0.15 of nominal width.

These values are frozen for the first validation pass. If sensitivity analysis
is required, it must use a small documented grid and nested held-out rounds;
the final report must retain the original pass.

## Combined v2 surface score

Evaluate these four preregistered top-level alternatives:

| Candidate | Profile | Slice energy | Containment | Outward rise | Beamwidth quality |
| --- | ---: | ---: | ---: | ---: | ---: |
| conservative | 30% | 25% | 15% | 10% | 20% |
| balanced | 30% | 25% | 10% | 10% | 25% |
| smoothness | 30% | 20% | 10% | 10% | 30% |
| contour-forward | 30% | 20% | 5% | 5% | 40% |

Do not optimize unrestricted continuous weights on the same rankings used for
evaluation. Select among these four alternatives by leave-one-round-out
validation, with each full ten-plot round held out in turn.

## Validation

The calibration report must compare v1, beamwidth quality alone, and every v2
candidate using:

- mean and median within-round Spearman correlation;
- pairwise ordering agreement;
- results separated into broad rounds 1–10 and close-score rounds 11–20;
- per-round results, not only pooled summaries;
- bootstrap or permutation uncertainty;
- score distribution and changed-rank audit;
- the user's five written plot notes as qualitative checks.

Promotion requires:

1. close-round mean Spearman correlation at least 0.25 and better than v1;
2. close-round pairwise agreement above 60%;
3. broad-round mean Spearman no more than 0.05 below v1;
4. no synthetic regression failure for ideal, sloped, rippled, locally narrowed,
   missing-crossing, or angular/frequency-resampled surfaces.

If no candidate passes, keep v1 as normal and publish v2 as experimental. Do not
adjust thresholds repeatedly until the same ranking set passes.

## Reports and API

Candidate reports must expose, for each plane and contour:

- absolute and normalized contour traces;
- missing fraction and longest missing span;
- per-scale ripple;
- trend complexity and explanatory reversal count;
- local-narrowing value;
- upper-third-octave width and target error;
- contour score and combined beamwidth-quality score.

The final score table must identify the active surface-score version and retain
the v1 value for comparison. Plain JSON exports must contain both versions and
all constants needed for independent evaluation.

## Tests and reproducibility

- Synthetic smooth global slopes score materially better than equal-amplitude
  localized dips or oscillations.
- Fine and broad sinusoidal ripple are both detected.
- A local narrowing penalty exceeds the corresponding widening penalty.
- -3 and -9 dB disturbances affect the result even with an unchanged -6 dB
  crossing.
- Missing crossings cap the relevant contour score.
- Frequency decimation and angular resampling remain within stated tolerances.
- Repeated calibration and report generation are byte deterministic.
- Python report and exported JSON values agree on fixed vectors.

All implementation, calibration outputs, and documentation are committed in
recoverable checkpoints without staging active-study runtime files.
