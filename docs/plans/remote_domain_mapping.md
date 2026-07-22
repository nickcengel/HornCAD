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

The already-running Batch 1 contributes the same two remote maximin samples in
every cell: one low-S/low-K/low-N point and one high-S/high-K/high-N point. Its
50 outcomes test whether useful behavior exists far from the previously dense
K=4, N=10 ridge. They are retained as broad discovery and held-out validation,
but their correlated controls cannot by themselves estimate independent
effects.

## Batch 2: identical response surface in every cell

Each cell uses its best completed K=4, N=10 result as a deterministic center
with physical length L0. Every cell receives the same face-centered design:

- length levels: 0.85 L0, 1.00 L0, and 1.15 L0;
- K levels: 3, 4, and 5; and
- N levels: 6, 10, and 14.

The center already exists. Fourteen additional prescribed coordinates comprise
the six axial points (one factor low or high, two centered) and all eight
low/high corners. This is 15 modeled coordinates per cell and 350 new Batch-2
coordinate outcomes over the 25 cells.

The design is deliberately identical in every cell. It supports main effects,
quadratic curvature, and length×K, length×N, and K×N interactions without
confounding a control with mouth size or coverage. Exact existing results are
reused. Geometry-invalid coordinates are recorded as rejected boundary
outcomes and are not silently replaced by easier special cases.

The materialized manifest is `batch_2_response_surface.json`. It is the source
of truth for every prescribed coordinate, its factor levels, physical values,
derived S, and status. At the current checkpoint it contains 350 prescribed
coordinates: 315 new simulations, 9 exact reused results, and 26 explicit
geometry rejections. These counts can change only if additional exact results
complete before Batch 2 is materialized; the design coordinates cannot change.

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

Batch 1 is allowed to finish unchanged. A guarded supervisor then stops the old
coordinator before its stale Batch-2 plan can run and launches the committed
Batch-2 entry point with `--start-batch 2`. The entry point preserves Batch-1
state, writes the exact response-surface manifest, materializes all feasible
cell searches, and resumes completed work rather than duplicating it.

Two concurrent searches with ten solver workers each keep the 20-core machine
occupied. Each completed subsearch updates the state and index report. The
state ledger exposes all 400 Phase-4 coordinate outcomes in advance: 50 remote
Batch-1 coordinates plus 350 Batch-2 response-surface coordinates.

Phase 4 is complete only when every coordinate is complete, reused,
geometry-rejected, or explicitly failed. Candidate reports, compact response
archives needed for future diagnostics, the manifest, state, analysis, and
index are tracked as study artifacts.
