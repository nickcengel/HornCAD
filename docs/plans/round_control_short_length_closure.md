# Round-control short-length closure

## Purpose

Bracket the remaining three short/low-K length curves after ridge closure.
K=1 is a hard design limit and is held fixed. This study does not investigate
K below 1 or revisit K=7.

Cells:

- 35 degrees / 300 mm;
- 40 degrees / 250 mm;
- 45 degrees / 250 mm.

All cases retain N=8, zero extension, 6-degree throat angle, the registered
mouth and coverage, and the ridge study's target-S length reference.

## Staged design

The completed ridge study measured length multipliers 0.9, 1.0, and 1.1. In
stage 1, measure multiplier 0.8 once in each cell: three new BEM evaluations.

For a cell, stop if the 0.8 score is no greater than the existing 0.9 score;
the 0.9 point is then bracketed by 0.8 and 1.0. If 0.8 is better than 0.9,
measure multiplier 0.7 in that cell. Stage 2 therefore contains zero to three
conditional evaluations.

After stage 2, the curve is bracketed if 0.8 is at least as good as both 0.7
and 0.9. If 0.7 remains best, report the short-length boundary without
authorizing more simulations. The absolute study cap is six.

Each candidate is an independent one-candidate search. Execution must use the
stage-aware BEM queue with a shared capacity of 20 NumCalc processes; whole-
search slot scheduling is prohibited.

Throat impedance is retained as an experimental diagnostic and remains outside
surface score, ranking, the conditional decision, and the bracket decision.
