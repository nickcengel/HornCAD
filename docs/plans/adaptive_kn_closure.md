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
5. If every point in the complete neighborhood is within 0.5 surface-score
   points of the incumbent, record that neighborhood as a score asymptote and
   stop K/N refinement. In a coupled search, proceed immediately to local
   S/length refinement.
6. Otherwise, if the incumbent wins its complete neighborhood, refine N
   spacing while retaining K = 0.5 spacing.
7. Repeat until an asymptote is found or the neighborhood spacing reaches
   K = 0.5 and N = 1.

After the coarse 3x3 interaction check, refined rounds measure axial neighbors
first. If those axial results are all within 0.5 score points, closure stops
without spending four more candidates on fine diagonal combinations. Stored
quarter-step K state is promoted to K=0.5 on resume, and stored sub-unit N
spacing is promoted to N=1. The audit of completed Phase 3 searches found no
practical design decision changed by finer resolution.

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

## High-S, high-N K rescue

A poor high-N result does not by itself reject its K. When a completed
candidate has S >= 2.0 and N >= 8 and scores at least 3 surface-score points
below the current search best, closure first holds length and K fixed and
lowers N by 2. If the lower-N result remains poor while N is still at least 8,
the rule may step downward again. Only after this measured lower-N check may
the normal neighborhood move away from that K region.

This is a rescue probe, not an assumption that lower N must win. It prevents
high-S termination behavior from making a potentially useful K appear bad.
The search records the source score, best score, K, and N transition in
`kn_closure.last_rescue`.

## Closure certificate

`search_state.json` records a `kn_closure` object with the incumbent, current
spacing, status, and reason. The possible terminal states are:

- `closed`: all axial and diagonal neighbors were measured at K=0.5 and N=1.
- `boundary-limited`: the best point reached K=7 or N=40.
- `unresolved`: closure could not start from valid completed symmetric points.

A score-asymptote closure records every measured point in the plateau plus its
K and N bounds. The best numerical point remains the seed for local S/length
refinement, but the neighboring points remain first-class evidence rather than
being discarded. If length moves materially, the next alternating round
reopens K/N around the new length; the K near 4 is therefore not imposed on the
new length without another measured check.

A search that exhausts its evaluation budget while closure is still running is
not a proven optimum. Reports expose the closure status and must describe its
best candidate as provisional.

## Existing studies

Completed fixed-grid studies remain unchanged and retain their original search
history. A finished study whose winner is not bracketed at N=1 resolution is
eligible for a targeted follow-on closure search seeded from that winner. This
retrospective work is lower priority than the central 40/45/50-degree program
and does not repeat a complete coarse grid. Completed 60-degree studies are
excluded from retrospective closure. Active BEM processes must not be
interrupted to adopt this policy.
