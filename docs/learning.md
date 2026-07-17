# Horn Learning Log

This document tracks the design questions we are trying to answer, the
provisional answers we have so far, and the experiments meant to turn those
answers into practical rules of thumb.

## Current Study Context

- The active mouth-size/length survey lives in
  `examples/mouth-size-length-survey`.
- That survey holds intended coverage at 45 x 45 deg, OS-SE coverage at
  45 x 45 deg, K at 4, conical extension at 0 mm, and sweeps 500-8000 Hz with a
  750 Hz crossover.
- It varies round mouth size, horn length, and N. The goal is to isolate the
  first-order mouth-size/length relationship before doing broader K/N searches.
- Candidate-search scoring is documented in `docs/plans/bem_candidate_search.md`.

## Diagnostic Direction

Question: how should the diagnostics better match subjective visual judgment?

Current answer:

The heatmap itself is the real object being judged. Rather than adding many
small independent metrics, the next diagnostic direction should turn the visual
rubric into measurements over the response matrix:

- red inside the intended coverage window is good
- red outside the window is bad
- uniform color inside the window is good
- strongest level near center, smoothly fading toward the coverage edge, is good
- positive off-axis regions inside the window are bad
- smooth shapes are good
- pointy, chaotic, or fragmented shapes are bad

Proposed metric family:

- Window Field Fit: compare the in-window response to a smooth target shape that
  falls from 0 dB on axis toward about -6 dB at the intended coverage edge.
- Outside Leakage: integrate excess level outside the intended window.
- Angular Monotonicity: penalize rises when walking outward from 0 deg toward
  the measured -6 dB point.
- 2D Field Smoothness: penalize high curvature, high-frequency residual, and
  narrow pointy artifacts over frequency and angle.
- Coverage Boundary Fit: keep a simpler version of the current -6 dB boundary
  fit.

The current Window Uniformity positive-zone penalty is a first step in this
direction, not the final form.

## Research Questions

### 1. Is there a best mouth-size / horn-length ratio for a given coverage angle?

Current answer:

Unknown. This is the main purpose of the mouth-size/length survey.

Working hypothesis:

For fixed coverage, there may be a useful region of mouth dimension divided by
horn length where coverage match, waistbanding, outside leakage, and field
smoothness all improve together. The useful region may be broad rather than a
single ratio.

Evidence so far:

Long horns can improve loading, but trying to use length alone creates problems:
it tends to force K higher to preserve intended coverage, and higher K tends to
narrow measured coverage. That makes length useful, but not independently
useful.

Next evidence needed:

Compare the fixed-K survey results by mouth size, length, N, solved S, waist
stability, field smoothness, and subjective best/worst labels.

### 2. Does the K sweet spot move with mouth size and horn length?

Current answer:

Probably yes, but it has not been isolated yet.

Working hypothesis:

K should be swept after promising and bad mouth-size/length regions are known.
The useful K range may shift, expand, or shrink depending on the mouth/length
geometry. High K can help tune coverage, but too much K appears to encourage
coverage narrowing. Low K has produced uneven response; K around 3 has felt like
a rough minimum viable region so far.

Next evidence needed:

Run focused K/N sweeps inside selected mouth/length regions instead of sweeping
K globally across every geometry.

### 3. Is solved S magnitude a reliable predictor?

Current answer:

Maybe. Treat S as a derived classifier first, not as a causal explanation.

Working hypothesis:

S may predict failure modes even if it is only a proxy for other geometry
relationships. It may correlate with:

- waistbanding
- rough or pointy in-window fields
- high-frequency narrowing
- mouth curvature severity
- geometry/mesh failures

Next evidence needed:

Plot objective and subjective outcomes against solved S while controlling for
mouth size, length, K, and N. Useful output would be a warning band such as
"avoid S below X" or "S above Y tends to produce Z failure."

### 4. Is there a best N for each K or S region?

Current answer:

There is probably a useful N plateau rather than a single best N.

Evidence so far:

Higher N generally gives smoother response and seems to reduce waistbanding.
However, higher N has diminishing returns and can create or reinforce a peak in
the upper octave region. Low N can be rougher, but very high N should not be
assumed better.

Next evidence needed:

For each promising mouth/length region, compare N at fixed K first. Then test
whether the best N range changes when K moves or when solved S changes.

### 5. Beyond increasing N, what can reduce waistbanding?

Current answer:

N helps, but it should not be the only lever.

Candidate levers:

- adjust horn length
- adjust mouth size
- adjust K
- bias OS-SE nominal coverage wider or narrower than intended coverage
- later, test conical extension after the higher-priority relationships are
  better understood

Important constraint:

A waistband fix only counts if it does not merely make the entire pattern worse.
The desired movement is less lower-band narrowing while preserving coverage
match, outside rejection, in-window field quality, and high-frequency retention.

### 6. Are coverage angles below and above 45 deg different regimes?

Current answer:

Unknown. Do not assume 45 deg is the real dividing line.

Working hypothesis:

There may be narrow, medium, and wide regimes, perhaps roughly:

- narrow: below 40 deg
- medium: 40-60 deg
- wide: above 60 deg

The dividing lines may move with crossover, mouth size, and length. Wide
coverage may need different mouth sizing or different K/N behavior than narrow
coverage, and the difference may be frequency-dependent.

Next evidence needed:

Once the 45 deg survey gives a useful rule of thumb, repeat smaller surveys at
other target coverages and test whether the rule scales or breaks.

## Calibration Data We Need

Subjective labels are valuable. For each run, collect:

- best 3 candidates by visual judgment
- worst 3 candidates by visual judgment
- reason tags, such as smooth, waist, outside leakage, off-axis positive zone,
  HF narrowing, rough/pointy, or poor boundary fit

Those labels should be used to calibrate experimental field-quality metrics
before promoting any new metric into the headline score.

## Target Form Of The Final Rules

The long-term goal is to turn the experiments into compact design guidance, for
example:

```text
For 45 deg coverage:
  mouth/length ratio: useful region A-B
  K range: useful region C-D
  N range: useful region E-F
  S warning region: avoid or investigate G-H
  common failure: X appears when Y is too high or Z is too low
```

The rules should be treated as provisional until tested against multiple
coverage angles.
