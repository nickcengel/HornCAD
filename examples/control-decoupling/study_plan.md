# Round-horn control-decoupling study

This directory is the clean canonical study for symmetric, square, zero-extension
OS-SE horns. Historical searches are evidence sources, not an execution queue.

## Domain and registered design

- Coverage half-angles: 30, 35, 40, 45, and 50 degrees.
- Square mouths: 250, 300, 350, 400, and 450 mm.
- Independent controls: physical length, K, and N. S is recorded as derived.
- Per cell: complete 3×3×3 factorial at length factors 0.80/1.00/1.20,
  K 2/4/6, and N 4/8/16.
- Per cell: one strictly reused K4/N10 reference and two length-only boundary
  sentinels at factors 0.70 and 1.30.
- Per cell: six conditional hard-boundary probes at length factors 0.60/1.40,
  K 1/7, and N 2/20. These are registered but run only after an inner endpoint
  points outward. N=2 is never part of the regular grid.
- Locked validation: two deterministic interior coordinates per cell.
- Registered ceiling: 675 factorial + 25 references + 50 boundary sentinels +
  50 validation + 150 conditional closure probes = 950 coordinates. The actual
  new-BEM ceiling remains 800.

Preflight currently classifies 25 coordinates as strictly
reusable, 184 as invalid geometry,
89 as physically redundant, and
566 as requiring BEM. A further
86 feasible closure probes run only when triggered.

After geometry and redundancy filtering, 492
independent factorial coordinates remain, with
18-
22 per cell. The complete
quadratic control basis has rank 10 and condition
5.23; no absolute pairwise factor
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

## Prior evidence retained

The physical-length center in each cell is the best retained K4/N10 S-grid
length, not a generic constant. Twenty-three retained cells have closed S
evidence and two are geometry-limited. This preserves the earlier mouth/coverage
length prescription while the factorial measures how K and N modify it.

K=2/4/6 brackets the useful K≈3-6 ridge more honestly than the earlier
2.5/4/5.5 proposal. Fine K changes near the ridge generally moved score by only
tenths, but K=6 was not independently closed, so K=1/7 remain conditional probes.

N=2 is not a regular sample. Four retained fixed-length/fixed-K comparisons put
it 14.9-17.6 score points below N=5-10; it runs only if N=4 unexpectedly improves
over N=8. N=4/8/16 is used because it leaves every cell full-rank and physically
distinct. Substituting N=10 for N=8 makes some cells rank-deficient through
profile redundancy; the K4/N10 anchor is still reused in every cell.

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

## Execution and completion policy

Execution order is reference anchors, core center/axes, sparse boundary sentinels,
conditional axis closure, two-factor faces, three-factor corners, then locked
validation. No canonical factorial coordinate is pruned by score. Every feasible,
profile-distinct center, axis, face, and corner runs because L/K/N effects are
already known to change with mouth, coverage, and derived S. This preserves the
same identifiable response model in every cell.

An outer L/K/N closure point runs only if the measured inner endpoint improves
score by at least 0.5 points or materially improves a component diagnostic over
the center. N=2 is therefore only a lower safety-bound check after N=4 beats N=8;
existing evidence gives no reason to sample it routinely.

Two searches with ten workers each keep twenty cores occupied. Search completion,
failure, or geometry rejection immediately releases a slot. Single-candidate
searches are explicitly supported; an empty initial pool is forbidden. One search
failure is isolated and cannot stall the other slot or the remaining searches.
The runner records the failure and finishes all independent work before reporting
the study blocked.

The queue is restartable from the per-search ledgers. Completed searches are
skipped, an interrupted running candidate is requeued, and a failed coordinate is
retried once with the recovery mesh policy. An unresolved failure releases its
slot, remains visible in the runtime audit, and prevents a false complete status.

Each completed candidate retains its project YAML, surface STL, report, and
validated compressed `bem/responses.npz`. That archive contains the frequency,
angle, response, and impedance arrays required to regenerate diagnostics and
reports. The much larger `project-NumCalc-*` mesh/solver tree is deleted only
after the retained archive has been opened and every stored array validated.

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

The primary confirmatory fit uses only this canonical study and strict exact
response reuses. A second augmented predictive fit may then add all compatible
historical responses, retaining source provenance. Historical optimizer traces
can improve prediction but cannot substitute for a missing canonical contrast.
