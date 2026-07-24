# BEM surface diagnostics

This document specifies the implemented surface-diagnostic suite for HornCAD
BEM angle-frequency reports. The raw measurements and calibrated weighted score
are used by current BEM search. Surface score v2.3 is the diagnostic of record
and the authoritative candidate-ranking score. V1 and v2.2 remain reproducible
historical fields. The released round-control models still predict their
documented frozen v1 response; that model target is not silently relabeled.

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

The contour-forward branch used by experimental revisions v2.1 and v2.2 has
these component weights:

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

### Narrow-coverage correction

The subsequent blinded v1/v2 comparison contained 31 comparisons at 25 degrees,
25 of which had a non-tie preference. Original v2 agreed with 13 of 25 (52%);
v1 agreed with 19 of 25 (76%). Inspection showed that contour-forward v2 was
over-tolerant of smooth, full-band displacement from the intended coverage
line in this narrow cell.

Revision v2.1 therefore blends the v1 and contour-forward v2 plane scores below
30 degrees. The retained v2 fraction is 20% through 25 degrees, rises linearly
to 100% at 30 degrees, and remains 100% above 30 degrees. Equivalently, the
25-degree effective weights are 30% profile, 24% slice energy, 17%
containment, 13% outward rise, 8% full-band -6 dB target accuracy, and 8%
three-contour quality. This is the largest tested v2 fraction that retained the
best observed 25-degree agreement. It raises agreement to 19 of 25 without
changing scores at the existing 30–50 degree cells.

This is calibration on the recorded comparison pairs, not independent
validation. The original v2 scores and selections remain frozen as evidence.

### Coverage-dependent correction in v2.2

The later 25-cell winner comparison exposed that v2.1 still over-selected
smooth but poorly targeted candidates in the 30–35 degree cells. All six cells
with identical v1 and v2.1 winners were marked tie. Among the 19 genuinely
different winners, the human choices were nine v1, four v2.1, and six ties.

V2.2 blends the v1 plane score with the contour-forward v2 plane score using
the coverage-dependent contour fraction

`0.20 + 0.45 * clip((coverage - 25) / 25, 0, 1) ** 2`.

The contour fractions at 25, 30, 35, 40, 45, and 50 degrees are respectively
0.200, 0.218, 0.272, 0.362, 0.488, and 0.650. This smooth rule fits all 13
decisive cell-winner preferences without cell-specific exceptions. It was
selected from a documented 5-by-6 family after checking the earlier pairwise
evidence. Agreement with those earlier 192 non-tie comparisons falls from
73.4% for original v2 to 65.6% for v2.2; that tradeoff is retained explicitly
because the cell-winner task is the intended optimization use.

V2.2 remains calibrated rather than independently validated and is retained as
the baseline inside v2.3.

### General-purpose guarded refinement in v2.3

V2.3 combines two complementary results from the completed ranking studies.
V2.2 retains stronger broad-range discrimination, while a four-component local
fit improves ordering among high-scoring candidates. The local fit cannot
stand alone because containment and outward-rise receive no weight in that
restricted population.

For each plane, v2.3 builds a local core from 40.8608% profile quality, 29.3908%
slice-energy stability, 10.7227% full-band -6 dB target accuracy, and 19.0257%
three-contour beamwidth quality. It applies one-sided soft guardrails below 75%
mean containment and below a 60% outward-rise component score:

`guarded_core = core * min(1, containment / 75) * min(1, outward_score / 60) ** 0.125`

The final result is `80% * v2.2 + 20% * guarded_core`. Consequently, v2.2's
continuous containment and outward-rise contributions remain present even
when neither explicit guardrail triggers. The result records both factors and
the names of any triggered guardrails.

Against the existing evidence, v2.3 changes broad mean Spearman from 0.902 to
0.898, close-score agreement from 0.402 to 0.491, and per-cell agreement from
0.546 to 0.579. Pairwise agreement changes from 89.1% to 88.7%, 66.7% to 70.0%,
and 70.8% to 72.5%, respectively. This satisfies the documented no-regression
tolerance in every population, but the same evidence participated in
calibration. On July 24, 2026, v2.3 was explicitly selected as the diagnostic
of record despite that validation limitation. It now replaces v1 for live
ranking; the limitation remains published rather than being erased. The
complete design and limitations are in
[`surface_diagnostic_v2_3.md`](../plans/surface_diagnostic_v2_3.md).

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
one; contour-forward remained the full-evidence validation choice. Against v1,
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
