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
The earlier central-grid handoff under
`examples/control-decoupling/model_source/extension_handoff.json` is superseded
by the full-grid [extension and throat-angle heuristic study](extension_throat_angle_heuristic_study.md).
That plan schedules no BEM and remains launch-gated until ridge closure and the
resulting measured-heuristic rebuild are complete.

## Stage 2: conical extension and throat angle

Stage 2 covers the complete 5×5 round baseline: 30–50 degrees in 5-degree
steps and 250–450 mm in 50-mm steps. It measures extensions 0, 20, 40, and
60 mm and throat angles 0, 6, and 12 degrees using a staged 210-case design,
with a 16-case conditional validation block and an absolute cap of 226 new BEM
evaluations.

The authoritative candidate allocation, fixed paired-effect formula, locked
validation cells, error thresholds, geometry convention, and launch gates are
defined in the
[extension and throat-angle heuristic study](extension_throat_angle_heuristic_study.md).
The study uses the final measured winner in every cell plus three secondary
parents to test parent transfer. It reuses all compatible 6-degree,
zero-extension responses.

This is a deterministic design-heuristic study, not a surrogate-model expansion.
Throat impedance is retained as a separate experimental diagnostic. It is not
part of surface score, ranking, parent selection, or the conditional-expansion
decision.

## Stage 3: fixed round-to-square mouth transformation

Retain the full 5×5 round-baseline domain as the eventual scope. Apply one
precisely defined round-to-square mouth transformation; do not search multiple
squareness controls in this stage. Allocate dense contrasts economically and
use locked full-domain transfer tests rather than redefining the supported
domain around a central sub-grid. Hold throat geometry, OSSE controls, OSSE
length, extension, and sag fixed in each paired contrast.

Reuse representative parents from Stage 2 where practical, including parents
with different diagnostic failure modes. Fit and validate a round-to-square
correction without conflating it with H/V aspect ratio. If that correction is
intended for the full round-baseline domain, apply the same four outer-corner
locked-sentinel policy: one matched round/square parent per corner first, followed
by added transforms or parents only in cells where transfer fails.

## Stage 4: separate horizontal and vertical behavior

First use a small elliptical-mouth bridge study. Ellipses vary horizontal and
vertical scale/coverage while retaining a smooth boundary, allowing H/V
anisotropy to be measured without simultaneously introducing rectangular
corners. This stage is a control experiment, not a search for an elliptical
product horn.

Test, in order:

1. independent H and V predictions derived from corresponding round cases;
2. those predictions plus a compact aspect-ratio correction;
3. an explicit H×V interaction only if held-out validation requires it.

If a sparse ellipse set validates the decomposition, stop expanding ellipses and
move to rectangular mouths. Then simulate matched rectangular cases to identify
the additional corner/round-to-square correction. If ellipse predictions fail,
expand only enough to characterize the missing H/V interaction before proceeding.

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
    + round-to-square correction
    + H/V aspect and coupling correction
    + sag and complementary-profile correction
```

Every correction must publish its training provenance, support domain,
diagnostic-specific validation error, uncertainty, and demonstrated interactions.
Unsupported interactions are omitted rather than filled by a broad brute-force
grid.
