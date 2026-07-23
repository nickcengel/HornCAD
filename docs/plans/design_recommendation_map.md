# BEM design recommendation map

## Status

The released v1 API implements prediction, support labeling, intervals, derived
geometry, and nearest evidence. Automated diagnosis, improvement, design search,
rule extraction, and experiment selection remain future work governed by this
plan.

## Intended workflow

The user selects mouth width, mouth height, and intended horizontal/vertical
coverage. The system returns the best-supported OSSE length, K, N, derived S,
predicted surface score, uncertainty, closure status, and nearby alternatives.

S is not an additional independent control once mouth, coverage, OSSE length,
K, and N are fixed. The canonical round model uses OSSE length, K, and N as its
independent profile controls and reports the resulting S. A later internal model
may use S as an additional derived feature, but it must not redefine length or
invert S into a replacement authored length.

## Stored evidence

The design map must not be only a table of winners. Preserve every evaluated
candidate, including low scores that establish boundaries, with:

- Physical and OS-SE parameters.
- Derived S and dimensionless length ratios.
- Surface score and component diagnostics.
- Frequency-resolved diagnostic curves when available.
- Solver, mesh, search, and model provenance.
- Completion, failure, pruning, and closure status.
- Links to retained reports and geometry artifacts.

Candidates may have bulky artifacts thinned under a separate retention policy,
but their compact study records must remain available to the model.

## Recommendation model

For the released symmetric square-mouth study, model every component diagnostic
and score as a function of mouth size, coverage half-angle, OSSE length, K, and
N, with derived S and normalized geometry available as secondary features and
support checks. Rectangular and asymmetric designs require separate horizontal
and vertical inputs and should not be inferred from the square symmetric model
without validation.

The recommendation process should:

1. Reject geometrically invalid combinations.
2. Search the measured/interpolated domain for the predicted optimum.
3. Report prediction uncertainty and distance to measured evidence.
4. Return alternatives within a configurable score tolerance.
5. Prefer closed optima over slightly higher unresolved boundary predictions.
6. Require a confirmation BEM solve for extrapolation or a production design.

Interpolation is allowed only inside a sufficiently sampled domain.
Extrapolation must be clearly labeled and must not silently become a final
recommendation.

## Diagnostic learning and steering rules

The final surface score decides whether a proposal is better overall, but it is
not the only learning target. Fit and compare changes in containment, profile
RMS error, outward-rise violation, slice-energy departure, the secondary -6 dB
line, and their retained frequency traces. This separates three outputs:

1. **Prediction:** which unmeasured candidate is likely to score higher.
2. **Diagnosis:** which acoustic behavior currently limits the result.
3. **Steering:** which OS-SE control direction is likely to correct that
   behavior in the current geometry regime.

Every learned steering rule must state its diagnostic condition, geometry
regime, parameter action, expected component and final-score changes, support
count, exceptions, and confidence. Confidence is `hypothesis` for uncontrolled
correlation, `supported` for repeated matched perturbations, and `validated`
only after the rule predicts held-out or prospective results. For example,
"decrease K when containment is already high but the coverage trace narrows too
quickly" is learnable from matched K perturbations and the frequency-resolved
-6 dB traces; candidates that change K, N, and S together may suggest that rule
but cannot establish it.

The learner should therefore retain multi-output diagnostic models and paired
local effects even when a scalar-score model ranks proposals more accurately.
Feature importance alone is not a steering rule, and a component improvement
is not accepted when its weighted final-score tradeoff is negative.

## Output schema

A versioned machine-readable record should include at least:

```json
{
  "mouth_width_mm": 400,
  "mouth_height_mm": 400,
  "coverage_h_deg": 45,
  "coverage_v_deg": 45,
  "recommended": {
    "length_mm": 143.1,
    "k_h": 4.0,
    "k_v": 4.0,
    "n_h": 5.0,
    "n_v": 5.0,
    "s_h": 1.9,
    "s_v": 1.9,
    "predicted_surface_score": 89.1,
    "closure_status": "closed",
    "prediction_uncertainty_points": 0.5
  }
}
```

The actual values above are illustrative and must not be treated as a final
recommendation without closed-study evidence.

## Index interface

The index should eventually provide a design-recommendation panel with:

- Mouth and coverage inputs.
- Recommended length, K, N, and S.
- Predicted surface score and uncertainty.
- Closure and interpolation/extrapolation status.
- Nearest measured candidates and report links.
- Near-equivalent alternatives, including shorter options.
- A way to materialize a HornCAD project/STL and request confirmation.

Frequency-energy modeling described in
`frequency_energy_bunching_analysis.md` should later add choices for maximum
surface score, smoothest spectral energy distribution, and compromises between
the two.

## Delivery stages

1. Exact lookup for measured closed mouth/coverage combinations.
2. Validated interpolation between sampled mouth sizes and coverage angles.
3. Continuous OSSE-length/K/N optimization with derived-S support checks and
   uncertainty.
4. Confirmation simulations that update the measured dataset.
5. Frequency-resolved heatmap and energy-curve prediction.

The fitting, validation, and portable export contract is defined in
[`examples/control-decoupling/model_pipeline.md`](../../examples/control-decoupling/model_pipeline.md).
Later geometry corrections follow
[`geometry_research_roadmap.md`](geometry_research_roadmap.md).
