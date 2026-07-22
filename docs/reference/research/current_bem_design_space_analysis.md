# Current BEM design-space analysis

Snapshot through `2026-07-22T01:07:52.600293-07:00`. This analysis is **provisional** and can be regenerated as solves finish.

## Evidence inventory

- 589 unique scored physical designs across 36 mouth/coverage cells.
- Search states: complete: 98, geometry-rejected: 7, running: 2.
- Study program: `coupled` (running).
- S-closure certificate: complete; closed: 29, geometry-limited: 7.
- Candidate counts by coverage half-angle: 25°: 110, 30°: 39, 35°: 90, 40°: 97, 45°: 172, 50°: 81.

The counts are evidence density, not evidence quality. Cross-angle conclusions remain provisional while the study program is running; expected geometry rejections describe the admissible design boundary rather than missing solver evidence.

## Controlled adjacent effects

Positive score deltas mean increasing the named control improved the surface score. For error diagnostics, negative deltas are improvements. S comparisons hold K and N fixed; K comparisons hold physical length and N fixed; N comparisons hold physical length and K fixed.

| Increase | Pairs | Score improves | Median score Δ | Containment Δ | Profile RMS Δ dB | Slice-energy Δ dB | Outward-rise Δ dB | -6 dB RMS Δ deg | Bunching shift oct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S | 426 | 34% | -0.55 | -0.60 | 0.043 | 0.021 | -0.006 | 0.38 | 0.000 |
| K | 89 | 55% | 0.06 | -0.10 | 0.002 | 0.018 | -0.086 | 0.28 | 0.000 |
| N | 90 | 38% | -0.24 | 0.07 | -0.003 | 0.015 | 0.000 | 0.16 | 0.000 |

These are aggregate directional summaries, not universal steering rules. A control can reverse sign by mouth, coverage, S, or the other OS-SE controls. The next pass must stratify matched effects by the starting diagnostic state before promoting a rule.

### Where the aggregate direction reverses

| Control increase | Starting regime | Pairs | Score improves | Median score Δ |
| --- | --- | ---: | ---: | ---: |
| S | coverage 30° | 33 | 18% | -1.94 |
| S | S < 1 | 95 | 73% | 1.82 |
| S | coverage 25° | 82 | 4% | -1.61 |
| S | coverage 35° | 60 | 15% | -1.20 |
| S | S ≥ 2 | 160 | 6% | -1.16 |
| S | coverage 40° | 66 | 35% | -0.97 |
| S | coverage 50° | 75 | 60% | 0.75 |
| S | 1 ≤ S < 2 | 171 | 39% | -0.40 |
| K | high starting high_frequency_coverage_error_deg | 45 | 80% | 0.58 |
| K | coverage 35° | 16 | 56% | 0.54 |
| K | high starting profile_rms_error_db | 45 | 60% | 0.25 |
| K | coverage 25° | 15 | 40% | -0.19 |
| K | high starting minus_six_rms_error_deg | 45 | 40% | -0.14 |
| K | high starting outward_rise_violation_db | 45 | 64% | 0.12 |
| K | low starting minus_six_rms_error_deg | 44 | 70% | 0.11 |
| K | low starting high_frequency_coverage_error_deg | 44 | 30% | -0.10 |
| N | coverage 25° | 14 | 14% | -1.54 |
| N | high starting slice_energy_departure_db | 45 | 36% | -0.75 |
| N | coverage 35° | 16 | 25% | -0.68 |
| N | high starting minus_six_rms_error_deg | 45 | 33% | -0.63 |
| N | high starting profile_rms_error_db | 45 | 42% | -0.54 |
| N | low starting outward_rise_violation_db | 45 | 24% | -0.54 |
| N | low starting mean_containment | 45 | 33% | -0.52 |
| N | high starting high_frequency_coverage_error_deg | 45 | 44% | -0.31 |

This table is a screening device. Coverage/S regimes are descriptive, while splits on a starting diagnostic are hypotheses that still need repetition across independent mouth/coverage cells and held-out confirmation.

### Sampled K and N transitions

| Control | Transition | Pairs | Score improves | Median score Δ |
| --- | ---: | ---: | ---: | ---: |
| K | 3 → 3.5 | 6 | 83% | 2.33 |
| K | 3.5 → 4 | 19 | 84% | 0.99 |
| K | 4 → 4.25 | 9 | 100% | 0.14 |
| K | 4 → 4.5 | 20 | 45% | -0.04 |
| K | 4.25 → 4.5 | 14 | 57% | 0.00 |
| K | 4.5 → 4.75 | 8 | 0% | -0.13 |
| K | 4.5 → 5 | 9 | 22% | -0.54 |
| K | 4.75 → 5 | 3 | 0% | -0.21 |
| K | 5 → 5.5 | 1 | 0% | -0.49 |
| N | 2 → 5 | 6 | 100% | 14.82 |
| N | 2.5 → 5 | 1 | 100% | 8.72 |
| N | 5 → 5.5 | 3 | 100% | 0.31 |
| N | 5 → 6.25 | 3 | 100% | 0.94 |
| N | 5 → 10 | 21 | 43% | -0.25 |
| N | 5.5 → 6.25 | 3 | 100% | 0.22 |
| N | 6.25 → 6.5 | 6 | 100% | 0.06 |
| N | 6.5 → 7.5 | 6 | 50% | 0.06 |
| N | 7.5 → 8.5 | 3 | 0% | -0.05 |
| N | 7.5 → 8.75 | 3 | 0% | -0.27 |
| N | 8.5 → 8.75 | 3 | 0% | -0.04 |
| N | 8.75 → 10 | 6 | 0% | -0.38 |
| N | 10 → 13 | 1 | 0% | -1.62 |
| N | 10 → 15 | 19 | 0% | -1.71 |
| N | 13 → 15 | 1 | 0% | -1.12 |
| N | 15 → 20 | 5 | 0% | -1.38 |

