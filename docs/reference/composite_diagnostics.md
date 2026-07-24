# Composite surface and impedance score

Composite score v1.0 is a secondary comparison diagnostic:

`composite = 0.75 * surface_score_v2.3 + 0.25 * throat_impedance_score_v2.3.0`

Both inputs are percentages on a 0–100 scale. The composite is unavailable
unless both component scores are finite and available.

The composite does not replace either component and is not authoritative for
candidate ranking. Surface score v2.3 remains the sole ranking score. Reports
show the composite to make the surface/loading tradeoff visible and to collect
evidence about whether impedance should influence a future decision rule.

The implementation lives in `app/tools/composite_diagnostics.py`. Its JSON
result records the component values, weights, versions, and
`authoritative_for_ranking: false`.
