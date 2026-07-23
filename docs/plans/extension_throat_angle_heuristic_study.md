# Extension and throat-angle heuristic study

## Purpose

This study measures how a conical throat extension and throat angle modify the
best measured axisymmetric round horn in every mouth/coverage cell. It produces
a deterministic, paired-effect design heuristic. It is not a new global
surrogate and it does not narrow the round baseline to a central sub-grid.

The complete 5×5 field remains in scope:

- coverage half-angle: 30, 35, 40, 45, and 50 degrees;
- round mouth diameter: 250, 300, 350, 400, and 450 mm;
- extension: 0, 20, 40, and 60 mm;
- throat angle: 0, 6, and 12 degrees.

The compatible 6-degree, zero-extension response already retained for each
parent is reused. It must not be simulated again.

## Launch gate

The round-control ridge-closure study is complete, its 48 responses passed
archive/diagnostic audit, and the measured round heuristic records the exact
ridge-results hash. The launch gate was completed on July 23, 2026:

1. primary parents were frozen in all 25 cells and distinct secondary parents
   were frozen in the three transfer cells;
2. the 210-case initial manifest and coordinate hash were frozen;
3. all 210 candidates passed geometry-only feasibility checks;
4. BEM execution was explicitly authorized.

The study runner verifies the completed ridge state, matching heuristic
provenance, frozen input hashes, candidate cap, and stage-specific preflight
marker before launching any BEM. Development and transfer results must be
frozen before the locked stage can be read or run.

Execution must use the repository's stage-aware BEM queue and global NumCalc
semaphore. Because candidates within one search are sequential, materialize this
fixed design as one independently schedulable search per candidate. Record the
queue-worker count, global NumCalc capacity, and sharding policy in the runtime
ledger. Scheduler preflight must reject a layout that can leave the final
candidates serialized in one search.

## Fixed geometry convention

For a paired contrast, hold mouth diameter, intended and OSSE coverage, OSSE
length, K, N, and authored throat radius fixed. Changing extension or throat
angle changes only those registered factors. OSSE length is not shortened to
compensate for extension: profile-plus-extension length is
`OSSE length + extension`.

For planning and reporting, calculate

```text
effective profile throat radius = authored throat radius
                                + extension × tan(throat angle)
```

and calculate the equivalent mouth obtained from the same OSSE controls and
effective profile throat radius. These profile-curve calculations describe the
geometric shift and help interpret transfer. They do not replace an acoustic
evaluation. In particular, a zero-degree extension is cylindrical and leaves
the OSSE profile curve unchanged while still changing the acoustic throat path.

## Frozen candidate allocation

### A. Full-grid primary-parent measurements — 175 new evaluations

After ridge closure, select the final best measured zero-extension round parent
in each of the 25 cells. For every primary parent evaluate:

- 6 degrees at 20, 40, and 60 mm extension;
- 0 and 12 degrees at zero extension;
- 0 and 12 degrees at 40 mm extension.

That is seven new responses per cell. Together with the retained 6-degree,
zero-extension response, these measurements identify the extension effect, the
direct throat-angle effect, and their combined effect throughout the full grid.

### B. Parent-transfer measurements — 15 new evaluations

In three representative cells, freeze one distinct, competitive secondary
parent with meaningfully different L/K/N/S or diagnostic behavior:

- 30 degrees / 250 mm;
- 40 degrees / 350 mm;
- 50 degrees / 450 mm.

For each secondary parent evaluate 0 and 12 degrees at zero extension, then 0,
6, and 12 degrees at 40 mm extension. Reuse its retained 6-degree,
zero-extension response. These 15 cases test whether the paired rule transfers
between round-control parents instead of merely describing the cell winner.

### C. Locked endpoint validation — 20 new evaluations

Freeze the heuristic described below before revealing these responses. At the
four grid corners and the center,

- 30 degrees / 250 mm;
- 30 degrees / 450 mm;
- 40 degrees / 350 mm;
- 50 degrees / 250 mm;
- 50 degrees / 450 mm,

evaluate the four withheld combinations formed by throat angles 0 and 12 degrees
and extensions 20 and 60 mm. These cases are never used to formulate or tune the
frozen rule.

### D. Conditional edge-midpoint validation — at most 16 evaluations

If any locked cell fails a registered radiation threshold, evaluate the same
four withheld combinations at:

- 30 degrees / 350 mm;
- 40 degrees / 250 mm;
- 40 degrees / 450 mm;
- 50 degrees / 350 mm.

The conditional block is all-or-none. No other automatic follow-up is
authorized.

The initial count is 210 new BEM evaluations. The absolute maximum is 226,
leaving 30 evaluations below the requested ceiling of 256. Geometry rejected
before BEM is recorded as unavailable and is not silently replaced.

## Deterministic paired-effect rule

Build one lookup per radiation diagnostic and surface score. For diagnostic
`y`, throat angle `a`, and extension `e`, use:

```text
y_hat(a,e) = y(6,0)
           + [y(6,e) - y(6,0)]
           + [y(a,0) - y(6,0)]
           + (e / 40) × I40(a)

I40(a) = y(a,40) - y(6,40) - [y(a,0) - y(6,0)]
```

This is exact at the measured zero- and 40-mm anchors. It predicts only the
withheld 20- and 60-mm endpoints and exposes each measured contribution; it is
not a fitted response surface. Interpolation across mouth/coverage cells is not
needed because every cell has its own primary-parent measurements.

Freeze the formula, lookup values, coordinate hashes, and thresholds after
blocks A and B and before loading block C outcomes.

## Validation and expansion rule

A locked case fails if any of these absolute errors exceeds its limit:

| Output | Limit |
| --- | ---: |
| Surface score | 1.00 point |
| Mean containment | 1.00 percentage point |
| Profile RMS error | 0.25 dB |
| Slice-energy RMS departure | 0.25 dB |
| Outward-rise violation | 0.50 dB |
| -6 dB coverage RMS error | 1.00 degree |

If every locked case passes every radiation threshold, stop at 210. If any
case fails, authorize the complete 16-case conditional block and stop at 226.
A failed gate remains useful: publish the measured table and restrict the API
to measured combinations rather than inventing broader confidence.

## Throat impedance

Record the current experimental throat-impedance diagnostic and its component
measurements for every response. Report its paired changes and validation errors
beside the radiation diagnostics. It remains excluded from surface score,
candidate ranking, parent selection, the expansion gate, and every claim that a
configuration is “best.” Its purpose here is to accumulate evidence for future
calibration.

## Deliverables

The versioned `extension_throat_heuristics_v1` artifact must include:

- all parent and candidate coordinates, response hashes, and measured/withheld
  roles;
- derived S, effective profile throat radius, equivalent-mouth shift, OSSE
  length, and profile-plus-extension length;
- exact measured lookup tables and the frozen paired-effect rule;
- locked and conditional validation results;
- radiation support status and nearest measured evidence;
- throat impedance in a clearly separate experimental section.

The design API should return measured or paired-rule provenance and warnings.
It must not silently represent an unvalidated throat/extension combination as a
confident prediction.

The executable study and live index are retained at
`examples/extension-throat-angle-heuristics/`. The index follows the repository
study-report convention and shows throat impedance beside surface score without
using it in ranking, fitting, or validation gates.
