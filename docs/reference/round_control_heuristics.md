# Round-control measured heuristics

## Purpose

This is the actionable learning deliverable from the completed round study. It
does not predict score. It converts mouth and coverage intent into measured
starting configurations and preserves observed alternate high-score zones.

The portable artifact is
`models/round_control_heuristics_v1/heuristics.json`. Its builder recomputes
every count below from retained evidence. Exact-cell starting configurations
come from the current surface-score v2.3 winner map; the older v1 selections
remain only as historical audit evidence.

## Rules supported directly by the canonical factorial

At K=4/N=8, the registered reference length beat its available ±20% alternatives
in all 25 cells and all 49 direct comparisons. Its median score advantage was
6.40 points; the smallest was 2.01 points.

At reference length and N=8, K=4 beat K=2 and K=6 in all 25 cells. At reference
length and K=4, N=8 won 21 cells, N=4 won four, and N=16 won none.

These one-axis statements are not the whole result. Coordinated length/K changes
expose three useful measured branches:

- short/low-K: length factor 0.8, K=2, N=8;
- center: length factor 1.0, K=4, N=8;
- long/high-K: length factor 1.2, K=6, N=8.

The best of those three at each canonical cell is:

| Coverage | 250 mm | 300 mm | 350 mm | 400 mm | 450 mm |
|---|---|---|---|---|---|
| 30° | short/low-K | center | center | long/high-K | long/high-K |
| 35° | short/low-K | short/low-K | center | long/high-K | long/high-K |
| 40° | short/low-K | center | long/high-K | long/high-K | long/high-K |
| 45° | short/low-K | long/high-K | long/high-K | long/high-K | long/high-K |
| 50° | center | long/high-K | long/high-K | long/high-K | long/high-K |

Therefore length and K must not be optimized separately. The reference seed is
strong when K/N remain central, while a larger K should first carry a longer
profile and a smaller K should first carry a shorter one.

## What S adds

S makes the coupled branches physically legible. The S value of the measured
winner in each mouth cell falls in these coverage-dependent bands:

| Coverage | Minimum winner S | Median winner S | Maximum winner S |
|---|---:|---:|---:|
| 30° | 0.40 | 0.50 | 0.55 |
| 35° | 0.67 | 0.78 | 0.90 |
| 40° | 0.77 | 0.79 | 1.34 |
| 45° | 0.90 | 1.09 | 3.21 |
| 50° | 0.94 | 1.31 | 2.43 |

This is more useful than a universal K or length rule. When K or N changes,
solve length to preserve the interpolated coverage-level S seed, then measure
at least a small ±10% length bracket. Do not hold length fixed and sweep K
alone.

N remains a secondary branch control. Start near N=8. Use N=4 as the first
alternate when the measured nearest cell points that way. Do not spend an early
candidate on N=16.

## Alternate high-score zones and ridge closure

The study did find competitive regions away from the selected benchmarks.
Using a one-point score window and registered normalized L/K/N adjacency:

- 15 of 25 cells contain a measured multi-point competitive component outside
  the benchmark component;
- the measured best lies outside the benchmark component in 18 cells;
- nine cells beat their benchmark by more than one score point;
- the largest gaps are 40°/450 mm (+4.37), 50°/450 mm (+3.41),
  45°/450 mm (+3.32), and 35°/450 mm (+2.98).

This is evidence of real alternate zones, not merely model speculation.
The 48-case ridge-closure study then tested K=1 or K=7 at three nearby lengths
in 16 of these cells:

- 13 of 16 cells bracketed length at the tested outward K;
- the outward K beat compatible inner K=2/K=6 evidence in six cells;
- the inner K remained better in ten cells;
- six final measured cell seeds therefore move to ridge-closure evidence.

The six outward-K wins are useful registered-domain seeds, not proof of an
unconstrained optimum beyond K=1 or K=7. A three-case follow-up tested one
shorter length in each previously unbracketed K=1 cell. All three shorter cases
lost, so the K=1 short branch is now length-bracketed in every tested cell; no
conditional second step was needed. The artifact publishes these statuses per
cell and keeps multi-point zones separate from single-point hints.

The later ten-case
[wide-coverage closure](../plans/round_control_wide_coverage_closure.md)
tested the most valuable remaining L/K seams in selected 45° and 50° cells.
Its best gain was only 0.268 surface-v2.3 points. At 50°/450 mm, extending the
K=7/N=8 ridge from L=175.658 mm to 191.627 and 207.596 mm reduced score by
9.944 and 29.793 points. The two conditional infinite-baffle controls were
deliberately not run.

The leading working explanation for the residual wide-coverage deficit is
mouth-edge diffraction: wider coverage carries more acoustic energy to the lip,
and the principal disturbance follows an aperture-scaled frequency. This is a
working hypothesis consistent with measured scaling, not a demonstrated causal
separation. No
additional round-horn simulations are currently planned; the question carries
forward into intended non-round and baffle geometry.

## Extension and throat-angle initialization

The completed 6° composite extension map now contains 1,542 exact-response-
deduplicated zero-extension responses and 101 extension responses. Its
registered 75/25 surface/impedance composite retains zero extension in all 25
cells, including the 23-case S-recovery closure. Start at zero extension.

Extension remains a measured search branch, not a prohibited control. Four
cells have a measured extension whose surface-v2.3 gain exceeds 0.5 point even
though the impedance loss makes its composite worse: 30°/450 mm, 35°/350 mm,
40°/250 mm, and 50°/350 mm. A surface-first optimizer should therefore retain
extension proposals where local evidence or weak throat loading warrants them.

The matched A6/A8 extension grid improved throat impedance in 14 of 15
30°–40° cells, with a median 6.90-point gain. The four wide-coverage bridge
points also improved from A6 to A8. Treat these as matched initialization
evidence at their exact coordinates. The failed general throat-angle predictor
remains unreleased.

## H/V starting construction

For a non-round target, apply the round evidence independently to the horizontal
and vertical mouth/coverage pair:

1. Bilinearly interpolate the registered reference-length table.
2. Take L/K/N/S from the nearest surface-v2.3 measured cell winner, including
   ridge and wide-coverage closure evidence where it won, as the axis seed.
3. For a flat mouth, combine the two axis lengths using mouth width and height
   as weights, matching the surface-score plane weighting.
4. As an alternative, set the common length to the longer axis seed and apply
   cylindrical sag only to the shorter-length axis. In HornCAD geometry, sag
   equal to the length difference exactly reconciles the two principal mouth
   edges.

Step 4 is a geometric construction rule, not evidence that sag improves
acoustics. It produces a precise candidate worth comparing with the flat seed;
it is not labeled an optimized sag value.

Example:

```python
from app.design_api import (
    DesignIntent,
    RoundControlHeuristics,
)

rules = RoundControlHeuristics.load("models/round_control_heuristics_v1")
seed = rules.recommend(DesignIntent(400, 300, 50, 35))
```

`seed.extension_mm` is zero. The artifact also records exact cells where an
extension should be retained as an early surface-priority branch.

For this example, the measured-axis seeds are approximately:

- horizontal: 140.61 mm, K=5.5, N=8.75;
- vertical: 144.26 mm, K=2, N=8;
- flat weighted compromise: 142.17 mm;
- alternative: 144.26 mm common length with 3.64 mm horizontal-only sag.

If K/N are changed deliberately, preserve the S seed first:

```python
adjusted = rules.length_for_target_s(
    mouth_mm=400,
    coverage_deg=45,
    k=5,
    n=7,
)
```

The heuristic rejects mouth or coverage extrapolation beyond the measured 250–
450 mm and 30–50° domain.
