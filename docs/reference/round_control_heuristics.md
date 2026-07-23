# Round-control measured heuristics

## Purpose

This is the actionable learning deliverable from the completed round study. It
does not predict score. It converts mouth and coverage intent into measured
starting configurations and preserves observed alternate high-score zones.

The portable artifact is
`models/round_control_heuristics_v1/heuristics.json`. Its builder recomputes
every count below from retained evidence.

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
| 30° | 0.44 | 0.48 | 0.55 |
| 35° | 0.65 | 0.78 | 0.90 |
| 40° | 0.78 | 0.92 | 1.16 |
| 45° | 0.90 | 1.09 | 1.43 |
| 50° | 1.25 | 1.39 | 1.72 |

This is more useful than a universal K or length rule. When K or N changes,
solve length to preserve the interpolated coverage-level S seed, then measure
at least a small ±10% length bracket. Do not hold length fixed and sweep K
alone.

N remains a secondary branch control. Start near N=8. Use N=4 as the first
alternate when the measured nearest cell points that way. Do not spend an early
candidate on N=16.

## Alternate high-score zones

The study did find competitive regions away from the selected benchmarks.
Using a one-point score window and registered normalized L/K/N adjacency:

- 11 of 25 cells contain a measured multi-point competitive component outside
  the benchmark component;
- the measured best lies outside the benchmark component in 18 cells;
- nine cells beat their benchmark by more than one score point;
- the largest gaps are 40°/450 mm (+3.92), 50°/450 mm (+2.66),
  45°/450 mm (+2.33), and 35°/450 mm (+2.15).

This is evidence of real alternate zones, not merely model speculation.
However, every non-benchmark measured best is on a sampled L/K/N boundary. The
study therefore found these zones but did not prove their optima are bounded.
The artifact keeps multi-point zones separate from single-point boundary hints.

## H/V starting construction

For a non-round target, apply the round evidence independently to the horizontal
and vertical mouth/coverage pair:

1. Bilinearly interpolate the registered reference-length table.
2. Take L/K/N/S from the nearest measured cell winner as the axis seed.
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

For this example, the measured-axis seeds are approximately:

- horizontal: 140.92 mm, K=6, N=8;
- vertical: 144.26 mm, K=2, N=8;
- flat weighted compromise: 142.35 mm;
- alternative: 144.26 mm common length with 3.34 mm horizontal-only sag.

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
