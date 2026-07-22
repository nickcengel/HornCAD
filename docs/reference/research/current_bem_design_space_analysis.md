# Current BEM design-space analysis

Snapshot through `2026-07-22T11:32:13.120292-07:00`. This analysis is **provisional** and can be regenerated as solves finish.

## Evidence inventory

- 839 unique scored physical designs across 36 mouth/coverage cells.
- Search states: cancelled: 3, complete: 122, geometry-rejected: 7, running: 2.
- Study program: `domain-map-batch-1` (running).
- S-closure certificate: complete; closed: 31, geometry-limited: 5.
- Candidate counts by coverage half-angle: 25°: 121, 30°: 40, 35°: 91, 40°: 97, 45°: 289, 50°: 201.

The counts are evidence density, not evidence quality. Cross-angle conclusions remain provisional while the study program is running; expected geometry rejections describe the admissible design boundary rather than missing solver evidence.

## Controlled adjacent effects

Positive score deltas mean increasing the named control improved the surface score. For error diagnostics, negative deltas are improvements. S comparisons hold K and N fixed; K comparisons hold physical length and N fixed; N comparisons hold physical length and K fixed.

| Increase | Pairs | Score improves | Median score Δ | Containment Δ | Profile RMS Δ dB | Slice-energy Δ dB | Outward-rise Δ dB | -6 dB RMS Δ deg | Bunching shift oct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
- Running: `30deg/250x250-domain-map-b01` — BEM evaluation candidate-001; 1/2 candidates complete; 10 solver workers.
- Running: `30deg/300x300-domain-map-b01` — BEM evaluation candidate-000; 0/2 candidates complete; 10 solver workers.
| S | 514 | 32% | -0.49 | -0.45 | 0.041 | 0.028 | -0.020 | 0.27 | 0.000 |
| K | 232 | 59% | 0.06 | -0.06 | 0.003 | 0.018 | -0.068 | 0.28 | 0.000 |
| N | 259 | 45% | -0.02 | 0.04 | -0.002 | 0.001 | 0.001 | 0.07 | 0.000 |

These are aggregate directional summaries, not universal steering rules. A control can reverse sign by mouth, coverage, S, or the other OS-SE controls. The next pass must stratify matched effects by the starting diagnostic state before promoting a rule.

### Where the aggregate direction reverses

| Control increase | Starting regime | Pairs | Score improves | Median score Δ |
| --- | --- | ---: | ---: | ---: |
| S | coverage 30° | 33 | 18% | -1.94 |
| S | coverage 25° | 83 | 4% | -1.56 |
| S | S < 1 | 104 | 68% | 1.48 |
| S | coverage 35° | 61 | 16% | -1.17 |
| S | S ≥ 2 | 178 | 6% | -1.08 |
| S | coverage 40° | 66 | 35% | -0.97 |
| S | 1 ≤ S < 2 | 232 | 34% | -0.39 |
| S | coverage 45° | 161 | 43% | -0.08 |
| K | coverage 35° | 16 | 56% | 0.54 |
| K | high starting high_frequency_coverage_error_deg | 116 | 74% | 0.19 |
| K | coverage 25° | 15 | 40% | -0.19 |
| K | high starting outward_rise_violation_db | 116 | 72% | 0.13 |
| K | high starting profile_rms_error_db | 116 | 62% | 0.12 |
| K | low starting minus_six_rms_error_deg | 116 | 69% | 0.10 |
| K | high starting mean_containment | 116 | 61% | 0.07 |
| K | high starting slice_energy_departure_db | 116 | 57% | 0.07 |
| N | coverage 25° | 14 | 14% | -1.54 |
| N | coverage 35° | 16 | 25% | -0.68 |
| N | low starting mean_containment | 129 | 43% | -0.05 |
| N | high starting outward_rise_violation_db | 130 | 53% | 0.04 |
| N | low starting slice_energy_departure_db | 129 | 41% | -0.04 |
| N | low starting outward_rise_violation_db | 129 | 37% | -0.04 |
| N | low starting high_frequency_coverage_error_deg | 129 | 38% | -0.04 |
| N | low starting profile_rms_error_db | 129 | 40% | -0.03 |

This table is a screening device. Coverage/S regimes are descriptive, while splits on a starting diagnostic are hypotheses that still need repetition across independent mouth/coverage cells and held-out confirmation.

### Sampled K and N transitions

