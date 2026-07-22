# Current BEM design-space analysis

Snapshot through `2026-07-21T19:46:41.396626-07:00`. This analysis is **provisional** and can be regenerated as solves finish.

## Evidence inventory

- 467 unique scored physical designs across 36 mouth/coverage cells.
- Search states: complete: 58, running: 1.
- Candidate counts by coverage half-angle: 25°: 105, 30°: 27, 35°: 88, 40°: 63, 45°: 109, 50°: 75.

The counts are evidence density, not evidence quality. Incomplete 30° work and unfinished closure studies must not yet be used for final cross-angle recommendations.

## Controlled adjacent effects

Positive score deltas mean increasing the named control improved the surface score. For error diagnostics, negative deltas are improvements. S comparisons hold K and N fixed; K comparisons hold physical length and N fixed; N comparisons hold physical length and K fixed.

| Increase | Pairs | Score improves | Median score Δ | Containment Δ | Profile RMS Δ dB | Slice-energy Δ dB | Outward-rise Δ dB | -6 dB RMS Δ deg | Bunching shift oct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S | 361 | 34% | -0.61 | -0.60 | 0.047 | 0.022 | -0.001 | 0.42 | 0.000 |
| K | 47 | 55% | 0.25 | -0.18 | -0.017 | 0.016 | -0.149 | 0.27 | 0.000 |
| N | 46 | 28% | -1.06 | 0.12 | 0.010 | 0.076 | 0.008 | 0.40 | 0.000 |

These are aggregate directional summaries, not universal steering rules. A control can reverse sign by mouth, coverage, S, or the other OS-SE controls. The next pass must stratify matched effects by the starting diagnostic state before promoting a rule.

### Where the aggregate direction reverses

| Control increase | Starting regime | Pairs | Score improves | Median score Δ |
| --- | --- | ---: | ---: | ---: |
| S | S < 1 | 78 | 72% | 1.97 |
| S | coverage 30° | 21 | 14% | -1.85 |
| S | coverage 25° | 77 | 0% | -1.70 |
| S | coverage 35° | 58 | 16% | -1.31 |
| S | S ≥ 2 | 135 | 6% | -1.15 |
| S | coverage 40° | 57 | 37% | -0.88 |
| S | coverage 50° | 69 | 65% | 0.88 |
| S | 1 ≤ S < 2 | 148 | 39% | -0.50 |
| K | high starting outward_rise_violation_db | 24 | 83% | 1.08 |
| K | high starting profile_rms_error_db | 24 | 67% | 0.98 |
| K | high starting high_frequency_coverage_error_deg | 24 | 79% | 0.90 |
| K | high starting mean_containment | 24 | 71% | 0.73 |
| K | low starting minus_six_rms_error_deg | 23 | 74% | 0.58 |
| K | coverage 35° | 16 | 56% | 0.54 |
| K | coverage 45° | 16 | 69% | 0.51 |
| K | high starting slice_energy_departure_db | 24 | 50% | 0.32 |
| N | coverage 25° | 14 | 14% | -1.54 |
| N | low starting minus_six_rms_error_deg | 23 | 22% | -1.46 |
| N | low starting slice_energy_departure_db | 23 | 22% | -1.41 |
| N | high starting high_frequency_coverage_error_deg | 23 | 39% | -1.37 |
| N | low starting outward_rise_violation_db | 23 | 4% | -1.21 |
| N | low starting mean_containment | 23 | 22% | -1.11 |
| N | low starting profile_rms_error_db | 23 | 22% | -1.11 |
| N | high starting profile_rms_error_db | 23 | 35% | -1.01 |

This table is a screening device. Coverage/S regimes are descriptive, while splits on a starting diagnostic are hypotheses that still need repetition across independent mouth/coverage cells and held-out confirmation.

### Sampled K and N transitions

| Control | Transition | Pairs | Score improves | Median score Δ |
| --- | ---: | ---: | ---: | ---: |
| K | 3 → 3.5 | 6 | 83% | 2.33 |
| K | 3.5 → 4 | 17 | 82% | 0.97 |
| K | 4 → 4.5 | 18 | 39% | -0.12 |
| K | 4.5 → 5 | 6 | 0% | -0.57 |
| N | 2 → 5 | 6 | 100% | 14.82 |
| N | 5 → 10 | 18 | 39% | -0.57 |
| N | 10 → 15 | 17 | 0% | -1.46 |
| N | 15 → 20 | 5 | 0% | -1.38 |

The current K evidence describes a broad crest near K=4: increases below 4 are usually helpful, while increases above 4 are usually harmful. The current N evidence rejects N=2, but does not support continuing upward past 10: N=2→5 is strongly helpful, N=5→10 is mixed, and every measured transition above 10 is harmful. These statements apply only to the mouth/coverage/S regimes represented by the matched pairs.

## Fixed K=4, N=10 S evidence

