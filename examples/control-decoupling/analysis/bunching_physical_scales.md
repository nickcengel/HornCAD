# Physical-scale energy-bunching analysis

Snapshot: `2026-07-23T01:46:15.314400+00:00`.

## Scope

This initial analysis found 127 retained NPZ archives and used 127 unique symmetric candidates. It tests whether the dominant interior positive peak and negative trough become more stable when frequency is normalized by a measured physical length.

A small collapse error is screening evidence, not proof of a resonance or causal mechanism. Matched one-control shifts are the stronger test; later completed canonical candidates serve as prospective validation.

## Positive-peak dimensionless collapse

| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| mouth radius | 119 | 0.396 | 1.446 | -0.591 | -0.286 |
| mouth width | 119 | 0.396 | 1.446 | -0.591 | -0.286 |
| radial growth | 119 | 0.396 | 1.468 | -0.546 | -0.286 |
| wall path length | 119 | 0.489 | 1.625 | -0.246 | -0.150 |
| half radial growth from throat | 119 | 0.514 | 1.664 | -0.262 | -0.164 |
| termination 10 from throat | 119 | 0.602 | 2.013 | 0.151 | 0.109 |
| termination 50 from throat | 119 | 0.637 | 1.962 | 0.159 | 0.105 |
| termination 90 from throat | 119 | 0.638 | 1.939 | 0.159 | 0.106 |

## Negative-trough dimensionless collapse

| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| osse length | 126 | 0.368 | 1.560 | -0.398 | -0.283 |
| termination 90 from throat | 126 | 0.369 | 1.561 | -0.398 | -0.277 |
| termination 50 from throat | 126 | 0.381 | 1.578 | -0.390 | -0.272 |
| termination 50 to mouth | 126 | 0.420 | 1.688 | -0.276 | -0.346 |
| termination 10 from throat | 126 | 0.420 | 1.518 | -0.327 | -0.245 |
| termination 90 to mouth | 126 | 0.423 | 1.613 | -0.323 | -0.344 |
| half radial growth to mouth | 126 | 0.442 | 1.712 | -0.406 | -0.577 |
| wall path length | 126 | 0.476 | 1.517 | -0.349 | -0.166 |

An inverse-length mechanism predicts an F–length slope near -1. Collapse rank alone is insufficient when a scale is correlated with mouth, coverage, or OSSE length. The matched translation below aligns the full curve, so it tests peaks and troughs together without assuming that one dominant extremum keeps the same identity.

## Matched one-control shifts

### length_mm

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mouth radius | 21 | 16 | 0.385 | 0.385 | 0.000 | 25.5% |
| mouth width | 21 | 16 | 0.385 | 0.385 | 0.000 | 25.5% |
| radial growth | 21 | 16 | 0.385 | 0.385 | 0.000 | 25.5% |
| diameter at max curvature | 21 | 16 | 0.389 | 0.385 | -0.003 | 25.5% |
| wall path length | 21 | 16 | 0.399 | 0.385 | -0.014 | 25.5% |
| half radial growth from throat | 21 | 16 | 0.463 | 0.385 | -0.078 | 25.5% |

### k

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| half radial growth to mouth | 13 | 10 | 0.217 | 0.385 | 0.168 | 25.6% |
| mouth radius | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| mouth width | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| osse length | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| radial growth | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| termination 10 from throat | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |

### n

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| diameter at max curvature | 6 | 6 | 0.039 | 0.089 | 0.049 | 11.0% |
| half radial growth to mouth | 6 | 6 | 0.060 | 0.089 | 0.029 | 11.0% |
| max curvature from throat | 6 | 6 | 0.087 | 0.089 | 0.001 | 11.0% |
| mouth radius | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |
| mouth width | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |
| osse length | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |

## Interpretation gate

Promote a scale from *association* to *supported* only when it improves matched-pair shift prediction over the no-shift baseline, the full curve aligns materially better after translation, the result repeats across independent mouth/coverage cells, and predicts candidates completed after this snapshot. Endpoint peaks and troughs are retained in the JSON but excluded from the dominant-feature fits because their true extrema may lie outside the simulated band.

The complete candidate peaks, troughs, physical scales, method constants, and all association rows are retained in `bunching_physical_scales.json`.
