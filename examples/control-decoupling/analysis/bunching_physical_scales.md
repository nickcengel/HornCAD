# Physical-scale energy-bunching analysis

Snapshot: `2026-07-23T02:04:30.128639+00:00`.

## Scope

This analysis found 134 retained NPZ archives and used 134 unique symmetric candidates. It tests whether the dominant interior positive peak and negative trough become more stable when frequency is normalized by a measured physical length.

A small collapse error is screening evidence, not proof of a resonance or causal mechanism. Matched one-control shifts are the stronger test; later completed canonical candidates serve as prospective validation.

## Positive-peak dimensionless collapse

| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| minimum curvature radius | 126 | 0.295 | 1.184 | -0.636 | -0.548 |
| radial growth | 126 | 0.395 | 1.459 | -0.609 | -0.316 |
| mouth width | 126 | 0.396 | 1.441 | -0.660 | -0.316 |
| mouth radius | 126 | 0.396 | 1.441 | -0.660 | -0.316 |
| diameter at max area flare | 126 | 0.419 | 2.950 | -0.281 | -0.417 |
| wall path length | 126 | 0.475 | 1.609 | -0.278 | -0.164 |
| half radial growth from throat | 126 | 0.521 | 1.724 | -0.248 | -0.148 |
| max area flare from throat | 126 | 0.598 | 2.395 | -0.265 | -0.278 |

## Negative-trough dimensionless collapse

| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| mouth zone median area flare length | 133 | 0.370 | 1.492 | -0.456 | -0.463 |
| osse length | 133 | 0.409 | 1.561 | -0.386 | -0.262 |
| termination 90 from throat | 133 | 0.410 | 1.563 | -0.386 | -0.257 |
| termination 50 from throat | 133 | 0.413 | 1.568 | -0.381 | -0.254 |
| termination 10 from throat | 133 | 0.416 | 1.602 | -0.328 | -0.234 |
| minimum area flare length | 133 | 0.447 | 1.570 | -0.405 | -0.545 |
| termination 50 to mouth | 133 | 0.449 | 1.774 | -0.245 | -0.297 |
| termination 90 to mouth | 133 | 0.455 | 1.654 | -0.290 | -0.295 |

An inverse-length mechanism predicts an F–length slope near -1. Collapse rank alone is insufficient when a scale is correlated with mouth, coverage, or OSSE length. The matched translation below aligns the full curve, so it tests peaks and troughs together without assuming that one dominant extremum keeps the same identity.

## Linear-frequency extremum spacing

A round-trip or standing-wave mechanism more naturally predicts linear frequency spacing proportional to `1 / length` than it predicts one absolute peak frequency.

### adjacent extrema

| Physical scale | Candidates | MAD octaves | P10–P90 span | Spacing–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| radial growth | 126 | 0.172 | 1.895 | -0.162 | -0.336 |
| mouth width | 126 | 0.175 | 1.881 | -0.178 | -0.336 |
| mouth radius | 126 | 0.175 | 1.881 | -0.178 | -0.336 |
| diameter at max area flare | 126 | 0.222 | 2.315 | -0.324 | -0.478 |
| wall path length | 126 | 0.241 | 2.045 | 0.065 | -0.170 |
| half radial growth from throat | 126 | 0.363 | 2.043 | -0.071 | -0.153 |

### peak to peak

| Physical scale | Candidates | MAD octaves | P10–P90 span | Spacing–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| mouth radius | 72 | 0.141 | 1.854 | 0.937 | -0.033 |
| mouth width | 72 | 0.141 | 1.854 | 0.937 | -0.033 |
| radial growth | 72 | 0.152 | 1.888 | 0.873 | -0.033 |
| diameter at max area flare | 72 | 0.158 | 1.924 | 0.358 | 0.048 |
| wall path length | 72 | 0.232 | 1.793 | 0.669 | 0.131 |
| half radial growth from throat | 72 | 0.294 | 1.874 | 0.358 | 0.171 |

