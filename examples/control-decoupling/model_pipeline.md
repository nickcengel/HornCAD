# Round-control model fitting and export pipeline

## Required outcome

The control-decoupling study is incomplete until it produces a compact,
executable model of symmetric, square, zero-extension OS-SE horns. Candidate
reports and NPZ response surfaces are source evidence, not the primary study
deliverable.

The exported model must answer:

```text
F(mouth, coverage, body length, K, N)
    -> surface score and component diagnostics
    -> calibrated prediction uncertainty
    -> local control effects and interactions
```

S remains a derived geometry result. It must never be accepted as an independent
input coordinate.

## Portable deliverables

The pipeline writes a versioned directory:

```text
models/round_control_v1/
├── model.json
├── validation.json
├── rules.json
├── training_index.json
└── model_card.md
```

`model.json` is the executable artifact. It contains plain JSON numbers and
arrays rather than Python pickles so the same model can run in Python and the
browser. The other files document evidence, limitations, and interpretation.

The retained candidate `responses.npz` files remain the authoritative source for
future diagnostics, but routine prediction and study design must not require
loading them.

## Provenance lock

Every export records:

- control-study manifest SHA-256;
- execution-plan SHA-256;
- diagnostic implementation/version hash;
- solver/frequency fingerprint;
- geometry implementation/version hash;
- model schema version;
- fitting-code Git commit;
- creation time and complete coordinate-ID list.

Changing diagnostics creates a new model version. An old model must never be
silently relabeled with newly calculated scores.

## Input assembly

### Primary confirmatory dataset

The primary fit includes only:

- completed canonical factorial coordinates;
- strict exact historical reuses registered by the frozen manifest.

It excludes:

- locked validation coordinates;
- `benchmarks.json` optimized historical benchmarks;
- geometry-rejected and geometry-redundant coordinates;
- conditional closure coordinates unless a later model version explicitly
  declares an expanded-boundary fit;
- arbitrary historical optimizer traces.

All included candidates are rescored directly from retained NPZ response
surfaces with the selected diagnostic implementation. Stored report scores are
comparison fields, not fitting inputs.

### Locked validation dataset

The two registered validation coordinates in each mouth/coverage cell remain
unavailable to model fitting, model selection, regularization selection, rule
extraction, and candidate ranking. They are opened only after the model is
frozen.

### Secondary augmented dataset

A separately named augmented model may include compatible historical responses
with source provenance and sampling weights. It cannot replace the primary model
or fill missing canonical contrasts. Primary and augmented validation results
must be reported separately.

### Training index

`training_index.json` contains one row per response with:

- coordinate ID and source path;
- mouth, coverage, body length, reference length, length factor, K, N, and
  derived S;
- response/diagnostic hashes;
- inclusion role: fit, locked validation, external benchmark, or excluded;
- exclusion reason where applicable;
- all fitted response values.

This provides an auditable bridge from a model coefficient back to its source
NPZ without embedding raw response surfaces in the model.

## Response vector

Fit each response independently while retaining their residual covariance:

1. surface score;
2. mean containment;
3. profile RMS error;
4. slice-energy RMS departure;
5. outward-rise violation;
6. secondary minus-six-dB RMS error.

The model must expose all six predictions. Surface score alone is insufficient
for control advice.

## Cell-local model

Each of the 25 mouth/coverage cells uses the same preregistered quadratic basis:

```text
1, L, K, N, L², K², N², L×K, L×N, K×N
```

Here `L` is body-length factor relative to the registered cell reference length.
L, K, and N are centered and scaled using constants stored in `model.json`.
Physical values are always preserved in inputs and outputs.

The canonical preflight established rank 10 in every cell. Fitting must fail
closed if the completed dataset loses that rank. No term selection or stepwise
regression is permitted because it would make control meanings inconsistent
between cells.

The cell export stores, for every response:

- ten coefficients;
- coefficient covariance;
- residual covariance across responses;
- observed input extent;
- condition number and effective rank;
- center prediction, gradient, and Hessian.

Regularization is allowed only if numerical or validation evidence requires it.
Its strength must be selected without locked validation data and recorded in the
export.

## Mouth/coverage interpolation

The 25 cell-local coefficient sets form ten coefficient fields for each response
over the 5×5 mouth/coverage grid. The cross-cell model interpolates those fields,
not raw optimizer ranks.

Candidate interpolators, in increasing complexity, are:

1. bilinear coefficient interpolation;
2. regularized tensor-product spline;
3. a smooth Gaussian-process coefficient field.

Use the simplest method that passes leave-one-cell-out testing. Complexity and
hyperparameters are selected using only canonical fitting coordinates. If no
method supports a requested region, the model must return high uncertainty or
`unsupported`; it must not manufacture a confident recommendation.

The reference-length field `L0(mouth, coverage)` is exported separately. A user
body length is converted to length factor with this field before evaluating the
control response.

## Geometry gate

Prediction never overrides deterministic geometry. Before model evaluation, the
existing OS-SE solver must:

- solve derived S;
- apply the same geometry-feasibility checks used by the study;
- reject disc-like or otherwise invalid geometry;
- identify extrapolation beyond the sampled physical profile extent.

`model.json` stores the sampled bounds and required geometry-policy version, but
the exact geometry implementation remains authoritative.

## Uncertainty

Prediction uncertainty combines:

- cell coefficient covariance;
- local residual error;
- cross-cell interpolation error;
- distance outside the observed L/K/N support;
- leave-one-cell-out error;
- locked-validation calibration after model freeze.

The API returns a point prediction plus calibrated intervals for every response.
Intervals must widen near geometry boundaries and during extrapolation. Locked
validation is used to calibrate and report uncertainty, never to refit the frozen
primary model.

## Validation sequence

Validation occurs in this order:

1. **Structural audit:** provenance hashes, unique coordinates, rank 10, finite
   coefficients, and deterministic rebuild.
2. **Within-cell fit audit:** residual plots and influence diagnostics using only
   fitting coordinates.
3. **Leave-one-cell-out audit:** predict omitted mouth/coverage cells to test
   coefficient interpolation.
4. **Locked validation:** predict all 50 locked coordinates exactly once after
   model and interpolation choices are frozen.
5. **Historical benchmark audit:** classify the 25 external optimized benchmarks
   without adding them to the primary fit.
6. **Python/browser parity:** identical test vectors must agree within a recorded
   numerical tolerance.

Validation reports absolute and signed error separately for every response,
cell, and geometry region. A model may be released with limited support, but its
unsupported regions must be explicit.

No control rule is actionable unless its predicted improvement is larger than
both:

- the response's practical materiality threshold; and
- twice the relevant local 90th-percentile validation error.

This prevents model noise from becoming design advice.

## Historical optimum audit

For each benchmark and previous cell winner, evaluate the local gradient,
curvature, model-supported search region, and uncertainty. Classify it as:

- supported optimum;
- near-optimal;
- unresolved or boundary-limited;
- likely superseded;
- score-optimal with a material diagnostic tradeoff.

A predicted replacement is a proposal, not a result. It requires confirmation
BEM before replacing a benchmark.

## Rule extraction

`rules.json` is generated from the validated response field, not written from
informal observations. The extractor samples the valid domain and evaluates
finite practical changes in L, K, and N plus the analytic model gradient and
curvature.

A rule records:

- mouth, coverage, L/K/N/S region;
- affected diagnostic;
- control direction and practical step;
- expected response range;
- relevant interactions;
- confidence and validation support;
- counter-effects on other diagnostics;
- source model and rule-extraction version.

Rules are emitted only for contiguous regions with stable, material effects and
uncertainty that excludes a direction reversal. Weak or reversing effects remain
available through prediction but are not promoted to prose guidance.

## Executable API

Python and browser implementations expose equivalent operations:

```text
predict(mouth, coverage, length, K, N)
    -> diagnostics, intervals, derived geometry, support status

improve(candidate, objectives, constraints)
    -> related candidates, expected diagnostic deltas, uncertainty, rationale

design(mouth, coverage, constraints)
    -> diverse predicted leaders for confirmation BEM

select_experiments(domain, budget)
    -> points that reduce uncertainty or distinguish competing control models
```

`improve` uses the complete diagnostic Jacobian and Hessian. It must not optimize
surface score alone. Constraints and diagnostic tradeoffs remain visible in its
output.

## Use by later geometry studies

Later studies learn corrections relative to this frozen baseline:

```text
round-control prediction
    + conical-extension delta
    + round-to-square delta
    + H/V-coupling residual
```

Each correction is accepted only where paired validation supports an additive or
conditional correction. The round model supplies baseline predictions, parent
selection, compensating L/K/N directions, and uncertainty. New geometry studies
must not silently retrain or overwrite the round-control model.

## Required implementation commands

The implementation should provide idempotent commands equivalent to:

```text
python -m app.tools.assemble_round_control_dataset
python -m app.tools.fit_round_control_model
python -m app.tools.validate_round_control_model
python -m app.tools.export_round_control_model
```

They may share internal code, but the artifacts and failure boundaries remain
separate. Re-running with identical inputs must produce numerically identical
model content apart from explicitly excluded creation timestamps.

## Release gate

`round_control_v1` is released only when:

- every required coordinate has a terminal audited status;
- all included NPZ archives validate;
- every cell retains the registered model rank;
- locked validation remained untouched until model freeze;
- diagnostic-specific validation errors and support limits are published;
- uncertainty is calibrated conservatively enough to cover observed locked
  errors;
- Python and browser predictions pass parity tests;
- benchmarks are classified and any proposed replacements are clearly marked
  unconfirmed;
- `model.json`, validation, rules, training index, and model card agree on all
  provenance hashes.

Failure of a release gate produces a limited-support model and a documented next
experiment. It must not be hidden by reporting only aggregate score accuracy.
