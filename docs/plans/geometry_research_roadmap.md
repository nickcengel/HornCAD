# Geometry research roadmap

This roadmap defines how the round control model is extended into more complex
horn geometries. The objective is a sequence of interpretable, validated model
augmentations, not one Cartesian search over every available control.

## Geometry terminology

- **Length** always means the axial length of the OSSE profile.
- **Extension** is the separately authored conical throat extension length.
- **Sag distortion** is the axial length change introduced by mouth sag.
- **Total length** is OSSE length + extension + axial distortion from sag.

Length must never be renamed, redefined as total depth, or silently shortened to
compensate for extension or sag. Unless a registered contrast explicitly changes
more than one quantity, adding extension holds OSSE length fixed and increases
total length by the extension amount.

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

## Stage 1: finish the round control study

Finish, fit, and validate the symmetric zero-extension study already registered
under `examples/control-decoupling/`. Its portable model maps mouth, coverage,
OSSE length, K, and N to the component diagnostics and surface score while
reporting derived S. The validation and export requirements are defined in the
control study's
[model pipeline](../../examples/control-decoupling/model_pipeline.md).

This round baseline is frozen before any later geometry augmentation is fitted.

## Stage 2: conical extension and throat angle

The initial extension domain uses:

- coverage half-angles: 40 and 45 degrees;
- mouth sizes: 250, 300, and 350 mm;
- extension: 0, 20, 40, and 60 mm.

Use several deliberately different round-control parents per mouth/coverage
cell. For each paired extension contrast, hold the parent's OSSE length, S, K,
N, mouth, coverage, and throat angle fixed. Test withheld parent/extension
combinations and add simulations when the learned extension correction predicts
poorly.

Throat angle is a sparse registered factor within this stage:

- current throat angle;
- one lower throat angle;
- one higher throat angle.

**The lower and higher throat-angle values must be tested with zero throat
extension as well as with nonzero extension.** Throat angle is not to be treated
only as a property of the conical extension. Zero-extension contrasts identify
its direct effect on the OSSE horn; matched nonzero-extension contrasts identify
any throat-angle × extension interaction. Do not launch a full extension ×
throat-angle factorial unless these sparse contrasts demonstrate a material
interaction.

Throat impedance is an additional diagnostic output in this stage, not a
replacement for the radiation-surface diagnostics.

## Stage 3: fixed round-to-square mouth transformation

Use the same 40/45-degree and 250/300/350-mm domain. Apply one precisely defined
round-to-square mouth transformation; do not search multiple squareness controls
in this stage. Hold throat geometry, OSSE controls, OSSE length, extension, and
sag fixed in each paired contrast.

Reuse representative parents from Stage 2 where practical, including parents
with different diagnostic failure modes. Fit and validate a round-to-square
correction without conflating it with H/V aspect ratio.

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
