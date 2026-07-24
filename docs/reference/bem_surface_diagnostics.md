# BEM surface diagnostics

This document specifies the implemented surface-diagnostic suite for HornCAD
BEM angle-frequency reports. The raw measurements and calibrated weighted score
are used by current BEM search. Surface score v2 is active; the former
five-component score remains available as v1 for provenance and is still the
response predicted by the released round-control models.

## Scope and conventions

- Work independently on the horizontal and vertical principal-plane heat-map
  surfaces already produced by the solver.
- Use only angles from 0 through 90 degrees. The solved quadrant is reflected,
  so the negative-angle half is identical and its factor of two cancels from
  ratios.
- A configured coverage angle is a half-angle. The intended window is from
  `-coverage` through `+coverage`.
- Convert normalized level in dB to relative power with
  `power = 10 ** (level_db / 10)` before angular integration.
- Evaluate from crossover through the upper sweep frequency on a logarithmic
  frequency grid. Band summaries weight equal logarithmic-frequency spans
  equally.
- Do not infer spherical radiation or absolute radiated power. The input heat
  maps are normalized to 0 dB on axis at each frequency, so the energy values
  describe relative angular concentration.

## 1. Coverage-window containment

At each frequency, integrate relative power from 0 degrees to the intended
coverage half-angle and divide it by the relative power integrated from 0
through 90 degrees:

`containment(f) = inside_window_power(f) / total_angular_power(f)`

Record the full containment-versus-frequency trace and these summaries:

- log-frequency mean containment;
- minimum containment and its frequency;
- log-frequency mean containment deficit, where deficit is
  `1 - containment`;
- worst sustained containment over raw samples and moving windows of 1/12,
  1/6, 1/3, and 2/3 octave.

The moving-window results are retained separately so report review can show
which scale reliably identifies meaningful bad frequency regions.

## 2. In-window amplitude distribution

At each frequency, the reference profile inside the intended window is a
straight line in dB from 0 dB on axis to -6 dB at the coverage half-angle:

`ideal_db(angle) = -6 * angle / coverage`

Interpolate the measured angular response at the exact window boundary before
evaluation. Record frequency traces and band summaries for:

- RMS dB error from the reference profile;
- peak absolute dB error from the reference profile;
- outward-rise violation, measured from positive level changes as angle moves
  away from the axis.

The outward-rise measurement distinguishes a smooth profile offset from the
reference from a profile containing in-window lobes or reversals.

## 3. Angular slice-energy stability

At every frequency, integrate relative power across the available reflected
plane:

`slice_energy(f) = 2 * integral(power(f, angle), angle=0..90 degrees)`

The factor of two represents the mirrored -90 through 0 degree half. It does
not affect normalized stability results.

Normalize the slice-energy trace by its log-frequency geometric mean and
express the departure in dB. A perfectly stable surface produces a flat
0 dB departure trace. Record:

- RMS slice-energy departure in dB;
- largest positive departure and its frequency;
- largest negative departure and its frequency;
- peak-to-peak departure;
- RMS departure after moving averages of 1/12, 1/6, 1/3, and 2/3 octave.

The unsmoothed and multiscale results remain visible until retained-candidate
data establishes which frequency scale is appropriate.

## 4. Multiscale contour quality

At each frequency, follow the first outward-going -3, -6, and -9 dB crossings.
Their nominal half-angles under the linear target profile are respectively
`0.5 * coverage`, `coverage`, and `1.5 * coverage`. Divide each measured
half-angle by its nominal value before comparing cells.

Every contour records:

- absolute and normalized width traces;
- missing fraction and longest missing span;
- RMS ripple relative to moving means at 1/12, 1/6, 1/3, 2/3, 1, and 2 octave;
- low-frequency-to-high-frequency net trend;
- slope variation after removing that net trend;
- explanatory slope-reversal count;
- asymmetric local-narrowing deficit at every scale;
- upper-third-octave mean width and target error.