### trough to trough

| Physical scale | Candidates | MAD octaves | P10–P90 span | Spacing–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| mouth width | 97 | 0.124 | 1.003 | -0.061 | -0.325 |
| mouth radius | 97 | 0.124 | 1.003 | -0.061 | -0.325 |
| radial growth | 97 | 0.135 | 1.035 | -0.053 | -0.325 |
| diameter at max area flare | 97 | 0.142 | 1.116 | -0.129 | -0.352 |
| wall path length | 97 | 0.205 | 1.011 | 0.031 | -0.163 |
| half radial growth from throat | 97 | 0.322 | 1.134 | 0.021 | -0.120 |

The closest measured spacing slope to the inverse-length prediction is -0.405 for adjacent extrema versus minimum curvature radius. Thus, a small dimensionless MAD in these tables is not evidence for a simple standing-wave law when the fitted slope remains far from -1.

## Webster 1D reflection comparison

The lossless plane-wave Webster model is a mechanism screen, not BEM ground truth. A strong correspondence would support an axial impedance/reflection explanation; weak correspondence shifts attention toward aperture directivity or higher-order spatial behavior.

Candidates compared: 134. Median signed curve correlation: 0.547; median absolute correlation: 0.563. The fraction with absolute correlation at least 0.5 is 56.0%.

| BEM feature → Webster feature | Comparisons | Median distance oct | Within 1/6 oct |
| --- | ---: | ---: | ---: |
| positive peak → reflection peak | 125 | 0.146 | 61.6% |
| positive peak → reflection trough | 125 | 0.125 | 67.2% |
| negative trough → reflection peak | 132 | 0.146 | 59.8% |
| negative trough → reflection trough | 132 | 0.083 | 76.5% |

## Matched one-control shifts

### length_mm

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mouth radius | 24 | 18 | 0.333 | 0.333 | 0.000 | 22.9% |
| mouth width | 24 | 18 | 0.333 | 0.333 | 0.000 | 22.9% |
| radial growth | 24 | 18 | 0.333 | 0.333 | 0.000 | 22.9% |
| diameter at max curvature | 24 | 18 | 0.340 | 0.333 | -0.006 | 22.9% |
| minimum curvature radius | 24 | 18 | 0.363 | 0.333 | -0.029 | 22.9% |
| wall path length | 24 | 18 | 0.391 | 0.333 | -0.058 | 22.9% |

### k

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| half radial growth to mouth | 13 | 10 | 0.217 | 0.385 | 0.168 | 25.6% |
| minimum area flare length | 13 | 10 | 0.311 | 0.385 | 0.075 | 25.6% |
| mouth zone median area flare length | 13 | 10 | 0.323 | 0.385 | 0.063 | 25.6% |
| mouth radius | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| mouth width | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |
| osse length | 13 | 10 | 0.385 | 0.385 | 0.000 | 25.6% |

### n

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| diameter at max curvature | 6 | 6 | 0.039 | 0.089 | 0.049 | 11.0% |
| half radial growth to mouth | 6 | 6 | 0.060 | 0.089 | 0.029 | 11.0% |
| max curvature from throat | 6 | 6 | 0.087 | 0.089 | 0.001 | 11.0% |
| max area flare from throat | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |
| max area flare to mouth | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |
| mouth radius | 6 | 6 | 0.089 | 0.089 | 0.000 | 11.0% |

## Interpretation gate

Promote a scale from *association* to *supported* only when it improves matched-pair shift prediction over the no-shift baseline, the full curve aligns materially better after translation, the result repeats across independent mouth/coverage cells, and predicts candidates completed after this snapshot. Endpoint peaks and troughs are retained in the JSON but excluded from the dominant-feature fits because their true extrema may lie outside the simulated band.

The complete candidate peaks, troughs, physical scales, method constants, and all association rows are retained in `bunching_physical_scales.json`.
