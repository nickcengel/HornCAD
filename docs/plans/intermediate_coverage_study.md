# Intermediate Coverage Study: 30°, 40°, and 50°

The supported study domain is 25° through 50° half-coverage. The exploratory
60° family has been archived and is not part of active comparisons or future
work.

The 30° study closes the interpolation gap between 25° and 35°. It uses the
supported six 250--500 mm square mouths and the exact S coordinates 0.7, 1.0,
1.3, 1.6, 1.9, 2.2, 2.5, 2.8, and 3.0 used by those neighboring studies.
Adaptive pruning may omit a confidently declining intermediate tail, but the
S=3.0 boundary sentinel is mandatory. All seven 30° searches must complete
before coupled K/N or finer local searches begin. The supported active mouth
range is 250--500 mm; earlier 200 mm results are archived boundary evidence.

## Motivation

The completed square-mouth survey sampled 25°, 35°, 45°, and 60°. Its best
derived S moved systematically upward with coverage: approximately 0.7 at 25°,
0.7–1.3 at 35°, 1.7–2.2 at 45°, and 3.0 at 60°. The 25° and 60° optima landed
on the original S boundaries, while the strongest scores clustered around 35°
and 45°.

This can indicate a continuous solution ridge in coverage, mouth scale, length,
and S rather than an intrinsic preference for exactly 45°. The 10–15° gaps in
the original coverage sampling are too large to resolve that ridge. The next
study therefore prioritizes 40° and 50° instead of adding detail around the
less-promising 25° and 60° regions.

## Questions

1. Does peak surface score vary smoothly through 35°–50°?
2. How must length and S change to widen or narrow coverage while preserving
   surface score?
3. Is the apparent 45° advantage physical, or an artifact of where the earlier
   S range intersected the solution ridge?
4. Does the preferred dimensionless length remain stable across mouth sizes?

## Design

- Intended symmetric half-coverages: 40° and 50°.
- Square mouths: 250, 300, 350, 400, 450, and 500 mm.
- Fixed profile controls: K=4, N=10, zero extension.
- Fixed acoustic sweep and diagnostic definitions from the existing study.
- Derived S targets: 0.5 through 4.0 in increments of 0.25.
- Length is solved independently for every coverage, mouth, and S target.

The wider S interval prevents the new peak from being censored by the earlier
0.7–3.0 boundaries. Every coverage/mouth pair begins with the same 15-point
opportunity.

## Adaptive stopping

Candidates run in ascending S. At least five measured points are required.
The remaining high-S tail may be skipped only after three consecutive score
declines and when a quadratic prediction plus twice its uncertainty remains at
least three surface-score points below the observed best. Rising, recovering,
or uncertain curves continue to S=4.0.

This rule does not prune the low-S side before it is measured. A future round
may extend below S=0.5 or above S=4.0 if a new optimum again reaches a boundary.
The highest authored S point is a required boundary sentinel: intermediate
tail points may be pruned, but S=4 still runs to detect an unexpected second
rise. Canonical matched-comparison sets and short local-refinement sets are not
adaptively pruned.

## Scheduling and reporting

The study uses two concurrent queues with ten NumCalc frequency workers each.
It starts only after the active K/N study finishes, so no current search is
interrupted or oversubscribed. The main index includes these candidates in the
existing physical-parameter plots and refreshes while the study runs.

After completion, selective 42.5° and 47.5° searches are warranted only where
the 40°/45°/50° ridge shows rapid curvature or a change in the winning geometry
family.
