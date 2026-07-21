# BEM design trends and proposed studies

## Scope

This document records the design trends found by reviewing the scored BEM
results under `examples/` after introduction of the final surface score. The
review included 329 scored records representing 322 unique design signatures.
The useful study families were:

- 120 mouth-size / coverage / length candidates;
- 100 mouth-size / length / N candidates;
- 56 K / N field candidates;
- 53 rectangular OSSE records representing 50 unique parameter sets.

Standalone BEM/FEM reference runs were reviewed as verification artifacts but
were not treated as design sweeps. Repeated candidates in successive OSSE
rounds were deduplicated when inferring trends.

The square-horn studies provide controlled evidence. The rectangular OSSE
search changes several variables together, so its results are hypotheses to
test rather than general constraints.

## Main findings

### Relative length is the dominant controlled variable

Use mouth width divided by horn length as the relative-length quantity. Across
the 45-degree mouth-size / length survey, its Spearman correlation with final
surface score was +0.91 to +0.96 within each mouth size.

The useful relative-length region moves upward as the intended coverage
half-angle increases:

| Coverage half-angle | Observed useful mouth/length region | Confidence |
| --- | ---: | --- |
| 25 degrees | approximately 1.4 to 2.2 | low; ranges do not overlap across all mouths |
| 35 degrees | approximately 1.6 to 2.2 | moderate; larger-mouth optima hit a boundary |
| 45 degrees | approximately 2.6 to 3.0 | high within the sampled range |
| 60 degrees | at least 4.3 | low; every group improved to the upper boundary |

The simple seed rule `mouth/length = coverage_half_angle_degrees / 15` follows
the broad progression well enough to initialize a search. It is not a fitted
law and must not replace the coverage-specific bounds above.

Longer 45-degree horns slightly increased mean containment while degrading all
other surface measurements. From the shortest to longest sampled designs,
mean containment generally rose from about 89--91% to 92--94%, while final
score fell from about 80--87% to 44--54%. Profile RMS error, outward-rise
violation, slice-energy departure, and -6 dB line error all worsened. Mean
containment must therefore remain a supporting component rather than a length
selection objective by itself.

### K is strongly beneficial over the sampled square-horn range

The controlled 400 x 400 mm, 45-degree, 160 mm K/N field produced:

| K, N | Final surface score |
| --- | ---: |
| 1, 10 | 55.9% |
| 3, 7 | 80.5% |
| 4, 6 | 85.8% |
| 5, 7 | 88.8% |

K = 5 was the upper test boundary, so the location of the K optimum is still
unknown. Increasing K improved profile RMS, outward-rise behavior, slice-energy
stability, and -6 dB error while containment remained near 91%. This is a
surface-quality improvement rather than a containment artifact.

### Moderate N is preferable

The best N depended mildly on K, but the useful region was consistently N = 5
to 10 and most optima were N = 6 to 8. N = 2 was poor. N = 15 to 25 generally
lost score, especially in otherwise short, high-performing designs. At long
lengths the N effect became small because the length penalty dominated.

For new square searches, initialize N near 7, concentrate early samples from 5
through 10, and allocate few samples above 15 unless another variable changes
the observed interaction.

### Mouth size interacts with coverage and operating band

For 45-degree square designs over the 750--8000 Hz diagnostic band, the best
sampled scores were approximately:

| Mouth | Best score |
| --- | ---: |
| 300 mm | 87.8% |
| 350 mm | 88.3% |
| 400 mm | 87.3% |
| 450 mm | 85.9% |
| 500 mm | 84.0% |

This supports a 300--400 mm search focus for that target and band, but does not
establish a universal mouth-size constraint. The 35-degree series improved
toward larger mouths, while the 60-degree series declined as mouth size grew.
Some of that difference is confounded by incomplete relative-length ranges.

### The rectangular OSSE example favors a compact branch

For the 400 x 280 mm example targeting 50 degrees horizontal and 35 degrees
vertical:

| Candidate | Length | Score |
| --- | ---: | ---: |
| Seed | 300 mm | 78.1% |
| Compact target-oriented branch | 255 mm | 86.1% |
| Long target-oriented branch | 335 mm | 77.0% |

The best sampled construction parameters were 44/12-degree H/V construction
coverage, K = 35/5, and N = 5/5. The compact candidate improved both axes and
all important surface-error measurements without sacrificing containment.

This result is specific to the 400 x 280 geometry, fixed 50/35 operating
intent, 500--5000 Hz band, sag, and squareness settings. The search is too
sparse and coupled to turn those construction values into general constraints.

## Provisional search constraints

Use these only inside the conditions supported by the sample set:

- choose a coverage-dependent mouth/length range before optimizing secondary
  shape variables;
- for 45-degree square designs, begin with mouth/length from 2.5 to 3.1;
- extend 60-degree searches beyond mouth/length 4.3 before accepting an
  optimum;
- start K between 4 and 7, with explicit samples above the old K = 5 boundary;
- start N between 5 and 10 and concentrate on N = 6 to 8;
- deprioritize very long designs even when their mean containment is high;
- keep square and rectangular constraints separate;
- do not yet constrain extension, throat geometry, mouth sag, squareness, or
  aspect ratio from the existing evidence.

