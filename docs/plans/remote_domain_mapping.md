# Zero-extension system-identification study

## Objective

The study must teach how physical length, K, and N affect score and each surface
diagnostic across the useful symmetric, square, zero-extension horn domain. It
is not a local score optimizer. S is a derived OS-SE geometry result, not a
fourth independent control.

The active domain is the same 25-cell matrix in every stage:

- half-coverage: 30, 35, 40, 45, and 50 degrees;
- square mouth: 250, 300, 350, 400, and 450 mm; and
- zero extension with identical horizontal and vertical curves.

The retained 25-degree and 500 mm results are edge history only. They receive no
new work. Conical extensions, round-to-square morphing, and independently
coupled horizontal/vertical curves remain later studies.

## Batch 1: remote validation

Batch 1 originally prescribed the same two remote maximin samples in every
cell: one low-S/low-K/low-N point and one high-S/high-K/high-N point. Interim
review found 29 of 30 completed remote outcomes were simple boundary
confirmations, none was competitive, and none exposed a useful diagnostic
tradeoff. Median score change was -11.3 points. Because the controls move
together, the samples also cannot estimate independent effects.

The remote batch is therefore intentionally truncated after the two candidates
that were already in flight on July 22 finish. Completed results remain sparse
outer-boundary evidence and out-of-domain model checks. Unstarted cells are
recorded as abandoned redundant boundary work rather than simulated. The
response-surface stage receives the saved compute.

## Batch 2: deduplicated quadratic identification

Each cell uses its best completed K=4, N=10 result as a deterministic center
with physical length L0. All new candidates use the same normalized levels:

- length levels: 0.85 L0, 1.00 L0, and 1.15 L0;
- K levels: 3, 4, and 5; and
- N levels: 6, 10, and 14.

The existing K4/N10 S grids already sample the physical-length axis. Repeating
K4/N10 at nominal ±15% length was therefore removed. The augmentation pool is
limited to four center-length K/N axial points and eight low/high interaction
corners. Existing symmetric zero-extension evidence is deduplicated in
normalized length/K/N coordinates before it contributes model information.

For each cell, a greedy D-optimal audit selects only enough feasible pool points
to make the combined existing-plus-new quadratic feature matrix full rank and
bring its condition number to 18 or less. The modeled terms are length, K, N,
their three squares, and all three pair interactions. This preserves a common
factor basis across cells while allowing cells with substantial prior evidence
to run fewer new candidates. A nearby existing point within 0.18 normalized
distance covers a proposed coordinate; geometry-invalid points remain explicit
boundary outcomes. Nothing is silently replaced by an optimizer proposal.

The materialized manifest is `batch_2_response_surface.json`. It is the source
of truth for all 300 audited pool coordinates, their physical and normalized
values, geometry status, nearest-existing distance, selection result, and each
cell's before/after matrix rank and condition number. Once committed, that
manifest is fixed for execution and resume.

## Analysis and steering rules

Models are fit to final surface score and separately to mean containment,
profile RMS error, slice-energy departure, outward-rise violation, and the
secondary -6 dB line diagnostic. The first questions are:

1. Which factor changes each response, in which direction, and with what
   magnitude?
2. Which effects reverse with coverage, mouth size, length regime, or starting
   diagnostic state?
3. Which interactions explain energy bunching or the outward-rise degradation
   seen at wider coverage?
4. Do Batch-1 remote samples agree with the fitted surface or expose another
   ridge that the local three-level design misses?

Later points are allowed only when a predefined model check justifies them:
large held-out residual, unresolved curvature at an active boundary, or an
interaction whose uncertainty changes a design recommendation. No sub-point
score polishing and no ad hoc per-cell optimizer are part of this phase.

## Execution and handoff

The duplicate-heavy first Batch-2 attempt was stopped after its two active
+15% length candidates finished. Its completed points remain evidence, but the
superseded searches are hidden. The replacement entry point preserves Batch-1
state, writes the audited manifest, materializes only selected candidates, and
resumes completed work rather than duplicating it.

Two concurrent searches with ten solver workers each keep the 20-core machine
occupied. Each completed subsearch updates the state and index report. The
state ledger retains the original 50 Batch-1 slots so completed and
intentionally abandoned work remain distinguishable, followed by the 300
audited Batch-2 candidate-pool coordinates and their selected/not-selected
outcomes.

Phase 4 is complete only when every coordinate is complete, reused,
geometry-rejected, or explicitly failed. Candidate reports, compact response
archives needed for future diagnostics, the manifest, state, analysis, and
index are tracked as study artifacts.