| Control | Transition | Pairs | Score improves | Median score Δ |
| --- | ---: | ---: | ---: | ---: |
| K | 3 → 3.5 | 6 | 83% | 2.33 |
| K | 3.5 → 3.75 | 3 | 100% | 0.60 |
| K | 3.5 → 4 | 21 | 86% | 1.03 |
| K | 3.75 → 4 | 15 | 100% | 0.14 |
| K | 4 → 4.25 | 29 | 59% | 0.07 |
| K | 4 → 4.5 | 26 | 58% | 0.22 |
| K | 4.25 → 4.5 | 26 | 58% | 0.01 |
| K | 4.25 → 4.75 | 1 | 100% | 1.12 |
| K | 4.5 → 4.75 | 22 | 50% | 0.00 |
| K | 4.5 → 5 | 18 | 44% | -0.10 |
| K | 4.75 → 5 | 21 | 29% | -0.02 |
| K | 4.75 → 5.25 | 2 | 100% | 1.07 |
| K | 5 → 5.25 | 15 | 53% | 0.05 |
| K | 5 → 5.5 | 7 | 57% | 0.14 |
| K | 5.25 → 5.5 | 11 | 36% | -0.03 |
| K | 5.25 → 5.75 | 2 | 100% | 0.50 |
| K | 5.5 → 5.75 | 4 | 25% | -0.05 |
| K | 5.5 → 6 | 2 | 50% | 0.06 |
| K | 5.75 → 6 | 1 | 0% | -0.18 |
| N | 2 → 5 | 6 | 100% | 14.82 |
| N | 2.5 → 5 | 4 | 100% | 9.92 |
| N | 2.5 → 7.5 | 3 | 100% | 10.20 |
| N | 3.75 → 6.25 | 4 | 100% | 3.47 |
| N | 3.75 → 8.75 | 5 | 100% | 4.28 |
| N | 5 → 5.5 | 3 | 100% | 0.31 |
| N | 5 → 6.25 | 9 | 100% | 0.94 |
| N | 5 → 7.5 | 4 | 100% | 1.85 |
| N | 5 → 10 | 23 | 48% | -0.22 |
| N | 5.5 → 6.25 | 3 | 100% | 0.22 |
| N | 6.25 → 6.5 | 12 | 100% | 0.09 |
| N | 6.25 → 6.75 | 2 | 100% | 0.09 |
| N | 6.25 → 7.5 | 5 | 100% | 0.57 |
| N | 6.25 → 8.75 | 2 | 100% | 0.62 |
| N | 6.5 → 7.5 | 12 | 75% | 0.16 |
| N | 6.75 → 7.5 | 2 | 100% | 0.11 |
| N | 6.75 → 7.75 | 1 | 100% | 0.02 |
| N | 7.5 → 7.75 | 11 | 100% | 0.04 |
| N | 7.5 → 8.5 | 9 | 0% | -0.07 |
| N | 7.5 → 8.75 | 6 | 33% | -0.14 |
| N | 7.5 → 10 | 3 | 100% | 0.26 |
| N | 7.5 → 12.5 | 3 | 0% | -1.05 |
| N | 7.75 → 8.75 | 12 | 67% | 0.04 |
| N | 8.5 → 8.75 | 9 | 0% | -0.04 |
| N | 8.75 → 9.75 | 9 | 11% | -0.06 |
| N | 8.75 → 10 | 17 | 6% | -0.32 |
| N | 8.75 → 11.25 | 2 | 0% | -0.31 |
| N | 8.75 → 13.75 | 5 | 0% | -0.81 |
| N | 9.75 → 10 | 9 | 11% | -0.02 |
| N | 10 → 10.25 | 3 | 100% | 0.01 |
| N | 10 → 11.25 | 7 | 0% | -0.24 |
| N | 10 → 12.5 | 9 | 0% | -0.67 |
| N | 10 → 13 | 1 | 0% | -1.62 |
| N | 10 → 15 | 21 | 0% | -1.71 |
| N | 10.25 → 11.25 | 3 | 67% | 0.02 |
| N | 11.25 → 12.25 | 3 | 0% | -0.04 |
| N | 11.25 → 13.75 | 4 | 0% | -0.69 |
| N | 12.25 → 12.5 | 3 | 0% | -0.01 |
| N | 12.5 → 15 | 4 | 0% | -0.71 |
| N | 13 → 15 | 1 | 0% | -1.12 |
| N | 15 → 20 | 5 | 0% | -1.38 |

The transition table is the current K/N conclusion: it is rebuilt from matched physical designs on every refresh. A direction is not promoted to a general rule until it repeats across independent mouth/coverage cells; later K/N results can therefore reverse an earlier provisional interpretation without leaving stale prose in this document.

## Phase 3 coupled-search audit

