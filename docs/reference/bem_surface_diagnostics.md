# BEM surface diagnostics

This document specifies the implemented surface-diagnostic suite for HornCAD
BEM angle-frequency reports. The raw measurements and calibrated weighted score
are used by current BEM search and by the released round-control models.

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

## 4. Retained -6 dB line diagnostic

The -6 dB crossing remains a secondary description rather than the primary
surface score. For each frequency record:

- measured -6 dB half-angle;
- signed error from intended coverage;
- missing-crossing state;
- local frequency-to-frequency movement of the crossing.

Summaries include RMS coverage error, RMS line movement, missing-crossing
fraction, worst error, and its frequency.

## Plane combination and final score

Horizontal and vertical raw results are reported separately. Combined raw
summaries use a geometric or root-mean-square combination appropriate to the
quantity; no left/right asymmetry diagnostic exists because the negative-angle
surface is a mirror.

The calibrated final score uses these component weights:

- 30% in-window profile RMS error;
- 25% slice-energy RMS departure;
- 20% mean containment;
- 15% outward-rise violation;
- 10% secondary -6 dB line error.

Mean containment contributes its percentage directly. Each error measurement
uses `100 / (1 + (error / reference)^2)`, which gives 100 at zero error and 50
at its reference value. Reference values are 3 dB for profile RMS, 2 dB for
slice-energy departure, 2 dB for outward rise, and 20 degrees for the -6 dB
line. Missing -6 dB crossings reduce that component in direct proportion to
the missing fraction. Horizontal and vertical scores are combined using mouth
width and height respectively. The worst one-third-octave containment summary
remains internal and does not contribute to the score or public reports.

## Validation

Synthetic surfaces must cover:

- the ideal linear in-window profile;
- energy spilling outside the coverage window;
- an isolated out-of-window lobe;
- in-window angular ripple and outward rises;
- frequency-dependent beam narrowing;
- uniform, bunched, and depleted slice-energy traces;
- smooth, wandering, and missing -6 dB crossings.

Regression tests cover frequency decimation and angular resampling stability.

The completed round study applying this score is specified in
[`examples/control-decoupling/study_plan.md`](../../examples/control-decoupling/study_plan.md).
Earlier empirical trends are preserved as historical evidence in the
[documentation archive](../archive/pre-control-decoupling-2026-07/README.md).