A centered moving mean reproduces a linear trace, so smooth global widening or
narrowing is not itself ripple. Slope variation penalizes bends and reversals.
The local-narrowing term adds a stronger penalty for dips below the local smooth
trace; widening still contributes to the symmetric ripple and trend terms.

High-frequency width receives full credit within ±10% of nominal. Only excess
outside that deadband is scored. Missing crossings multiply the contour score
through completeness rather than disappearing into an average.

Each contour score is the weighted geometric combination of:

- 30% multiscale ripple, with 0.12 normalized width as its reference;
- 25% trend complexity, with 0.36 width/octave as its reference;
- 30% local narrowing, with 0.18 normalized width as its reference;
- 15% high-frequency excess, with 0.45 normalized width as its reference.

The -3, -6, and -9 dB contour scores combine geometrically at 25%, 50%, and 25%.
The geometric combinations keep a serious localized failure from being hidden
by unrelated good averages.

The former -6 dB trace fields remain in JSON for compatibility, including RMS
target error and raw movement in degrees per octave.

## Plane combination and final score

Horizontal and vertical raw results are reported separately. Combined raw
summaries use a geometric or root-mean-square combination appropriate to the
quantity; no left/right asymmetry diagnostic exists because the negative-angle
surface is a mirror.

The active calibrated v2 score uses these component weights:

- 30% in-window profile RMS error;
- 20% slice-energy RMS departure;
- 5% mean containment;
- 5% outward-rise violation;
- 40% multiscale three-contour beamwidth quality.

Mean containment contributes its percentage directly. Each error measurement
uses `100 / (1 + (error / reference)^2)`, which gives 100 at zero error and 50
at its reference value. Reference values are 3 dB for profile RMS, 2 dB for
slice-energy departure and 2 dB for outward rise. Horizontal and vertical
scores are combined using mouth width and height respectively.

The legacy v1 score is retained beside v2. It weights profile error 30%,
slice-energy departure 25%, containment 20%, outward rise 15%, and -6 dB target
error 10%. It must not be relabeled as v2.

## Validation

Synthetic surfaces must cover:

- the ideal linear in-window profile;
- energy spilling outside the coverage window;
- an isolated out-of-window lobe;
- in-window angular ripple and outward rises;
- frequency-dependent beam narrowing;
- uniform, bunched, and depleted slice-energy traces;
- smooth, wandering, and missing -6 dB crossings.
- smooth global contour slopes;
- fine and broad contour ripple;
- equal-amplitude local narrowing and widening;
- independent -3 and -9 dB shoulder disturbances.

Regression tests cover frequency decimation and angular resampling stability.

The v2 release was calibrated against the completed 20-round, 200-plot blinded
human ranking experiment. The initial 1× reference pass selected the
preregistered contour-forward weighting in all 20 leave-one-round-out folds.
The final sensitivity pass selected contour-forward in 19 folds and balanced in
one; contour-forward remained the full-evidence release choice. Against v1,
mean broad-round Spearman agreement increased from 0.818 to 0.879; close-round
agreement increased from 0.052 to 0.459, with close-round pairwise agreement
increasing from 52.0% to 67.8%. The initial references correctly ordered
candidates but compressed real beamwidth-quality scores to 4–28%. The single
documented 1×–3× sensitivity pass selected 3× in 15 held-out folds, 1.5× in
four, and 1× in one; 3× was also the full-evidence selection. It restored an
interpretable 22–74% measured range without changing the metric definitions or
component weights. The frozen plan and complete
calibration output are in
[`surface_diagnostic_v2.md`](../plans/surface_diagnostic_v2.md) and the
[`surface-diagnostic-ranking-experiment`](../../examples/surface-diagnostic-ranking-experiment/README.md).

The completed round study applying this score is specified in
[`examples/control-decoupling/study_plan.md`](../../examples/control-decoupling/study_plan.md).
Earlier empirical trends are preserved as historical evidence in the
[documentation archive](../archive/pre-control-decoupling-2026-07/README.md).