The transition table is the current K/N conclusion: it is rebuilt from matched physical designs on every refresh. A direction is not promoted to a general rule until it repeats across independent mouth/coverage cells; later K/N results can therefore reverse an earlier provisional interpretation without leaving stale prose in this document.

## Fixed K=4, N=10 S evidence

36 mouth/coverage cells currently have fixed K=4, N=10 evidence; 4 have their measured winner on an observed S endpoint. An endpoint winner is unresolved unless the study metadata establishes that the endpoint is a deliberate terminal sentinel rather than an unfinished boundary.

| Coverage | Mouth | Samples | S extent | Best S | Best L mm | Score | Endpoint winner |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 25° | 250 | 15 | 0.50–3.00 | 0.70 | 198.9 | 70.96 | no |
| 25° | 300 | 17 | 0.70–4.15 | 0.70 | 234.4 | 74.96 | yes |
| 25° | 350 | 16 | 0.30–4.12 | 0.50 | 290.3 | 80.08 | no |
| 25° | 400 | 17 | 0.30–4.13 | 0.50 | 327.3 | 83.04 | no |
| 25° | 450 | 11 | 0.70–4.10 | 0.70 | 338.0 | 83.57 | yes |
| 25° | 500 | 12 | 0.70–4.06 | 0.70 | 372.1 | 81.90 | yes |
| 30° | 250 | 7 | 0.50–3.00 | 0.70 | 174.4 | 75.78 | no |
| 30° | 300 | 7 | 0.50–3.00 | 0.70 | 205.2 | 80.58 | no |
| 30° | 350 | 7 | 0.50–3.00 | 0.70 | 235.5 | 84.69 | no |
| 30° | 400 | 6 | 0.70–3.00 | 1.00 | 242.7 | 85.90 | no |
| 30° | 450 | 6 | 0.70–3.00 | 1.00 | 270.1 | 87.46 | no |
| 30° | 500 | 6 | 0.70–3.00 | 1.00 | 297.3 | 86.23 | no |
| 35° | 250 | 10 | 0.19–1.90 | 0.70 | 153.4 | 79.74 | no |
| 35° | 300 | 11 | 0.70–3.48 | 0.70 | 180.3 | 84.53 | yes |
| 35° | 350 | 11 | 0.70–3.41 | 1.00 | 191.0 | 86.50 | no |
| 35° | 400 | 12 | 0.70–3.39 | 1.30 | 200.0 | 88.23 | no |
| 35° | 450 | 11 | 0.70–3.33 | 1.30 | 222.6 | 88.02 | no |
| 35° | 500 | 11 | 0.70–3.27 | 1.30 | 245.0 | 85.62 | no |
| 40° | 250 | 16 | 0.50–4.00 | 1.00 | 125.6 | 83.48 | no |
| 40° | 300 | 15 | 0.50–4.00 | 1.00 | 147.7 | 87.43 | no |
| 40° | 350 | 9 | 0.50–4.00 | 1.50 | 152.1 | 88.32 | no |
| 40° | 400 | 8 | 0.50–4.00 | 1.50 | 171.6 | 88.64 | no |
| 40° | 450 | 10 | 0.50–4.00 | 1.75 | 181.7 | 86.61 | no |
| 40° | 500 | 10 | 0.50–4.00 | 1.75 | 200.1 | 85.38 | no |
| 45° | 250 | 15 | 0.50–4.00 | 1.25 | 105.8 | 86.14 | no |
| 45° | 300 | 19 | 0.50–3.00 | 1.67 | 115.0 | 87.57 | no |
| 45° | 350 | 21 | 0.50–3.00 | 1.99 | 125.0 | 88.30 | no |
| 45° | 400 | 20 | 0.50–3.00 | 1.90 | 143.1 | 87.11 | no |
| 45° | 450 | 19 | 0.50–3.00 | 2.00 | 156.6 | 85.16 | no |
| 45° | 500 | 18 | 0.50–3.00 | 2.25 | 165.6 | 83.89 | no |
| 50° | 250 | 11 | 0.50–4.00 | 1.50 | 89.8 | 87.70 | no |
| 50° | 300 | 13 | 0.50–4.00 | 2.25 | 93.9 | 87.27 | no |
| 50° | 350 | 14 | 0.50–4.00 | 2.50 | 104.1 | 86.76 | no |
| 50° | 400 | 15 | 0.50–4.00 | 2.50 | 117.4 | 84.24 | no |
| 50° | 450 | 14 | 0.50–4.00 | 2.75 | 126.3 | 82.57 | no |
| 50° | 500 | 14 | 0.50–4.00 | 2.75 | 139.1 | 80.90 | no |

## Immediate next analysis

1. Test whether the strongest current K and N transition signals repeat across independent cells.
2. Test whether diagnostic-conditioned directions repeat across independent cells.
3. Compare absolute and length/mouth-normalized bunching frequencies to identify which physical scale moves each frequency feature.
4. Freeze completed results as training evidence and use later completions as held-out checks before any steering rule is labeled supported.

Generated by `app/tools/analyze_bem_design_space.py`; do not edit this snapshot by hand.
