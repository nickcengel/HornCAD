# Round-horn control-decoupling study

This directory is the clean canonical study for symmetric, square, zero-extension
OS-SE horns. Historical searches are evidence sources, not an execution queue.

## Domain and registered design

- Coverage half-angles: 30, 35, 40, 45, and 50 degrees.
- Square mouths: 250, 300, 350, 400, and 450 mm.
- Independent controls: physical length, K, and N. S is recorded as derived.
- Per cell: complete 3×3×3 factorial at length factors 0.80/1.00/1.20,
  K 2.5/4.0/5.5, and N 4/8/16.
- Per cell: one strictly reused K4/N10 reference and two length-only boundary
  sentinels at factors 0.70 and 1.30.
- Locked validation: two deterministic interior coordinates per cell.
- Registered ceiling: 675 factorial + 25 references + 50 boundary sentinels +
  50 validation = 800 coordinates.

Preflight currently classifies 25 coordinates as strictly
reusable, 135 as invalid geometry,
70 as physically redundant, and
570 as requiring BEM.

After geometry and redundancy filtering, 496
independent factorial coordinates remain, with
16-
22 per cell. The complete
quadratic control basis has rank 10 and condition
5.09; no absolute pairwise factor
correlation exceeds 0.30. Every cell retains at least two physically active
high-N points. More importantly, every cell independently retains rank 10 for
the same ten-term quadratic L/K/N model; per-cell condition numbers range from
5.53
to 8.42.

## Why the grid is fixed

The full factorial gives balanced independent L, K, and N effects plus every
two- and three-control interaction. Existing results may fill exact slots but do
not alter the registered design. Dense optimizer traces cannot count as grid
coverage merely because they are numerous.

## Geometry and reuse gates

Every coordinate is solved analytically before meshing. Invalid OS-SE solutions,
derived S outside 0.05-4.0, excessive terminal radial growth, and other existing
geometry-feasibility failures are terminal geometry rejections. The known
300×300×116.54 mm 30-degree and 500×500×174 mm 35-degree disc-like examples are
unit-tested against this same gate.

At fixed length, a control change producing less than 1% RMS change in normalized
radial profile is recorded as geometry-redundant and receives no BEM solve.

Reuse requires matching mouth, coverage, K, N, length within 0.25 mm, identical
solver/frequency fingerprint, and a retained responses.npz archive. Reused
responses will be rescored with the current diagnostics before final analysis.

## Execution and dead-region policy

Execution order is reference anchors, core center/axes, sparse boundary sentinels,
two-factor faces, three-factor corners, then locked validation. Core axes are
never pruned by score. Face/corner strata may be
stopped only after at least five distributed cells spanning three angles and
three mouths show that at least 80% are five or more score points below their cell
reference and none offers a material diagnostic improvement. Distributed
sentinels remain. The predeclared face/corner sentinel wave is 90 candidates,
15.8% of the 570 planned solves; continuation work is avoided only when that
evidence satisfies the explicit rule.

Two searches with ten workers each keep twenty cores occupied. Search completion,
failure, or geometry rejection immediately releases a slot. Single-candidate
searches are explicitly supported; an empty initial pool is forbidden. One search
failure is isolated and cannot stall the other slot or the remaining searches.
The runner records the failure and finishes all independent work before reporting
the study blocked.

The study cannot be launched accidentally by either generator. The runner requires
the exact SHA-256 of the reviewed manifest, and refuses a stale execution plan or
a confirmation hash from an earlier version of the design.

## Completion

Every registered coordinate must finish as reused, complete, geometry-rejected,
geometry-redundant, pruned by a documented rule, or failed. Locked validation is
not used for candidate selection. Final reporting includes diagnostic-specific
held-cell errors, raw-control correlations, physical-space coverage, replicated
steering effects, and all pruning decisions.

`manifest.json` is authoritative. `index.html` is generated from it.

## Registered analysis

For each of the 25 cells, fit the same terms: intercept, L, K, N, L², K², N²,
L×K, L×N, and K×N. Fit each of the six outcomes separately: surface score,
containment, profile error, slice-energy departure, outward rise, and the
secondary −6 dB error. This distinguishes a score gain from the physical
diagnostic tradeoff that produced it.

The second stage maps those cell-local coefficients across mouth and coverage,
looking for effects that repeat rather than relying on one optimizer trace or one
cell. The two locked interior points per cell test interpolation and are excluded
from fitting, selection, and pruning.
