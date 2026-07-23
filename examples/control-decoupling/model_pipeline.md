# Round-control model fitting and export pipeline

## Release status

The prediction-only v1 release is complete. Primary and augmented models,
audited training indexes, validation results, provenance, model cards, and
placeholder rule files are present under `models/`. Sections below describe the
implemented prediction release and explicitly label capabilities deferred to a
later version.

The later [unified-v2 consolidation](round_control_v2_plan.md) retained the full
5×5 domain and tested five global historical weights against twelve new locked
BEM responses. None passed its release gates. Consequently, primary v1 is the
sole production baseline; augmented v1 remains research comparison evidence.
No v2 model was released.

## Required outcome

The completed control-decoupling study produces compact, executable models of
axisymmetric, round-mouth, zero-extension OS-SE horns. Candidate reports and NPZ
response surfaces remain authoritative source evidence rather than the routine
prediction interface.

The exported model must answer:

```text
F(mouth, coverage, OSSE profile length, K, N)
    -> surface score and component diagnostics
    -> calibrated prediction uncertainty
    -> interpretable quadratic response fields
```

S remains a derived geometry result. It must never be accepted as an independent
input coordinate.

## Portable deliverables

The pipeline writes two versioned directories:

```text
models/round_control_primary_v1/
├── model.json
├── primary_freeze.json
├── validation.json
├── provenance.json
├── rules.json
├── training_index.json
└── model_card.md

models/round_control_augmented_v1/
├── model.json
├── validation.json
├── provenance.json
├── rules.json
├── training_index.json
└── model_card.md
```

Each `model.json` is an executable plain-JSON artifact rather than a Python
pickle, so Python and browser evaluators share the same coefficients. The
primary model is canonical evidence only. The augmented model adds compatible,
density-weighted historical evidence after primary validation and retains the
primary prediction alongside it.

`rules.json` is a release placeholder with no actionable rules because
`diagnose()`, `improve()`, automated design, and experiment selection are
deferred. The other files document evidence, limitations, and interpretation.

The retained candidate `responses.npz` files remain the authoritative source for
future diagnostics, but routine prediction and study design must not require
loading them.

## Provenance lock

The model and `provenance.json` record:

- control-study manifest SHA-256;
- execution-plan SHA-256;
- diagnostic implementation/version hash;
- complete coordinate hash;
- fitting implementation SHA-256;
- fitting-code Git commit;
- model, validation, and training-index hashes.

The source audit separately records the uniform solver configuration and
response-grid fingerprints, archive counts, diagnostic-reproduction tolerance,
duplicate-response deduplication, and NumCalc cleanup result.

Changing diagnostics creates a new model version. An old model must never be
silently relabeled with newly calculated scores.

## Input assembly

### Primary confirmatory dataset

The primary fit includes only:

- completed canonical factorial coordinates;
- strict exact historical reuses registered by the frozen manifest.

It excludes:

- locked validation coordinates;
- non-reference `benchmarks.json` optimized historical benchmarks;
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

The separately named augmented v1 model includes compatible historical responses
with source provenance and sampling weights. It does not replace the primary
model or fill missing canonical contrasts. Primary and augmented validation
results are reported separately.

### Training index

`training_index.json` contains one row per response with:

- coordinate ID and source path;
- mouth, coverage, OSSE profile length, reference length, length factor, K, N, and
  derived S;
- response/diagnostic hashes;
- inclusion role: `fit`, `locked_validation`, `historical_challenge`, or
  `excluded`, plus a separate benchmark flag;
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

The release also exposes `throat_impedance_score` from the current experimental
normalized-magnitude diagnostic as an independent seventh response. It is
preparatory evidence for extension and throat-angle work: it does not alter the
six-response surface score, model selection, benchmark ranking, or the choice
between the primary and augmented model.

## Cell-local model

Each of the 25 mouth/coverage cells uses the same preregistered quadratic basis:

```text
1, L, K, N, L², K², N², L×K, L×N, K×N
```

Here `L` is OSSE-profile-length factor relative to the registered cell reference
length. L, K, and N are centered and scaled using constants stored in
`model.json`. Physical values are always preserved in inputs and outputs.

The canonical preflight established rank 10 in every cell. Fitting must fail
closed if the completed dataset loses that rank. No term selection or stepwise
regression is permitted because it would make control meanings inconsistent
between cells.

The cell export stores, for every response:

- ten coefficients;
- coefficient covariance;
- residual covariance across responses;
- observed input extent;
- condition number and effective rank.

Regularization is allowed only if numerical or validation evidence requires it.
Its strength must be selected without locked validation data and recorded in the
export.

## Mouth/coverage interpolation

