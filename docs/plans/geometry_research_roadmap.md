# Geometry research roadmap

This roadmap defines how the round control model is extended into more complex
horn geometries. The objective is a sequence of interpretable, validated model
augmentations, not one Cartesian search over every available control.

## Geometry terminology

- **Length** always means the axial length of the OSSE profile.
- **Extension** is the separately authored conical throat extension length.
- **Profile-plus-extension length** is OSSE length + extension.
- **Sag distortion** is the local axial setback introduced by mouth sag.
- **Measured exported span** is the actual `max(z) - min(z)` of a selected
  surface or body export; it is not computed by adding sag to OSSE length.

Length must never be renamed, redefined as exported depth, or silently shortened to
compensate for extension or sag. Unless a registered contrast explicitly changes
more than one quantity, adding extension holds OSSE length fixed and increases
profile-plus-extension length by the extension amount.

## General experimental policy

Each stage starts from the released model produced by the preceding stage and
adds one new physical effect. It uses paired geometries, with all controls other
than the registered contrast held fixed. Some parents must be withheld from
fitting and used to test prediction. Additional BEM points are commissioned where
prediction error is material or uncertainty remains high; an augmentation is not
accepted merely because its training points fit well.

Parent selection must include more than the highest-scoring horn. It should span
useful OSSE lengths/S values, K/N regions, and distinct diagnostic behavior so the
new effect is not mistaken for a winner-specific correction. Frequency-resolved
diagnostics remain available alongside the final score.

Every subsequent BEM stage uses the
[stage-aware BEM scheduler](../reference/bem_stage_aware_scheduler.md) with the
shared NumCalc capacity guard. Fixed designs are sharded at candidate
granularity so the final candidates can overlap; a study may not revert to
whole-search scheduling that leaves half the solver capacity idle at the tail.

A densely sampled inner design region does not by itself authorize prediction at
the outer cells of the round baseline. Each augmentation therefore uses a
**core-plus-sentinel** design: detailed paired contrasts in the likely product
region, plus sparse locked transfer tests at outer-domain cells. The outer tests
are predicted before their results are added to fitting. They are expanded only
where prediction error is material. Until the sentinels pass, reports must label
outer-cell predictions as extrapolations rather than supported behavior.

## Stage 1: measured round baseline

The axisymmetric round-mouth zero-extension study under
`examples/control-decoupling/` is complete. Its measured responses are the
round baseline. Primary v1 remains an API-compatible reference estimator and
augmented v1 remains comparison evidence, but neither is a validated global
interpolator. Later stages use measured round parents. The validation and
export requirements are defined in the control study's
[model pipeline](../../examples/control-decoupling/model_pipeline.md).

The measured baseline archive is frozen before later geometry work.
The full-grid
[unified-v2 challenge](../../examples/round-control-v2-validation/README.md)
failed its release gates and identified jointly sparse L/K/N regions that must
remain limited-support.
The subsequent 48-case
[ridge-closure study](round_control_ridge_closure.md) is complete: all retained
archives reproduced their diagnostics, 13 of 16 cells bracketed length at the
outward K, and six cells promoted a K=1/K=7 result to the final measured seed.
The three-case
[short-length closure](round_control_short_length_closure.md) then bracketed
the remaining K=1 length curves without requiring its conditional block.
The measured heuristic includes the exact ridge-results hash and publishes
per-cell closure status.
The bounded ten-case
[wide-coverage closure](round_control_wide_coverage_closure.md) found only a
0.268-point best local gain and strongly rejected the longer 50°/450 mm
continuation. Its conditional infinite-baffle controls were deliberately not
run. Mouth-edge diffraction is the leading provisional explanation for the
remaining 45°/50° deficit, and no more round simulations are planned for this
issue; the mechanism question moves forward into intended non-round and baffle
geometry.
The earlier central-grid handoff under
`examples/control-decoupling/model_source/extension_handoff.json` is superseded
by the completed extension evidence and composite closure. The maintained
measured result is summarized in the
[round-control heuristic reference](../reference/round_control_heuristics.md).

## Stage 2: conical extension and throat angle

Stage 2 is complete. The 6-degree composite map contains 1,542 exact-deduplicated
zero-extension responses and 101 extension responses. Zero extension wins the
registered 75/25 surface/impedance composite in all 25 cells, including every
S-recovery closure. Extension remains an early measured surface-priority branch
in the four documented cells. Matched A6/A8 evidence improves throat impedance
in 14 of 15 lower-angle cases, but the attempted general throat-angle predictor
failed and was not released.

## Stage 3: square and independent-H/V transfer

The targeted
[non-round transfer study](../../examples/non-round-transfer-study/study_plan.md)
is complete and replaces the earlier separate generic square and ellipse
stages. It measured 51 valid BEM coordinates with one geometry rejection. All
eight equal-H/V square transforms improved on their round parent, with a median
+3.372 surface-v2.3 points. The 14 development pairs selected weighted common
length by the registered ±0.5-point median tie rule.

Every candidate fixes zero extension, zero sag, a 6-degree throat, and intended
OS-SE coverage. The study retains independent H/V K/N, uses S-balanced length
when weighted length has nonpositive derived axis S, and widens first-round
exploration near the reversed-coverage L5 region. It does not fit a portable
correction or a global score surrogate.

## Stage 4: measured optimizer handoff

The measured [BEM horn optimizer](design_recommendation_map.md) is implemented
as the practical design handoff. It uses the promoted heuristics to construct
candidates, exact
compatible responses as zero-cost evidence, and new BEM measurements to improve
one fixed user intent. Independent H/V K/N remain authored controls, common
length and extension remain searched, and derived H/V S guides coupled moves.

The optimizer preserves multiple measured basins, operates in stage-aware
batches of at most four, enforces one hard simulation cap, and requires a
budget-counted final confirmation after evidence-based early stopping. Its
finite run-local response approximation is not a global or portable model.

## Stage 5: sag and complementary H/V design

Add sag after H/V and rectangular effects are understood. The first objective is
to determine whether sag can accommodate different preferred horizontal and
vertical OSSE lengths while preserving one manufacturable coupled geometry.

The second objective is to exploit complementary frequency behavior. Retain and
model frequency-resolved slice-energy, profile-error, outward-rise, -6 dB, and
impedance behavior. Select H and V profiles whose undesirable energy bunching
occurs in different frequency regions, then test whether sag and coupled geometry
produce a combined response smoother than either independently selected profile.
Final score alone is insufficient for this selection.

## Model progression

The portable model is versioned rather than replaced by disconnected studies:

```text
round-control baseline
    + extension correction
    + throat-angle correction and supported interaction
    + measured square/HV transfer initialization
    + BEM-confirmed run-specific optimization
    + sag and complementary-profile correction
```

Portable corrections still require training provenance, support domain,
diagnostic-specific validation error, uncertainty, and demonstrated
interactions. The optimizer is distinct: it publishes measured lineage,
nearest evidence, support warnings, and simulation accounting for one run.
Unsupported interactions are not filled by a broad brute-force grid.
