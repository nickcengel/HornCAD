# BEM candidate search

## Purpose

HornCAD should help a user move from a plausible hand-designed seed horn to a
small, reviewable set of better-performing candidates. Candidate evaluation uses
the free-air BEM backend. The search must preserve the user's physical and
acoustic intent, expose tradeoffs instead of hiding them in one opaque score,
and retain enough provenance to reproduce every result.

This document records the design of the implemented first search workflow and
identifies the refinements that remain open.

## Authored design intent

The user begins by designing and exporting a normal HornCAD YAML project. The
seed is both an initial search point and the reference for relative search
bounds.

The following values are immutable during a search:

- mouth width and height;
- intended horizontal and vertical coverage;
- throat radius or diameter;
- throat angle;
- mouth sag;
- crossover frequency;
- upper operating frequency; and
- any explicit manufacturing limits supplied by the user.

The intended coverage values describe the desired acoustic result. They are not
the same as the movable OS-SE coverage parameters used to construct a horn.

Length and conical extension are deliberately not immutable authored values.

## Initial search space

The active search model includes these eight variables:

- `k_h` and `k_v`;
- `osse_coverage_h_deg` and `osse_coverage_v_deg`;
- `length_mm`; and
- `extension_mm`; and
- `n_h` and `n_v`.

The explicit names above should be used in search records so intended coverage
cannot be confused with OS-SE construction parameters.

Horizontal and vertical `s` are derived geometry values, not independent search
variables. After proposing length, extension, OS-SE coverage, and `k`, HornCAD
solves the geometry and derives `s_h` and `s_v`. A candidate is feasible only
when both values are nonnegative and within the configured realized-S bounds.

K, OS-SE coverage, length, and extension are proposed together. Negative-S
geometry is rejected; K is never silently repaired afterward because that would
change the meaning of the proposed experiment.

The first round fixes extension at the seed value and varies N explicitly.
Parameters such as `q` and mouth squareness remain fixed. Extension may be
released in a later round, where authored `length + extension` is treated as
the axial-depth reference so the two lengths cannot independently buy depth.

The independent-lever interpretation is no longer adequate for candidate
generation. With mouth size fixed, increasing length or OS-SE coverage can make
derived S negative; increasing K or decreasing OS-SE coverage can restore
positive S. N also changes solved S, and its geometric influence grows with
positive S. Candidate families must therefore move along explicitly described
coupled directions rather than silently repairing one proposed parameter after
another moves.

N is treated as an internal construction parameter. Search and review use the
realized mouth exit angle and local mouth curvature radius (also normalized by
axis mouth half-dimension) to describe termination geometry. These values are
computed from the analytic profile before meshing.

## Search bounds

Length uses an explicit exploration envelope. The maintained example uses:

```text
255 mm <= candidate length <= 345 mm
```

The user may override the bounds. The initial experiment spans the full envelope
evenly; it does not impose a soft ±10% admission cap around the seed.

The currently running first-round implementation still subtracts a symmetric
length cost from its selection scores. Replace that rule after the active search
finishes; do not change scoring partway through a search ledger.

The replacement policy is asymmetric and separates acoustics from packaging:

- normalized throat-impedance magnitude at crossover remains a hard feasibility
  constraint (minimum 0.7 over the crossover-centered evaluation window);
- Pattern Fit, Pattern Stability, and HF Retention remain unmodified acoustic
  objectives;
- a candidate shorter than the authored reference receives no departure cost if
  it satisfies loading and the other feasibility checks;
- added axial depth may be penalized, but must not be hidden inside the reported
  acoustic diagnostics; and
- once extension is released, packaging size is measured using total axial depth
  `length_mm + extension_mm`, not horn length alone.

Prefer representing total axial depth as an explicit minimization objective in
the Pareto set. This makes compactness visible and prevents either extra loading
or shorter packaging from silently rewriting the meaning of the acoustic
scores. Additional impedance above the 0.7 feasibility threshold receives no
extra credit.