## Sampling blind spots

The existing data leave these important gaps:

- 25- and 35-degree larger mouths lack the lower mouth/length ratios sampled
  for smaller mouths;
- the 60-degree result improves to the shortest-length boundary everywhere;
- K above 5 is absent from the controlled square study;
- K, N, and relative length have not been studied as a controlled interaction;
- nonzero extension is sparse and confounded with unrelated variables;
- only one rectangular aspect ratio has an independent-axis search;
- throat radius, throat angle, mouth sag, squareness, and aspect ratio are
  effectively fixed within each controlled family;
- no identical design set establishes score sensitivity to crossover and
  upper diagnostic frequency;
- actual leading candidates have not all been confirmed at higher frequency,
  angular, and mesh resolution.

There are also 32 failed search candidates: 17 non-volume meshes, 14 solver or
remeshing aborts, and one mesh-resolution failure. Failures cluster around
short or extreme geometry. This is missing-not-at-random data near several
likely optima and must be resolved before the boundary trends are considered
complete.

## Proposed studies

### Study 1: complete the coverage / relative-length map

This is the highest-priority study. Use common dimensionless ranges rather
than different length sets for each mouth:

| Coverage half-angle | Proposed mouth/length range |
| --- | ---: |
| 25 degrees | 1.2 to 2.4 |
| 35 degrees | 1.4 to 2.6 |
| 45 degrees | 2.3 to 3.4 |
| 60 degrees | 3.8 to 5.2 |

Use steps of approximately 0.1 to 0.15. Begin with 250, 350, and 500 mm mouths
to detect mouth interaction efficiently, then fill the intermediate sizes.
Keep K and N fixed during the first pass; include existing K = 4, N = 10 points
as anchors. Repeat the most promising ratios with N = 7.

Primary output: an interior optimum or a justified expanded boundary for every
coverage and mouth.

### Study 2: extend and refine the K/N field

At 400 x 400 mm, 45 degrees, and a mouth/length ratio near 2.8, test:

- K = 4, 5, 6, 7, 8;
- N = 4, 5, 6, 7, 8, 10, 15.

The study must extend above K = 5 because the present optimum is censored by
that boundary. Retain the individual score components to determine whether K
eventually trades profile quality against another surface behavior.

Primary output: bounded K and N optima for a representative square geometry.

### Study 3: measure the K x N x length interaction

Take the best two or three K/N combinations from Study 2 and test them at
mouth/length ratios 2.5, 2.8, and 3.1. Repeat at 300 and 500 mm mouths after the
400 mm interaction is understood.

Primary output: whether the N = 6--8 preference and high-K benefit remain
stable when relative length and acoustic mouth size change.

### Study 4: controlled rectangular-axis response surface

Around the 400 x 280 compact candidate, perform a staged study using:

- length = 245, 255, 270, 285 mm;
- horizontal construction coverage = 40, 44, 48 degrees;
- vertical construction coverage = 8, 12, 16, 20 degrees;
- horizontal K = 25, 35, 50;
- vertical K = 3, 5, 10;
- H/V N centered on 4, 6, and 8.

Do not run the full Cartesian product initially. Use one-variable brackets
around the compact candidate, followed by a small response-surface design over
the variables that show measurable effects. Keep operating intent fixed at
50/35 degrees.

Primary output: independent H/V constraints and confirmation that the compact
result is not a coupled-search accident.

### Study 5: isolate extension

For a small set of high-scoring square and rectangular candidates, test 0, 10,
20, and 40 mm extension in two separate experiments:

1. hold horn-body length fixed;
2. hold total acoustic length fixed.

Primary output: whether extension has an independent surface benefit or merely
acts as added length.

### Study 6: fill geometry-family blind spots

After the preceding studies, vary one geometry family at a time:

- throat radius and throat angle;
- mouth sag;
- mouth squareness;
- aspect ratio, including at least 1.0, 1.2, 1.4, and 1.6;
- independent H/V construction parameters at multiple aspect ratios.

Primary output: determine which constraints transfer between square and
rectangular horns.

### Study 7: score and numerical robustness

Rerun leaders, near-leaders, and deliberately poor controls at higher points
per octave, denser angular sampling, and tighter mesh resolution. For identical
geometries, perturb crossover and upper diagnostic frequency to measure score
sensitivity to the evaluation band.

Primary output: a practical score-difference threshold below which candidates
should be considered tied, and confirmation that rankings are not numerical or
band-selection artifacts.

### Study 8: recover failed boundary samples

Diagnose the volume-mesh and remeshing failures, then rerun the failed short and
extreme candidates that lie near expanding search boundaries. Do not substitute
surrogate predictions for these points.

Primary output: remove missing-data bias from the most important boundary
conclusions.

## Recommended execution order

1. Recover failed boundary samples.
2. Complete the coverage / relative-length map.
3. Extend the K/N field above K = 5.
4. Measure the K x N x length interaction.
5. Run the compact rectangular response-surface study.
6. Isolate extension.
7. Fill broader geometry-family blind spots.
8. Confirm numerical and evaluation-band robustness throughout, with a final
   focused confirmation after each study identifies leaders.