The 25 cell-local coefficient sets form ten coefficient fields for each response
over the 5×5 mouth/coverage grid. The cross-cell model interpolates those fields,
not raw optimizer ranks.

V1 uses bilinear coefficient interpolation. Canonical leave-one-cell-out testing
compares its coefficient-field error with a nearest-cell baseline; bilinear is
retained because it wins that comparison. Off-grid mouth/coverage predictions
are returned as limited-support with widened intervals. Values outside the
sampled grid are explicitly extrapolated.

The reference-length field `L0(mouth, coverage)` is exported separately. A
user's OSSE profile length is converted to length factor with this field before
evaluating the control response.

## Geometry gate

Prediction never overrides deterministic geometry. Before model evaluation, the
existing OS-SE solver must:

- solve derived S;
- apply the same geometry-feasibility checks used by the study;
- reject disc-like or otherwise invalid geometry;
- identify extrapolation beyond the sampled physical profile extent.

`model.json` stores the sampled bounds and fixed geometry-policy parameters, but
the exact geometry implementation remains authoritative.

## Uncertainty

V1 interval half-widths use the larger of the locked-validation 90th-percentile
absolute error and 1.645 times the largest cell residual standard deviation.
The API widens them for off-support L/K/N, mouth, or coverage values and labels
the result extrapolated. Off-grid in-domain mouth/coverage interpolation is
limited-support. Locked validation calibrates uncertainty but never refits the
frozen primary model.

## Validation sequence

Validation occurs in this order:

1. **Structural audit:** provenance hashes, unique coordinates, rank 10, finite
   coefficients, and deterministic rebuild.
2. **Within-cell fit audit:** rank, condition number, coefficients, covariance,
   residual covariance, and support using only fitting coordinates.
3. **Leave-one-cell-out audit:** predict omitted mouth/coverage cells to test
   coefficient interpolation.
4. **Locked validation:** predict all 50 locked coordinates exactly once after
   model and interpolation choices are frozen.
5. **Historical benchmark audit:** report errors for all 25 external optimized
   benchmarks without adding non-reference benchmarks to the primary fit.
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

## Deferred historical optimum classification

The v1 validation reports prediction errors for every registered benchmark.
Gradient/curvature classification remains deferred with `diagnose()` and
`improve()`. A later version may classify each benchmark as:

- supported optimum;
- near-optimal;
- unresolved or boundary-limited;
- likely superseded;
- score-optimal with a material diagnostic tradeoff.

A predicted replacement is a proposal, not a result. It requires confirmation
BEM before replacing a benchmark.

## Deferred rule extraction

V1 ships `rules.json` as an explicit empty placeholder. No rule is actionable.
A later extractor must generate rules from the validated response field rather
than informal observations, sampling finite practical L/K/N changes plus model
gradient and curvature.

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

Python and browser implementations expose equivalent prediction evaluation.

The concrete Python value types and prediction façade are implemented in
`app.design_api` and documented in
[`docs/reference/design_application_api.md`](../../docs/reference/design_application_api.md).
That consumer contract must remain stable as the round backend grows correction
layers for later geometry studies.

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

Only `predict` is implemented in v1. The other operations deliberately raise
`ModelNotReadyError`; their types remain reserved so later releases need not
change callers. When implemented, `improve` must use the complete diagnostic
Jacobian and Hessian rather than optimize surface score alone.

## Use by later geometry studies

The experimental order and paired-study requirements for these augmentations are
specified in
[geometry_research_roadmap.md](../../docs/plans/geometry_research_roadmap.md).

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

## Implementation commands

The implementation provides idempotent commands equivalent to:

```text
python -m app.tools.assemble_round_control_dataset
python -m app.tools.fit_round_control_model
python -m app.tools.validate_round_control_model
python -m app.tools.export_round_control_model
```

They share one versioned implementation, but the artifacts and failure
boundaries remain separate. Re-running with identical inputs produces
byte-identical model, validation, and training-index content.

## Release gate

The primary and augmented v1 models are released only when:

- every required coordinate has a terminal audited status;
- all included NPZ archives validate;
- every cell retains the registered model rank;
- locked validation remained untouched until model freeze;
- diagnostic-specific validation errors and support limits are published;
- uncertainty is calibrated conservatively enough to cover observed locked
  errors;
- Python and browser predictions pass parity tests;
- all 25 benchmarks receive a separate prediction-error audit;
- `model.json`, validation, rules, training index, and model card agree on all
  provenance hashes.

Rule extraction and optimum classification are not release gates for the
prediction-only v1 model; their placeholder/deferred status must remain explicit.
Failure of a prediction release gate produces a limited-support model and a
documented next experiment rather than being hidden by aggregate score accuracy.