36 mouth/coverage cells currently have fixed K=4, N=10 evidence; 11 have their measured winner on an observed S endpoint. An endpoint winner is unresolved unless the study metadata establishes that the endpoint is a deliberate terminal sentinel rather than an unfinished boundary.

| Coverage | Mouth | Samples | S extent | Best S | Best L mm | Score | Endpoint winner |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 25° | 250 | 14 | 0.70–3.00 | 0.70 | 198.9 | 70.96 | yes |
| 25° | 300 | 17 | 0.70–4.15 | 0.70 | 234.4 | 74.96 | yes |
| 25° | 350 | 14 | 0.70–4.12 | 0.70 | 269.3 | 79.11 | yes |
| 25° | 400 | 15 | 0.70–4.13 | 0.70 | 303.8 | 82.64 | yes |
| 25° | 450 | 11 | 0.70–4.10 | 0.70 | 338.0 | 83.57 | yes |
| 25° | 500 | 12 | 0.70–4.06 | 0.70 | 372.1 | 81.90 | yes |
| 30° | 250 | 5 | 0.70–1.90 | 0.70 | 174.4 | 75.78 | yes |
| 30° | 300 | 5 | 0.70–1.90 | 0.70 | 205.2 | 80.58 | yes |
| 30° | 350 | 5 | 0.70–1.90 | 0.70 | 235.5 | 84.69 | yes |
| 30° | 400 | 5 | 0.70–1.90 | 1.00 | 242.7 | 85.90 | no |
| 30° | 450 | 5 | 0.70–1.90 | 1.00 | 270.1 | 87.46 | no |
| 30° | 500 | 2 | 0.70–1.00 | 1.00 | 297.3 | 86.23 | yes |
| 35° | 250 | 10 | 0.19–1.90 | 0.70 | 153.4 | 79.74 | no |
| 35° | 300 | 11 | 0.70–3.48 | 0.70 | 180.3 | 84.53 | yes |
| 35° | 350 | 10 | 0.70–3.41 | 1.00 | 191.0 | 86.50 | no |
| 35° | 400 | 11 | 0.70–3.39 | 1.30 | 200.0 | 88.23 | no |
| 35° | 450 | 11 | 0.70–3.33 | 1.30 | 222.6 | 88.02 | no |
| 35° | 500 | 11 | 0.70–3.27 | 1.30 | 245.0 | 85.62 | no |
| 40° | 250 | 15 | 0.50–3.75 | 1.00 | 125.6 | 83.48 | no |
| 40° | 300 | 15 | 0.50–4.00 | 1.00 | 147.7 | 87.43 | no |
| 40° | 350 | 8 | 0.50–2.25 | 1.50 | 152.1 | 88.32 | no |
| 40° | 400 | 7 | 0.50–2.25 | 1.50 | 171.6 | 88.64 | no |
| 40° | 450 | 9 | 0.50–2.50 | 1.75 | 181.7 | 86.61 | no |
| 40° | 500 | 9 | 0.50–2.50 | 1.75 | 200.1 | 85.38 | no |
| 45° | 250 | 15 | 0.50–4.00 | 1.25 | 105.8 | 86.14 | no |
| 45° | 300 | 13 | 0.70–2.50 | 1.67 | 115.0 | 87.57 | no |
| 45° | 350 | 15 | 0.70–2.80 | 1.99 | 125.0 | 88.30 | no |
| 45° | 400 | 14 | 0.63–2.80 | 1.90 | 143.1 | 87.11 | no |
| 45° | 450 | 14 | 0.57–3.00 | 2.20 | 151.6 | 85.11 | no |
| 45° | 500 | 14 | 0.53–3.00 | 2.20 | 166.9 | 83.87 | no |
| 50° | 250 | 10 | 0.50–2.75 | 1.50 | 89.8 | 87.70 | no |
| 50° | 300 | 12 | 0.50–3.25 | 2.25 | 93.9 | 87.27 | no |
| 50° | 350 | 13 | 0.50–3.50 | 2.50 | 104.1 | 86.76 | no |
| 50° | 400 | 14 | 0.50–3.75 | 2.50 | 117.4 | 84.24 | no |
| 50° | 450 | 13 | 0.50–3.50 | 2.75 | 126.3 | 82.57 | no |
| 50° | 500 | 13 | 0.50–3.50 | 2.75 | 139.1 | 80.90 | no |

## Immediate next analysis

1. Test whether the provisional K≈4 and N≈5–10 crest repeats across independent cells.
2. Test whether diagnostic-conditioned directions repeat across independent cells.
3. Compare absolute and length/mouth-normalized bunching frequencies to identify which physical scale moves each frequency feature.
4. Freeze completed results as training evidence and use later completions as held-out checks before any steering rule is labeled supported.

Generated by `app/tools/analyze_bem_design_space.py`; do not edit this snapshot by hand.
