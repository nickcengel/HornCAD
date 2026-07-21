# BEM design recommendation map

## Intended workflow

The user selects mouth width, mouth height, and intended horizontal/vertical
coverage. The system returns the best-supported length, K, N, derived S,
predicted surface score, uncertainty, closure status, and nearby alternatives.

S is not an additional independent control once mouth, coverage, length, K, and
N are fixed. The search model may use S as a convenient coordinate and derive
length, but the delivered design must report both the physical length and the
resulting S.

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

For the current symmetric square-mouth study, model score as a function of
mouth size, coverage half-angle, S, K, and N. Convert the selected S/K/N point
to physical length using the same HornCAD geometry equations used to generate
the study. Rectangular and asymmetric designs require separate horizontal and
vertical inputs and should not be inferred from the square symmetric model
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
3. Continuous S/K/N optimization with uncertainty.
4. Confirmation simulations that update the measured dataset.
5. Frequency-resolved heatmap and energy-curve prediction.