Extension should use explicit minimum and maximum lengths rather than only a
percentage of its seed value, because a seed extension may be zero. A provisional
default is zero through 15% of seed horn length. This default still needs to be
checked against the exact geometry convention and exposed clearly in the UX.

Bounds for `k_h`, `k_v`, and both OS-SE coverage parameters still need to be
chosen. They should be expressed relative to the seed where sensible, reject
invalid geometry before meshing, and be user-overridable without requiring the
user to understand the optimizer.

The search report records the configured range, seed value, and actual retained-
candidate span for every movable parameter, including `n_h` and `n_v`.
Each retained candidate receives a short label based
on its largest normalized departure from the seed (for example, “High
horizontal K”) instead of a generic geometry-feasibility note. When primary
traits repeat, every candidate in that group gains secondary (and, if needed,
additional) traits until its report label is distinct.

`N` is explored in the structured first round because it directly controls the
termination geometry of interest. This avoids confounding it with independently
randomized extension.

## Fixed evaluation band

Every candidate in one search is evaluated over the same band:

```text
user crossover frequency <= frequency <= user upper operating frequency
```

The automatic sustained -6 dB crossing remains useful diagnostic information,
but it must not move a candidate's optimization band. Otherwise a candidate
could appear better simply because a geometry change excluded its poor
low-frequency behavior.

If a genuine -6 dB crossing is absent within the fixed band, that frequency is
penalized as 90-degree half-angle using the established diagnostic convention.
All candidate comparisons use the same logarithmic evaluation grid and exact
endpoint frequencies.

## Objectives

The search maximizes the existing three 0-100% diagnostics:

- Pattern Fit;
- Pattern Stability; and
- HF Retention.

All are oriented so 100% is ideal. Horizontal, vertical, and combined values
remain available. The initial search should use the combined values as its
three objectives while retaining plane-specific values for review.

The objectives should not initially be collapsed into one weighted score.
HornCAD should retain a Pareto set: candidates for which no other evaluated
candidate is at least as good in every objective and better in one. This keeps
real tradeoffs visible. Preference weighting can be added later if users need a
single automatic selection.

## Crossover loading constraint

The normalized throat-impedance magnitude must be at least 0.7 at crossover:

```text
|Z throat| / (rho*c/S_t) >= 0.7
```

This is a feasibility constraint, not an objective to maximize. Values above
the threshold are not increasingly rewarded.

The displayed crossover-loading diagnostic is:

```text
100% * min(1, minimum normalized impedance / 0.7)
```

Rather than use a potentially fragile single sample, the provisional plan is to
take the minimum normalized magnitude across a one-third-octave region centered
on crossover. The exact band and interpolation behavior should be confirmed
before implementation.

## Candidate evaluation

For each proposal HornCAD should:

1. Materialize a complete candidate configuration from the seed and proposed
   variables.
2. Solve all derived geometry values, including `s_h` and `s_v`.
3. Reject infeasible or invalid geometry before generating a mesh.
4. Run the free-air BEM sweep over the fixed search band.
5. Generate the standard interactive report, impedance magnitude, coverage
   data, and diagnostics.
6. Record the candidate in the search history and update the Pareto set.

Every feasible evaluated candidate retains:

- a complete YAML project;
- an inspectable acoustic-surface STL;
- proposed and derived parameter values;
- effective search bounds;
- geometry-feasibility result;
- solver resolution, mesh statistics, timing, and completion status;
- standard report and `coverage_diagnostics.json`; and
- search iteration, batch, and selection provenance.

Rejected proposals retain no per-candidate record, YAML, STL, or rejection
reason. The report and ledger expose only their aggregate count. Failed BEM
evaluations remain visible because they may require diagnosis or resumption.

## Search strategy

The BEM solver is an expensive deterministic black box with multiple competing
objectives and feasibility constraints. The optimizer should learn changes
relative to the user's seed while respecting that useful geometric directions
are coupled.

The implemented strategy is constrained multi-objective Bayesian optimization:

