# Unified round-control v2 consolidation

## Decision

The primary and augmented v1 artifacts remain immutable audit releases. They
answered whether compatible historical evidence improves a balanced canonical
model, but their cell-by-cell production router is not the desired foundation
for later geometry corrections.

`round_control_v2` will be one continuous ten-term quadratic model over the full
5×5 domain:

- coverage half-angle: 30, 35, 40, 45, and 50 degrees;
- square mouth: 250, 300, 350, 400, and 450 mm;
- the existing supported L/K/N ranges and geometry gate.

No mouth or coverage cell is removed merely because the first extension study
is likely to concentrate elsewhere.

## Existing evidence and candidate models

All compatible, exact-response-deduplicated evidence is development evidence
for v2:

- canonical fit rows;
- the 50 former v1 locked rows, whose outcomes are already known;
- compatible historical challenge rows.

The fresh v2 validation rows remain inaccessible until every candidate model,
prediction, coordinate, scale, selection rule, and hash is frozen.

Every candidate retains the same interpretable ten-term L/K/N quadratic in all
25 cells. Candidates differ only in the global influence assigned to
density-balanced historical evidence. Canonical evidence always has unit
weight. Historical weights tested are:

```text
0.00, 0.10, 0.25, 0.50, 1.00
```

The density correction is inverse occupancy in the existing
0.05-length-factor × 0.25-K × 1-N bins. A single historical-weight setting is
used over the entire grid; there is no per-cell primary/augmented router.

Candidate comparison uses deterministic five-fold coordinate-grouped
cross-validation. The six radiation diagnostics contribute equally after
normalization by their development-evidence interquartile ranges. Throat
impedance is predicted and validated independently but is excluded from model
selection and surface score.

The candidate frozen for release validation minimizes:

```text
mean normalized MAE + 0.25 × worst-cell normalized MAE
```

This protects the full grid rather than optimizing only the densest or central
cells.

## Fresh locked validation

Twelve new round BEM responses form the only honest v2 release validation. They
cover every registered mouth and coverage level:

| Coverage | Mouths |
|---|---|
| 30° | 250, 350, 450 mm |
| 35° | 300, 400 mm |
| 40° | 250, 350 mm |
| 45° | 300, 450 mm |
| 50° | 250, 400, 450 mm |

This allocation includes v1 disagreement cells, difficult outer cells, and all
five mouth and coverage levels. It does not redefine the supported domain as
only the validation cells.

Within each registered cell, the coordinate is chosen deterministically before
BEM from an interior L/K/N pool. Selection rewards:

- prediction spread among the frozen unified candidates and both v1 models;
- distance from existing exact coordinates;
- valid, supported geometry.

It never uses a new BEM outcome or predicted surface-score rank.

## Final validation and release

After all twelve archives pass integrity and diagnostic reproduction checks,
the already selected candidate is evaluated against them. The fresh outcomes
cannot switch the release to another candidate; doing so would turn the release
set into tuning evidence. The selected candidate must satisfy:

- surface-score MAE no greater than 1.75 points;
- surface-score 90th-percentile absolute error no greater than 3.60 points;
- no invalid or non-finite prediction;
- one coefficient field, one uncertainty policy, and no companion-model router.

Radiation-diagnostic release thresholds are recorded in the frozen manifest.
Throat-impedance error is reported separately and cannot change the selected
candidate.

All frozen candidates are reported for scientific comparison, but only the
development-cross-validation winner is eligible for v2. It is exported without
refitting on the twelve new
responses. This preserves their validation role. Those responses become
eligible development evidence only for a later version that has a different
fresh validation set.

If no candidate passes, v2 is not released. The primary v1 model becomes the
sole supported baseline while the failure pattern is diagnosed; the augmented
v1 model remains comparison evidence.

## Commands and execution boundary

```bash
python -m app.tools.round_control_v2 prepare
python -m app.tools.round_control_v2 status
python -m app.tools.round_control_v2 run --slots 2
python -m app.tools.round_control_v2 finalize
```

`prepare` writes and hashes all candidate models and validation coordinates but
does not launch BEM. `run` executes only those frozen fixed-design searches.
`finalize` refuses incomplete, changed, or failed evidence.
