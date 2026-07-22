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

## Historical boundary work

Earlier S-boundary and coupled-length work remains historical evidence. The
Phase-4 coordinator does not rerun those phases; it starts directly with remote
domain-map Batch 1.

## Equal-opportunity map

Every one of the 25 mouth/coverage cells receives four remote candidates.
No Phase-4 candidate is scheduled at 25 degrees or at a 500 mm mouth. Existing
results at those edges remain historical evidence only. This yields 100
candidates total. Batch 2 is not materialized
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

Batch 1 maximizes distance from existing realized geometry and is retained as
broad discovery work. Batch 2 is a controlled-effect experiment, not another
optimizer. Every cell receives one two-candidate matched pair. The varied
control is balanced across the grid: nine cells vary physical length, eight
vary K, and eight vary N. The other two independent controls are held exactly
fixed within each pair. Initial targets are approximately −25%/+25% length,
−1.5/+1.5 K, or −4/+4 N around a measured anchor, with predefined closer
fallbacks when geometry or an existing duplicate prevents the broad pair.

This 50-candidate allocation estimates replicated main effects across the full
mouth/coverage domain without pretending S and physical length are independent;
S is recorded as a derived coordinate. It does not estimate every control in
every cell or identify all K/N/length interactions. Interaction blocks are a
separate follow-up selected from cells where matched effects reverse or depend
strongly on the starting diagnostic state.

## Learning objective

The final score remains the ranking target, but the map also models
containment, profile RMS error, slice-energy departure, outward-rise violation,
and the secondary -6 dB line. Candidate provenance states whether a solve was
selected for distance, uncertainty, a matched contrast, or material predicted
gain.

The first diagnostic hypothesis is that wider-coverage horns retain good
containment and average in-window distribution but develop angular shoulders
as mouth/length ratio increases. Batch 1 maps remote alternatives; Batch 2 uses
matched score and diagnostic differences to determine whether length, K, or N
actually changes that behavior when the other independent controls are fixed.

## Completion

Phase 4 is complete only when all 100 candidate slots are complete or carry an
explicit geometry/failure outcome. Reports expose planned and active slots,
acquisition reasons, parameter values, nearest-evidence distance, and the
one-point materiality rule. Compact response archives remain retained so new
diagnostics can be applied without rerunning BEM.
