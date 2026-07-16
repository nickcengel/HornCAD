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

The first implementation should search only these six variables:

- `k_h` and `k_v`;
- `osse_coverage_h_deg` and `osse_coverage_v_deg`;
- `length_mm`; and
- `extension_mm`.

The explicit names above should be used in search records so intended coverage
cannot be confused with OS-SE construction parameters.

Horizontal and vertical `s` are derived geometry values, not independent search
variables. After proposing length, extension, OS-SE coverage, and `k`, HornCAD
solves the geometry and derives `s_h` and `s_v`. A candidate is feasible only
when both values are strictly positive.

Because `k` is the principal feasibility control when length and OS-SE coverage
move, the implemented proposer repairs a negative-`s` proposal by raising the
corresponding `k` to the nearest positive-`s` region within its authored bounds.
It rejects the geometry only when the maximum allowed `k` cannot make `s`
positive. Repairs are retained in the candidate ledger.

Parameters such as `n`, `q`, and mouth squareness remain fixed in the initial
implementation. They may be added later if the six-variable search proves too
restrictive. Releasing all coupled geometry parameters at once would needlessly
increase the number of expensive BEM evaluations required to understand the
space.

## Search bounds

Length is bounded relative to the seed. The initial default is:

```text
0.85 * seed length <= candidate length <= 1.15 * seed length
```

The user may override that percentage. Search metadata must record both the
seed value and effective bounds.

Length is not a free path to improved low-frequency loading. Selection subtracts
a symmetric cost from all three optimization objectives while retaining the raw
physical diagnostics for review. The cost rises quadratically to 4 percentage
points at a 10% length change, then steeply to 20 points at 15%. Consequently a
candidate outside ±10% must deliver a substantial coverage improvement to
remain Pareto-competitive. Crossover loading is capped at 100% once the 0.7
constraint is satisfied, so additional impedance cannot offset this cost.

Extension should use explicit minimum and maximum lengths rather than only a
percentage of its seed value, because a seed extension may be zero. A provisional
default is zero through 15% of seed horn length. This default still needs to be
checked against the exact geometry convention and exposed clearly in the UX.

Bounds for `k_h`, `k_v`, and both OS-SE coverage parameters still need to be
chosen. They should be expressed relative to the seed where sensible, reject
invalid geometry before meshing, and be user-overridable without requiring the
user to understand the optimizer.

The search report records the configured range, seed value, and actual retained-
candidate span for every movable parameter. It also lists fixed `n_h` and `n_v`
explicitly so a search that did not explore termination exponent cannot be
mistaken for one that did. Each retained candidate receives a short label based
on its largest normalized departure from the seed (for example, “High
horizontal K”) instead of a generic geometry-feasibility note. When primary
traits repeat, every candidate in that group gains secondary (and, if needed,
additional) traits until its report label is distinct.

`N` should initially be explored as a structured second-stage termination study
around the strongest first-stage candidates. This avoids multiplying every
expensive BEM evaluation by an additional dimension before the main geometry
space has been screened, while still testing N before a final design is chosen.
Because N may interact with K and OS-SE coverage, the second stage must allow a
small local re-optimization rather than changing N only on one frozen geometry.

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

- coverage match;
- smoothness; and
- non-narrowing.

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
objectives and feasibility constraints. The provisional strategy is constrained
multi-objective Bayesian optimization:

1. Evaluate the user's seed at production resolution.
2. Generate an initial space-filling set of approximately 12 candidates within
   the allowed bounds.
   After K repair, reject any proposal within normalized distance 0.08 of a
   retained candidate so different proposals cannot collapse into effectively
   duplicate evaluated horns.
3. Fit surrogate models to objectives and constraints.
4. Propose hardware-appropriate batches that balance predicted Pareto
   improvement with exploration of uncertain regions.
5. Continue updating the models and Pareto set after each completed batch.
6. Confirm the leading candidates at production resolution.

A reduced points-per-octave setting may be useful during exploration, but it
must first be demonstrated that it does not materially reorder candidates. The
implemented default therefore remains 6 elements per wavelength and 10 points
per octave for every candidate.

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