Across 10 coupled K/N rounds, 276 candidates were completed; 110 used quarter-step K values. At the selected winners, the median advantage over a measured nearby K choice at the same N was 0.050 points and the maximum was 0.140. That resolution did not change a practical design decision.

The coupled phase remains useful at coarse resolution: it showed that useful K and N move with length and are not fixed at the original K=4, N=10 seed. Future closure uses K steps no finer than 0.5, N steps no finer than 1, and hands off to local S/length when the measured neighborhood is within 0.5 score points.

| Coverage | Mouth | K/N rounds | First seed | Final score | Final S / L | Final K / N | Status |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 40° | 400 | 1 | 88.64 | 89.77 | 0.98 / 171.6 mm | 4.25 / 6.50 | converged |
| 45° | 350 | 2 | 88.30 | 88.63 | 1.37 / 128.8 mm | 4.00 / 7.75 | converged |
| 45° | 400 | 3 | 87.11 | 89.21 | 1.28 / 153.6 mm | 5.25 / 7.50 | converged |
| 50° | 250 | 1 | 87.70 | 87.73 | 1.72 / 89.8 mm | 4.00 / 11.25 | converged |
| 50° | 400 | 3 | 84.24 | 86.28 | 1.72 / 133.2 mm | 5.50 / 8.75 | practical-stop-unbracketed |

## Coverage and mouth/length trend

The current wide-coverage penalty is not a general loss of surface smoothness. Profile and slice-energy errors improve through the central angles, while outward-rise violation grows as the preferred horn becomes shorter relative to its mouth. This supports testing longer, higher-K wide horns, but does not yet establish a causal rule.

| Coverage | Cells | Median score | Mouth / length | Profile RMS dB | Slice-energy dB | Outward rise dB | -6 dB RMS deg |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25° | 6 | 80.99 | 1.269 | 1.589 | 1.202 | 0.170 | 9.87 |
| 30° | 6 | 85.30 | 1.567 | 1.410 | 0.975 | 0.224 | 8.27 |
| 35° | 6 | 86.06 | 1.916 | 1.362 | 0.795 | 0.515 | 6.27 |
| 40° | 6 | 87.02 | 2.316 | 1.309 | 0.749 | 0.544 | 5.40 |
| 45° | 6 | 86.86 | 2.663 | 1.267 | 0.788 | 0.733 | 5.49 |
| 50° | 6 | 86.52 | 3.279 | 1.283 | 0.788 | 1.038 | 6.27 |

## Phase 4 remote-sample value

Assessment: **insufficient distributed evidence**. 11 remote candidates are complete; median score change from the pre-Phase-4 cell incumbent is -12.85 points and median normalized distance from pre-Phase-4 evidence is 0.672. Boundary confirmations are useful until a distributed stratum is established; later repetition in that stratum should be skipped.

| Remote stratum | Complete | Angles | Competitive | Diagnostic tradeoffs | Boundary confirmations | Median score Δ | Recommendation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| K≈1 / N≈2 corner | 6 | 2 | 0 | 0 | 6 | -25.18 | collect distributed sentinels |
| K≈7 / N≈20 corner | 5 | 1 | 0 | 0 | 5 | -9.75 | collect distributed sentinels |

## Fixed K=4, N=10 S evidence

36 mouth/coverage cells currently have fixed K=4, N=10 evidence; 4 have their measured winner on an observed S endpoint. An endpoint winner is unresolved unless the study metadata establishes that the endpoint is a deliberate terminal sentinel rather than an unfinished boundary.

| Coverage | Mouth | Samples | S extent | Best S | Best L mm | Score | Endpoint winner |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 25° | 250 | 15 | 0.50–3.00 | 0.70 | 198.9 | 70.96 | no |
| 25° | 300 | 18 | 0.40–4.15 | 0.40 | 263.3 | 75.30 | yes |
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
| 35° | 250 | 11 | 0.19–1.90 | 0.70 | 153.4 | 79.74 | no |
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
| 45° | 350 | 22 | 0.50–3.00 | 1.99 | 125.0 | 88.30 | no |
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

1. Complete four remote zero-extension candidates in every mouth/coverage cell.
2. Test whether longer, higher-K wide-coverage candidates reduce outward-rise without losing containment.
3. Test whether diagnostic-conditioned directions repeat across independent cells.
4. Compare absolute and length/mouth-normalized bunching frequencies to identify which physical scale moves each frequency feature.
5. Freeze completed results as training evidence and use later completions as held-out checks before any steering rule is labeled supported.

Generated by `app/tools/analyze_bem_design_space.py`; do not edit this snapshot by hand.
