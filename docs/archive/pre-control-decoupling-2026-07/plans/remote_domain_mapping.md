# Zero-extension controlled-learning study

## Objective and domain

The study must teach how physical length, K, and N affect every surface
diagnostic across the useful symmetric, square, zero-extension horn domain. It
is not a local score optimizer. S is a derived OS-SE geometry result, not a
fourth independent control.

The active domain contains 25 mouth/coverage cells: half-coverage 30, 35, 40,
45, and 50 degrees crossed with square mouths 250, 300, 350, 400, and 450 mm.
The retained 25-degree and 500 mm results are historical edge evidence and
receive no new work. Extensions, round-to-square morphing, and independently
coupled horizontal/vertical curves remain later studies.

## What the earlier work established

The remote-mapping batch prescribed low-S/low-K/low-N and
high-S/high-K/high-N samples. Thirty-six completed remote candidates produced
no competitive design or useful diagnostic tradeoff; their median score change
was -10.18 points. Those outer strata are closed.

Quarter-step K refinement was also below practical resolution. Across 110 such
candidates, a selected winner's median advantage over a nearby coarse K value
was 0.05 score points and the maximum was 0.14. New K values use 0.5 steps and
new N values use integer steps.

## Rejected replacement designs

Two proposed replacements were rejected before full execution:

1. A common response-surface grid repeated K=4/N=10 length work already
   present in the S grids.
2. A per-cell D-optimal augmentation reduced that duplication but still treated
   nominal K/N separation as information. At 30 degrees and 250 mm, changing N
   from 6 to 14 at L=200.597 mm and K=3 changes normalized radius by only 0.41%
   RMS. It is not an independent physical contrast.

The second design requested 223 new candidates to condition 25 separate cell
models. That ignored transfer across cells and optimized matrix rank rather
than acoustic knowledge. It was not launched. Completed candidates from the
interrupted attempts remain evidence; queued candidates are superseded.

## Physical representation and validation

All completed candidates in the retained cells are represented by coverage,
mouth, length/mouth, and normalized radial-profile modes. Three profile modes
retain 99.915% of measured surface-shape variance. K, N, and S remain steering
labels but cannot make a sample informative unless they change the surface.

Models are fit separately to score, containment, profile RMS error,
slice-energy departure, outward-rise violation, -6 dB RMS error, and
high-frequency coverage error. Validation withholds an entire mouth/coverage
cell, not random candidates, so dense local traces cannot leak into their own
test data. The initial physical model reaches held-cell R² of 0.903 for score,
0.873 for slice energy, 0.918 for outward rise, and 0.966 for -6 dB error. Its
largest gaps, mainly 250-300 mm mouths at 30 degrees and a few 50-degree edges,
determine where new evidence is valuable.

## Controlled learning batches

Each batch contains 30 direct one-control contrasts:

- 10 length, 10 K, and 10 N contrasts;
- five increases and five decreases for every control;
- at most two candidates in one mouth/coverage cell; and
- a material normalized-length or radial-profile change relative to a named
  completed candidate while the other two controls remain fixed.

Selection rejects excluded 25-degree/500 mm cells, old quarter-grid controls,
known remote boundary strata, repeated K4/N10 length-axis work, near-existing
geometry, and N changes whose surface difference is below 1% RMS. Every
manifest entry states its hypothesis, contrasting search/candidate, physical
novelty, and the learning rules that admitted it.

The study asks which factor changes each diagnostic, where directions reverse,
which interactions explain energy bunching or outward-rise degradation, and
whether a rule learned in one mouth/coverage cell predicts a held-out cell.

After every batch the complete model is rebuilt. Another batch is permitted
only if the median held-cell RMSE improvement across diagnostics is at least 2%.
The program stops on a prediction plateau, no physically novel direct
contrasts, or three rounds. No sub-point score polishing and no ad hoc per-cell
optimizer are part of this phase.

## Execution and record keeping

The authoritative rules are in
`docs/reference/research/bem_learning_ledger.json`. Candidate generation loads
that ledger; report prose and scheduler policy are no longer separate informal
notes. Contradicted work is marked superseded rather than silently retained in
the active queue.

Each round freezes its analysis and candidate manifest before BEM execution.
Two concurrent searches with ten solver workers each keep the 20-core machine
occupied. The unattended runner refits after completion and applies the
registered stop rule before creating another round.

Candidate reports, compact response archives needed for future diagnostics,
manifests, state, validation analyses, and the index are tracked study
artifacts.
