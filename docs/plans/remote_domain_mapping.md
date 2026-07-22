# Remote zero-extension domain mapping

## Purpose

The uniform-S and coupled phases located useful symmetric horn ridges, but the
coupled phase remained a local optimizer. It used fixed nearby S offsets and
sampled most heavily around the original K=4, N=10 surface. Phase 4 changes the
objective from polishing sub-point score differences to reducing holes in the
measured design domain.

The active design envelope remains square, symmetric, and zero-extension:
coverage half-angles 30–50 degrees in five-degree increments and mouths
250–450 mm in 50 mm increments. Existing 25-degree results and 500 mm mouths
remain historical edge evidence, but are not allocated full remote-map work.
Conical extensions, section-shape morphing, and independent horizontal/vertical
curves are explicitly deferred.

## Boundary repair

S closure is directional. A rejected far high-S sentinel closes only the high
side and cannot certify a low-S endpoint winner. Unresolved directions use
expanding S displacements of 0.3, 0.6, and 1.2 from the incumbent, stopping at
a measured decline, a same-direction geometry limit, or the S safety limit.

Four fixed-K/N cells were incorrectly labeled geometry-limited by the older
sentinel behavior. They are eligible for corrected low-side closure. The
50-degree, 400 mm coupled result remains a practical stop rather than a proven
length bracket.

## Equal-opportunity map

Every one of the 25 interior mouth/coverage cells receives four remote
candidates. The five 25-degree cells already completed or running at
250–450 mm retain their two Batch-1 candidates as sparse edge sentinels. No
Batch 2 is scheduled at 25 degrees, and no Phase-4 candidate is scheduled at a
500 mm mouth. This yields 110 candidates total. Batch 2 is not materialized
until Batch 1 results have entered the measured dataset.

Candidate generation uses feasible symmetric points in:

- S from 0.05 through 4.0, rounded to 0.1;
- K from 1 through 7, rounded to 0.5; and
- N from 2 through 20, rounded to integers.

These grids also apply to any new directional closure probe. A closure may
retain an already-running legacy quarter-step value as historical evidence,
but it cannot propagate that value into a later candidate: K is snapped to the
nearest 0.5 and N to the nearest integer before materialization.

Length is derived from S, K, and N with the same HornCAD equations used by the
exporter. Negative-S and late-growth/disc-like geometry are rejected before
BEM and replaced with the next feasible proposal.

Batch 1 maximizes distance from existing realized geometry. Batch 2 combines
70% distance with 30% global model uncertainty. Its two cross-strata complete
the coarse low/high K and N foldover begun by Batch 1. At 45 and 50 degrees,
one candidate per mouth is selected as a matched cross-angle contrast in
mouth/length ratio, K, and N.

Prescribed mapping candidates are not pruned for a poor predicted score. A
local exploitation proposal may replace the normal Batch-2 acquisition only
when its predicted score minus one prediction sigma exceeds the incumbent by
at least one point.

## Learning objective

The final score remains the ranking target, but the map also models
containment, profile RMS error, slice-energy departure, outward-rise violation,
and the secondary -6 dB line. Candidate provenance states whether a solve was
selected for distance, uncertainty, a matched contrast, or material predicted
gain.

The first diagnostic hypothesis is that wider-coverage horns retain good
containment and average in-window distribution but develop angular shoulders
as mouth/length ratio increases. The matched 45/50-degree contrasts and remote
long/high-K points test whether reducing mouth/length ratio while increasing K
suppresses outward rise without sacrificing containment.

## Completion

Phase 4 is complete only when all 110 candidate slots are complete or carry an
explicit geometry/failure outcome. Reports expose planned and active slots,
acquisition reasons, parameter values, nearest-evidence distance, and the
one-point materiality rule. Compact response archives remain retained so new
diagnostics can be applied without rerunning BEM.
