# Measured BEM horn optimizer

## Authority and status

This document is the single active authority for practical automated HornCAD
design. The implementation is `app.horn_optimizer`, the CLI is
`python -m app.tools.run_horn_optimizer`, and the input contract is
`horn_optimizer` YAML version 1.

The optimizer constructs candidates from measured heuristics, retained response
evidence, and new BEM measurements. It does not release or depend on a global
score surrogate. The older recommendation-map and frequency-energy surrogate
plans are retained only under `docs/archive/pre-horn-optimizer-2026-07/`.

The non-round transfer study must publish its result before the implementation
freezes its preferred common-length initialization. Until that artifact exists,
the implementation reports that it is using the width/height-weighted fallback.

## Fixed design intent

One run fixes:

- horizontal and vertical coverage half-angles, used unchanged in both OS-SE
  bases and the diagnostic target;
- throat angle;
- mouth-shape family, `round` or `square` (`round` means zero squareness and
  therefore has an elliptical boundary when width differs from height);
- sag axes: `none`, `horizontal`, `vertical`, or `both`;
- the allowed scalar or range for sag.

Mouth input is either:

- `width_mm` plus `height_mm`; or
- `width_mm` plus `aspect_ratio`, with height derived as width divided by aspect
  ratio.

Every mouth quantity can be a scalar or inclusive two-value range. Height and
aspect ratio are mutually exclusive. Practical bounds constrain the search but
never redefine the fixed coverage, throat, shape, or sag-axis intent.

The optimizer always searches one common OS-SE profile length, independent H/V
K, independent H/V N, and conical extension. S is derived separately on both
axes and guides coupled length/K moves.

See [`examples/horn-optimizer/example.yaml`](../../examples/horn-optimizer/example.yaml)
for the complete schema.

## Baseline and retained evidence

An optional full seed project must be compatible with the fixed run intent and
mouth ranges. It is always the first baseline. If an exact compatible retained
response with surface v2.3 and throat-impedance v2.3.0 exists, that response is
rescored/reused without spending simulation budget. Otherwise the seed receives
the first new BEM evaluation. With no supplied seed, the measured heuristic
construction is the baseline.

Nearby retained responses can initialize branches and supply support warnings.
They are never substituted for a new coordinate. Exact compatibility includes
coverage, throat angle, mouth squareness, sag axes, and every authored search
coordinate.

## Proposal rounds

Round zero measures or reuses the baseline. The first exploration includes:

- both validated common-length constructions;
- independent horizontal and vertical K/N moves without averaging axes;
- mouth width, height, or aspect sentinels when ranges permit them;
- extension;
- permitted sag sentinels.

Later rounds use batches of at most four candidates. Candidate moves are grouped
as horizontal-axis, vertical-axis, length/extension, mouth-size/aspect, and sag.
Length and K changes are coupled using derived H/V S guidance. Up to three
measured leaders remain anchors so a single local basin does not erase other
competitive regions.

An inverse-distance response approximation may order only the finite proposal
pool for the current run. It is discarded as the pool is consumed, is labeled
non-portable in state, and must not be exported as a general predictor.

The stage-aware queue shares a hard 20-process NumCalc capacity and starts no
more than four fixed searches per optimizer batch.

## Ranking

The default measured ranking is:

1. find the highest surface-v2.3 score;
2. retain every candidate within 0.5 surface point of that score;
3. choose the highest throat-impedance-v2.3.0 score in that shortlist.

The YAML may disable the impedance tiebreak or change the shortlist width. A
supplied seed remains the winner unless another measured/reused result beats it
under the selected rule.

## Budget, recovery, and stopping

Every newly launched solver evaluation counts against `max_simulations`,
including final confirmation and an evaluation that ends in solver failure.
Exact library reuse, deterministic geometry rejection, and retries of the same
interrupted evaluation do not consume another slot.

State is written atomically before a solver batch launches. Restart harvests a
completed search or resumes the same charged evaluation; coordinate and proposal
hashes prevent duplicates. Solver failures retain their attempt history.

Early stopping requires all three conditions:

1. local step sizes have contracted to the registered thresholds;
2. two completed rounds have not improved the ranked winner;
3. no unmeasured feasible heuristic branch remains.

If budget remains, early stopping schedules one higher-density final
confirmation, which consumes a simulation. The hard cap always wins.

## Outputs and live review

Each run retains:

- `optimizer_state.json`, including proposal lineage and full accounting;
- a live `index.html` that reloads every five seconds while active and provides
  sortable columns;
- every candidate project, STL/preflight artifact, fixed-search YAML, compact
  response, and report;
- `winning_project.yaml` and `winning_horn.stl`;
- `top_alternatives.json` and `result.json`, including seed-relative changes,
  parameter lineage, nearest evidence, support warnings, early-stop evidence,
  and simulation accounting.

Approval-gated runs materialize proposals and stop until `approve` is invoked.
Autonomous runs continue until the hard cap or the contracted stopping rule.

## CLI

```text
python -m app.tools.run_horn_optimizer CONFIG init
python -m app.tools.run_horn_optimizer CONFIG dry-run
python -m app.tools.run_horn_optimizer CONFIG step
python -m app.tools.run_horn_optimizer CONFIG run
python -m app.tools.run_horn_optimizer CONFIG approve
python -m app.tools.run_horn_optimizer CONFIG status
python -m app.tools.run_horn_optimizer CONFIG report
```

`dry-run` validates and materializes the next batch without spending simulation
budget. `step` performs at most one batch. `run` is restartable.

## Boundary with other systems

`bem_candidate_search` remains the low-level/manual engine used for fixed
candidate geometry, BEM, diagnostics, and artifact retention. Its generic
Pareto/surrogate proposer is not this optimizer.

`app.design_api` remains a portable-model interface. Its current prediction is
limited-support and its model-only `improve()`, `design()`, and
`select_experiments()` methods remain deferred. They are not alternative
optimizer implementations and cannot emit BEM-confirmed results.
