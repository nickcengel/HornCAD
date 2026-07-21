# Adaptive K/N closure strategy

## Objective

A fixed K/N grid may identify the best measured candidate while leaving a
valid, better neighbor untested. This is especially risky because the useful N
range changes with mouth size, length, coverage, and S. A K/N result is now
considered final only when the measured winner has a local closure certificate.

## Search sequence

1. Measure the authored coarse K/N cross and selected interactions. Routine
   coarse N probes are 5, 10, and 15; N=2 and N=20 are not automatic probes.
2. Choose the highest measured surface score as the incumbent.
3. Measure all feasible axial and diagonal neighbors around that incumbent.
4. If a neighbor wins, move the incumbent and repeat its neighborhood.
5. If the incumbent wins its complete neighborhood, halve the K and N spacing.
6. Repeat until the neighborhood spacing reaches K = 0.25 and N = 1.

The diagonal probes are required. Main effects alone cannot safely predict
points such as K=3, N=5 from K=3, N=10 and K=4, N=5.

## Limits and expansion

- K may decrease to 1 and N may decrease to 2.
- Probe N below 5 only when the measured winner or trend points downward.
- Probe N above 15 only when the measured winner or trend points upward.
- The initial upper safety limits are K=7 and N=40.
- Reaching K=1 or N=2 closes that lower direction.
- A winner at an upper safety limit is reported as boundary-limited, not closed.
- The evaluation budget is a safety stop, not evidence of closure.

The initial neighborhood spacing is K=0.5 and N=5. If N=5 wins, closure must
measure both a lower and an upper N value before accepting it; the same
bracketing rule applies to every interior winner. N intervals are bisected
through intermediate values rather than restricting N to multiples of five.
This allows each geometry and S value to establish its own useful N range.

## Closure certificate

`search_state.json` records a `kn_closure` object with the incumbent, current
spacing, status, and reason. The possible terminal states are:

- `closed`: all axial and diagonal neighbors were measured at K=0.25 and N=1.
- `boundary-limited`: the best point reached K=7 or N=40.
- `unresolved`: closure could not start from valid completed symmetric points.

A search that exhausts its evaluation budget while closure is still running is
not a proven optimum. Reports expose the closure status and must describe its
best candidate as provisional.

## Existing studies

Completed fixed-grid studies remain unchanged and retain their original search
history. A finished study whose winner is not bracketed at N=1 resolution is
eligible for a targeted follow-on closure search seeded from that winner. This
retrospective work is lower priority than the central 40/45/50-degree program
and does not repeat a complete coarse grid. Active BEM processes must not be
interrupted to adopt this policy.
