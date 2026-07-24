# Round-control wide-coverage closure

Status: completed after 10 initial candidates; conditional simulations declined

## Completion

All ten initial candidates completed successfully through the stage-aware
20-process scheduler. The best new result was the 50°/350 mm K=5.5 candidate:
surface score v2.3 increased from 80.522 to 80.790, a gain of only 0.268
points. This did not reach the preregistered 1.5-point threshold.

The 45°/350 mm incumbent remained bracketed. Extending the 50°/450 mm K=7,
N=8 ridge from L=175.658 mm / S=0.941 to:

- L=191.627 mm / S=0.562 reduced v2.3 by 9.944 points; and
- L=207.596 mm / S=0.238 reduced v2.3 by 29.793 points.

The project owner declined the two conditional infinite-baffle simulations on
July 24, 2026. They were not run and no substitutes were scheduled.

The leading provisional interpretation is mouth-edge diffraction: wider
coverage sends more energy to the lip, and the observed disturbance follows an
aperture-scaled frequency rather than a simple axial-length scale. The study
therefore stops round-horn sampling and carries the measured parameter map into
the intended non-round H/V, corner, sag, and baffle geometry work.

## Purpose

Determine whether the lower surface-score v2.3 performance in the large-mouth
45° and 50° round-control cells is caused by an incompletely closed L/K ridge
or by an aperture-scaled physical limitation of this axisymmetric, unbaffled
geometry class.

This is a bounded closure study, not a renewed global surrogate-model program.
Its results update measured heuristic seeds and mechanism evidence only.

## Existing evidence

The 50° winners show an outward-rise disturbance at nearly constant normalized
aperture frequency:

| Mouth | Worst outward-rise frequency | `f D / c` |
| ---: | ---: | ---: |
| 300 mm | 7.13 kHz | 6.23 |
| 350 mm | 5.99 kHz | 6.12 |
| 400 mm | 5.34 kHz | 6.23 |
| 450 mm | 4.76 kHz | 6.24 |

This favors a transverse/aperture or mouth-edge mechanism over a simple axial
length resonance. The initial study nevertheless closes the remaining
high-value L/K seams before promoting that interpretation.

## Initial design — 10 evaluations

All candidates retain the cell's round axisymmetric mouth, 6° throat angle,
zero extension, N=8, registered frequency grid, solver settings, and intended
coverage. S is derived and recorded for every coordinate.

| Cell | Incumbent | Initial probes |
| --- | --- | --- |
| 45° / 350 mm | L=150 mm, K=6, N=8 | L=142.5 and 157.5 at K=6; K=5.5 and 6.5 at L=150 |
| 50° / 350 mm | L=124.892 mm, K=6, N=8 | L=118.647 and 131.137 at K=6; K=5.5 and 6.5 at L=124.892 |
| 50° / 450 mm | L=175.658 mm, K=7, N=8 | L=191.627 and 207.596 at K=7 |

K=7 remains a hard upper bound. No K>7 candidate is authorized.

## Conditional allocation — at most 2 evaluations

Surface score v2.3 is the sole ranking and conditional-decision diagnostic.
Throat impedance and the 75/25 composite are reported but do not affect the
decision.

After all ten initial results:

1. If any candidate improves its current v2.3 cell winner by at least 1.5
   points, use at most two evaluations to confirm or bracket that measured
   direction.
2. Otherwise, use the two evaluations for a matched mechanism comparison of
   the 35°/450 mm and 50°/450 mm winners with an infinite planar baffle at the
   mouth plane. The comparison must retain aperture amplitude and phase when
   supported, as well as the normal surface and throat-impedance diagnostics.

If an equivalent infinite-baffle implementation cannot pass a same-geometry
preflight without changing the interior source or frequency definition, stop
at ten and record that limitation rather than substitute a non-equivalent
simulation.

The hard study cap is 12 new BEM evaluations.

## Execution and restart policy

Each coordinate is an independent one-candidate search. All NumCalc work must
run through the stage-aware queue:

- four queue workers;
- ten configured workers per search;
- twenty total NumCalc process slots;
- restart from retained per-search state;
- automatic bounded retry of failed NumCalc frequencies.

The study index is regenerated from manifests, search states, and retained
reports. Solver work trees are removed only after the compact NPZ response has
been validated.

## Stop and forward-use rules

- If no initial candidate improves its incumbent by 1.0 point, do not continue
  open-ended round L/K/N sampling.
- A 1.5-point or larger improvement may consume the two conditional slots but
  does not authorize further candidates beyond the hard cap.
- Regardless of outcome, proceed toward the intended non-round H/V, corner,
  sag, and baffle geometry after this study.
- Feed any measured improvement into the round-control heuristic seed map.
- Record an aperture-scaled limitation as provisional until the baffled or
  intended-geometry comparison separates internal and external mechanisms.
