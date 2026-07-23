# Round-control ridge-closure study

## Completion status

Completed with all 48 registered responses retained and audited. Recalculation
matched stored diagnostics within `1e-9`; all responses share the registered
solver fingerprint; no disposable NumCalc work trees remain.

Length was bracketed at the tested outward K in 13 of 16 cells. K=1/K=7 beat
the compatible inner K=2/K=6 evidence in six cells and lost in ten. The six
wins are registered-domain boundary seeds, not claimed unconstrained optima.
Detailed per-cell results and response hashes are in `results.json`, and the
released measured heuristic records that file's SHA-256.

This run also exposed a scheduler-tail limitation: separate searches overlapped,
but the last search processed its candidates sequentially. Future fixed studies
must use the stage-aware queue with one candidate per schedulable search as
required by `docs/reference/bem_stage_aware_scheduler.md`.

## Purpose

The completed round study found competitive short/low-K and long/high-K
regions, but many measured winners remained on the canonical K and length
boundaries. This study determines whether those regions turn over within the
registered K=1–7 domain and converts the result into stronger deterministic
design heuristics. It is not an attempt to revive a global score surrogate.

The complete 5×5 mouth/coverage field remains in scope. Candidate concentration
at particular cells is an information-allocation decision, not a reduction of
the supported design domain.

## Frozen design

The study has a hard limit of 48 new BEM evaluations:

- 16 cells selected from the observed short/low-K or long/high-K regions;
- one outward K boundary per cell: K=1 for the low branch or K=7 for the high
  branch;
- N=4 for the two 30° low-branch cells and N=8 otherwise;
- three lengths per cell: 0.9, 1.0, and 1.1 times the length that preserves the
  pre-study coverage-median target S.

Low-branch cells:

- 30°/250 mm, 30°/300 mm;
- 35°/250 mm, 35°/300 mm;
- 40°/250 mm;
- 45°/250 mm.

High-branch cells:

- 30°/400 mm, 30°/450 mm;
- 35°/400 mm, 35°/450 mm;
- 40°/350 mm, 40°/450 mm;
- 45°/300 mm, 45°/450 mm;
- 50°/300 mm, 50°/450 mm.

This selection covers all five mouth diameters and all five coverage rows. It
includes both established edge regions and cells near the observed branch
transitions.

## Interpretation

For each cell, the existing K=2 or K=6 evidence supplies the inner K
comparison. The three new lengths test the adjacent K=1 or K=7 boundary while
bracketing length around the physical S seed.

- If the center length beats both new length offsets, length is locally
  bracketed at that K.
- If K=1/K=7 loses to the compatible inner-K evidence, the preferred K lies
  inside the registered K domain at the sampled resolution.
- If K=1/K=7 wins, the best registered-domain seed is a K boundary result; it
  is reported as such rather than described as a proven unconstrained optimum.
- Repeated behavior across cells may update the branch map and S guidance.
  Isolated improvements update only their measured-cell seed.

No more than 48 candidates may be scheduled. There is no automatic follow-up
round study.

## Outputs and scoring

Every retained response records the existing six radiation diagnostics and the
experimental throat-impedance diagnostic. Throat impedance remains excluded
from surface score, candidate ranking, and heuristic selection.

After completion:

1. validate and rescore every retained NPZ;
2. publish per-cell inner/outer-K and length-bracketing results;
3. rebuild `round_control_heuristics_v1` from the earlier evidence plus these
   measured responses;
4. expose boundary/closure status with the measured axis seeds;
5. verify a deterministic rebuild and run repository validation.
