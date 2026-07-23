# Physical-scale energy-bunching analysis

Snapshot: `2026-07-23T01:15:19.484327+00:00`.

## Scope

This initial analysis found 107 retained NPZ archives and used 107 unique symmetric candidates. It tests whether the dominant interior positive slice-energy departure becomes more stable when frequency is normalized by a measured physical length.

A small collapse error is screening evidence, not proof of a resonance or causal mechanism. Matched one-control shifts are the stronger test; later completed canonical candidates serve as prospective validation.

## Cross-candidate dimensionless collapse

| Physical scale | Candidates | MAD octaves | P10–P90 span | F–length slope | Spearman |
| --- | ---: | ---: | ---: | ---: | ---: |
| radial growth | 99 | 0.376 | 1.468 | -0.621 | -0.324 |
| mouth width | 99 | 0.387 | 1.446 | -0.673 | -0.324 |
| mouth radius | 99 | 0.387 | 1.446 | -0.673 | -0.324 |
| half radial growth from throat | 99 | 0.460 | 1.552 | -0.446 | -0.263 |
| wall path length | 99 | 0.462 | 1.592 | -0.386 | -0.226 |
| termination 10 from throat | 99 | 0.579 | 1.887 | 0.033 | 0.039 |
| osse length | 99 | 0.584 | 1.874 | 0.042 | 0.036 |
| termination 90 from throat | 99 | 0.585 | 1.874 | 0.042 | 0.036 |

An inverse-length mechanism predicts an F–length slope near -1. Collapse rank alone is insufficient when a scale is correlated with mouth, coverage, or OSSE length.

## Matched one-control shifts

### length_mm

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mouth radius | 17 | 14 | 0.396 | 0.396 | 0.000 | 25.5% |
| mouth width | 17 | 14 | 0.396 | 0.396 | 0.000 | 25.5% |
| radial growth | 17 | 14 | 0.396 | 0.396 | 0.000 | 25.5% |
| wall path length | 17 | 14 | 0.399 | 0.396 | -0.003 | 25.5% |
| diameter at max curvature | 17 | 14 | 0.418 | 0.396 | -0.022 | 25.5% |
| half radial growth from throat | 17 | 14 | 0.490 | 0.396 | -0.094 | 25.5% |

### k

| Physical scale | Pairs | Cells | Median shift error oct | No-shift error | Improvement | Alignment gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| half radial growth to mouth | 11 | 8 | 0.168 | 0.458 | 0.291 | 28.5% |
| max curvature from throat | 11 | 8 | 0.437 | 0.458 | 0.022 | 28.5% |
| mouth radius | 11 | 8 | 0.458 | 0.458 | 0.000 | 28.5% |
| mouth width | 11 | 8 | 0.458 | 0.458 | 0.000 | 28.5% |
| osse length | 11 | 8 | 0.458 | 0.458 | 0.000 | 28.5% |
| radial growth | 11 | 8 | 0.458 | 0.458 | 0.000 | 28.5% |

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

Promote a scale from *association* to *supported* only when it improves matched-pair shift prediction over the no-shift baseline, the full curve aligns materially better after translation, the result repeats across independent mouth/coverage cells, and predicts candidates completed after this snapshot. Endpoint peaks are retained in the JSON but excluded from the dominant-feature fits because their true maxima may lie outside the simulated band.

The complete candidate peaks, physical scales, method constants, and all association rows are retained in `bunching_physical_scales.json`.
