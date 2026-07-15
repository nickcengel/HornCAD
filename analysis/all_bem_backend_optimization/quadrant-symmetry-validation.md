# Native BEM quadrant-symmetry validation

Validated 2026-07-15 on macOS with the installed NGSolve 6.2.2606 package and
the Test4 horn. This path does not use AKABAK, Wine, or a non-native solver.

## Implementation

The wavelength mesh is authored and retained as an open positive-X,
positive-Y quadrant. For BEM integration it is reflected into one connected
surface so that elements sharing a symmetry seam also share topology and use
NGSolve's singular quadrature. Even-even pressure degrees of freedom are
periodically identified and compressed. Sources cover the connected surface;
test integration, mass terms, and the prescribed throat load are restricted to
the independent quadrant. Radiation remains an unrestricted 4-pi free-air
problem. No baffle or symmetry-plane boundary is added.

This reduces Test4's 500 Hz H1 space from 1,298 unknowns to 416. It does not yet
reduce source quadrature/FMM tree construction to one quadrant; that is a
separate native-kernel optimization.

## Numerical comparison

Both cases used the 500 Hz, 6-EPW Test4 mesh and the combined-field formulation.
The quadrant solve used the production `1e-4` tolerance. The full reference
used `5e-5` after its first `1e-4` run stopped at a recomputed residual of
`1.48e-4`.

| Result | Quadrant | Full geometry |
|---|---:|---:|
| H1 unknowns | 416 | 1,298 |
| GMRES iterations | 28 | 38 |
| Recomputed relative residual | 5.23e-6 | 1.09e-5 |
| Solver wall time | 17.61 s | 13.17 s |

After normalization by on-axis complex pressure, the maximum complex
difference was 0.00299 horizontal, 0.00303 diagonal, and 0.00364 vertical.
Unnormalized far-field vectors differed by 1.4--1.5%; mouth acoustic-power
magnitudes differed by 1.03%. These results accept the quadrant formulation at
500 Hz and establish the full-geometry comparison procedure for higher mesh
tiers.

## Thread-safety finding and scheduling policy

NGSolve 6.2.2606's asymmetric full-source/quadrant-target hypersingular
operator is not thread-safe. Repeating the same operator application produced
about 1--4% changes with 20 native threads and a 1.62% combined-operator change
with only two threads. With one native thread, repeated applications were
bitwise identical and the independently recomputed solve residual passed.

Quadrant frequency workers therefore run with one native thread. Hardware is
used by running independent frequencies in separate processes, limited by
measured memory. A ten-frequency sweep uses ten cores on the 20-core reference
machine; twenty frequencies can use all twenty cores when memory allows. Each
quadrant solve repeats a deterministic combined-operator probe and aborts on
any difference larger than 1e-12, so this library race cannot silently corrupt
a sweep. Full-geometry reference solves retain the prior two-thread allocation
policy.

## Next optimization boundary

The current implementation has true quadrant unknowns and target integration,
but its connected source surface and source FMM tree contain all four reflected
quadrants. A further native C++ optimization would construct symmetry-aware
source multipoles from one quadrant without separating seam topology. That
work is not required for correctness and must preserve the deterministic probe
and full-geometry field comparison above.
