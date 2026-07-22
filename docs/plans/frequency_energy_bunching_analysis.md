# Frequency-energy bunching analysis

## Goal

The scalar slice-energy departure score measures how unevenly total angular
energy is distributed across frequency, but it discards the location, width,
and shape of the departures. Future work should retain the complete
frequency-dependent energy-density curve and determine which geometry controls
move, suppress, or redistribute each problematic frequency region.

This work complements the scalar surface score. It does not replace the
coverage-distribution, containment, outward-rise, or secondary -6 dB-line
diagnostics.

## Frequency-resolved diagnostic

All calculations use the simulated quadrant from 0 through 90 degrees. The
negative-angle quadrant is its mirror and is not separately simulated.

At each solved frequency, integrate linear energy over angle. Amplitude in dB
must be converted to a linear energy quantity before integration; dB values
must not be integrated directly. Normalize the resulting frequency curve by
its mean energy across the diagnostic band. Expressing the normalized result
in dB makes the ideal curve a constant 0 dB line.

Retain the complete normalized curve for every candidate, together with:

- RMS departure from the band mean.
- Peak and trough frequencies.
- Peak excess and trough depth in dB.
- Peak width and whether the departure is broad or narrow.
- Spectral centroid.
- Maximum local frequency slope.
- Horizontal and vertical curves when the two planes differ.

The public diagnostic should remain frequency resolved. Do not restore the
discarded worst-third-octave score as a public ranking metric.

## Controlled lever studies

Once a mouth/coverage design has a closed local K/N and length optimum, measure
matched local perturbations around it:

- Length or S below and above the incumbent.
- K below and above the incumbent in 0.5 steps. The Phase 3 audit found no
  practical design decision changed by quarter-step K probes.
- N below and above the incumbent, initially by 1.
- Selected diagonal perturbations when K/N or K/length interactions are
  plausible.

Change one independent control at a time wherever possible. Preserve the
incumbent as the common reference. For every perturbation, calculate the
frequency-by-frequency change in normalized slice energy.

Classify each observed response as:

1. **Translation:** a peak or trough moves in frequency.
2. **Suppression:** a departure becomes smaller without merely moving.
3. **Redistribution:** one region improves while another worsens.
4. **Broad reshaping:** a large portion of the diagnostic band changes.

Correlations across unrelated candidates are useful for screening, but causal
claims should rely on these matched perturbations.

## Frequency normalization

Analyze every feature in both absolute frequency and dimensionless frequency.
Useful initial coordinates include frequency times acoustic length divided by
sound speed, and frequency times mouth dimension divided by sound speed.

If peaks align after length normalization, length is primarily translating a
common feature. If they align after mouth normalization, mouth transition or
diffraction is a stronger explanation. Features that do not align under either
normalization require K, N, S, or interaction analysis.

Initial hypotheses to test, not assume, are:

- Length primarily translates spectral features.
- K redistributes energy broadly by changing where axial expansion occurs.
- N changes termination behavior and may affect narrower high-frequency
  features.
- Mouth size and coverage set the scale of mouth-transition effects.
- S may provide a useful combined coordinate across mouth sizes.

## Modeling

The eventual surrogate should predict the complete normalized energy-density
curve, not only its scalar RMS departure. A practical first model can represent
each curve with a low-dimensional basis such as principal components, then
predict the basis coefficients from mouth, coverage, S, K, and N.

The model must retain:

- Training-candidate identifiers and solver provenance.
- Parameter-domain limits.
- Distance to measured evidence.
- Prediction uncertainty.
- Cross-validation errors for both the curve and derived peak properties.

Do not use extrapolated curves as design evidence without a confirmation BEM
run.

Curve learning should produce conditional steering evidence rather than only a
predicted heatmap. For every matched S, K, or N perturbation, retain the parent
diagnostic state, parameter delta, frequency-by-frequency response delta,
component-score delta, and final-score delta. Aggregate a direction only inside
geometry regimes where its sign is consistent. Report contradictory regimes as
exceptions or interactions, not as noise to be averaged away.

The initial rule vocabulary includes containment state, high-frequency
narrowing or widening, profile-shape error, outward-rise concentration, and the
location and width of slice-energy bunching. Rules progress from hypothesis to
supported to validated only through held-out matched comparisons and eventual
prospective confirmation.

## Reports and visualizations

Candidate reports should eventually include:

- Normalized slice-energy density versus frequency with the 0 dB target.
- Highlighted peak and trough regions.
- Horizontal and vertical curves where available.
- Comparison with the search incumbent or parent candidate.
- A concise statement of whether the candidate moves, suppresses, or
  redistributes the parent's dominant departure.

The study index should add aggregate plots only after enough controlled pairs
exist. Useful plots include:

- Dominant bunching frequency versus length and normalized length.
- Dominant bunching frequency versus S.
- Peak excess versus K and N.
- Frequency-resolved parameter-sensitivity heatmaps.
- Observed versus predicted peak frequency and amplitude.

## Recommendation workflow

For a requested mouth and coverage, the future design map should be able to
offer:

- The highest predicted surface-score design.
- The design with the smoothest frequency-energy distribution.
- Near-optimal compromises within a configurable score tolerance.
- Parameter changes predicted to move a specified problem region upward or
  downward in frequency.
- Parameter changes predicted to suppress that region.

Every recommendation should report length, K, N, derived S, predicted surface
score, bunching properties, uncertainty, closure status, and nearest measured
candidates. A production choice should receive a confirmation BEM simulation
and then be added back to the measured dataset.

## Suggested implementation sequence

1. Persist the normalized per-frequency slice-energy curves and peak metadata.
2. Add the candidate-report curve and target line.
3. Generate controlled local perturbations from completed coupled-search
   optima.
4. Add normalized-frequency comparisons and paired sensitivity calculations.
5. Fit and cross-validate the curve surrogate.
6. Add diagnostic design recommendations to the index.
7. Confirm predicted optima and feed the results back into the model.