1. Evaluate the user's seed at production resolution.
2. Build four matched length families evenly spanning the full configured
   length envelope. Extension remains fixed at the seed. Within each family,
   keep the coupled H/V coverage-K controls fixed and evaluate low, seed, and
   high N. Coverage and K are selected jointly to place the middle-N member in
   a deliberate realized-S regime while keeping all three N members feasible.
   This yields direct N comparisons at short, intermediate, and long lengths.
   The initial realized-S window is configurable and defaults to 0–3.0 in
   both axes. This includes the zero-S boundary, the observed 0.2–0.5
   transition region, and strong high-S termination geometries. Negative S
   remains geometrically infeasible.
   The initial candidates span the full length bounds. Length cost is retained
   only as a ranking preference and does not define the exploration envelope.
3. Fit separate surrogate models to diagnostic changes relative to the seed and
   to the crossover-loading constraint. Retain prediction uncertainty rather
   than treating the surrogate mean as truth.
4. Screen an adaptive proposal only when the model assigns at least 97%
   probability that it is worse than the seed on all three selection objectives.
   Screening never applies to the initial coupled-geometry round. An uncertain
   candidate remains useful because it may improve the result or teach the
   model. Screened proposals retain no individual data; only an aggregate count
   is reported.
5. Propose hardware-appropriate batches that balance predicted Pareto
   improvement with exploration of uncertain regions.
6. Continue updating the models, learned lever-effect summary, and Pareto set
   after each completed batch.
7. Confirm the leading candidates at production resolution.

The learned lever summary expresses the estimated change in each diagnostic for
a positive 10% step across that parameter's configured range. These values are
evidence from the current search, not universal horn-design rules. Important
interactions—especially N×K, N×coverage, length×extension, and horizontal×vertical
coupling—must subsequently receive deliberate probes. A proposal should earn an
expensive solve either by having credible improvement potential or by materially
reducing uncertainty about such an important effect.

Training uses 6 elements per wavelength and 12 points per octave for every
candidate. Frequency sampling and spatial mesh density are separate convergence
questions: 6 EPW does not protect a diagnostic from missing a narrow feature
between solved frequencies. Every completed training run is therefore rescored
after factor-two frequency decimation. If Pattern Fit, Pattern Stability,
HF Retention, or crossover loading moves by more than two diagnostic points,
that run is marked sampling-unstable and excluded from surrogate learning.

Decimation is a warning, not proof of convergence. Before learned lever
directions or final rankings are trusted, the seed and representative initial
candidates must be checked at 16 PPO. Finalists also require 16-PPO confirmation. If
that confirmation materially changes rankings or learned effect directions, the
12-PPO model is invalidated and the search continues at the higher fidelity.
Results from different PPO levels must not be mixed in one surrogate unless
fidelity is explicitly modeled.

## Termination

Termination should be explicit and understandable. The initial defaults under
consideration are:

- a hard maximum of approximately 36-40 completed BEM candidates;
- an optional wall-time limit;
- stop after three consecutive batches produce less than one percentage point
  of meaningful Pareto improvement;
- stop proposing candidates that are effectively duplicates of evaluated
  designs; and
- always production-confirm the best three to five feasible candidates before
  declaring the search complete.

The evaluation or wall-time budget is the authoritative limit. Surrogate-model
confidence alone is not sufficient evidence that the engineering search is
finished.

## UX questions to resolve

The first implementation uses the browser to author operating intent and export
a separate search YAML. `run_bem_search.py` executes or resumes that request,
updates `search_report.html` throughout the run, retains candidate YAML and
standard reports, identifies impedance-feasible Pareto candidates, and creates
an automatic comparison of up to four finalists. Quick, normal, and thorough
presets correspond to 16, 36, and 60 completed BEM evaluations.

The following refinements remain open:

- support importing an existing search YAML back into the browser;
- add an optional wall-time limit and a tested stagnation threshold;
- validate whether reduced-PPO exploration preserves candidate ordering;
- allow selecting a different set of candidates for comparison from the search
  report; and
- make “use as new seed” more direct than importing the retained candidate YAML.
