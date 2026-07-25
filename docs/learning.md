# Horn learning status

This page identifies where current learning is recorded. It deliberately avoids
copying coefficients and validation summaries already carried by versioned
model artifacts.

## Round baseline evidence

The completed canonical round study covers axisymmetric zero-extension horns at
coverage half-angles 30, 35, 40, 45, and 50 degrees and round mouth diameters
250 through 450 mm.
It independently varies OSSE length, K, and N; S is derived. The registered
design, completion rules, and analysis terms are in the
[study plan](../examples/control-decoupling/study_plan.md).

Primary v1 remains available as an API-compatible legacy reference estimator;
augmented v1 remains research comparison evidence. A completed
[unified-v2 validation](../examples/round-control-v2-validation/README.md)
showed that no tested global historical weight made the ten-term quadratic
accurate enough in jointly sparse L/K/N regions, so no v2 model was released.
The subsequent
[nonlinear evaluation](../examples/round-control-nonlinear-evaluation/README.md)
also failed its locked challenge. Neither v1 model is therefore a validated
global interpolation foundation.

The full mouth/coverage grid remains in scope. Evidence-sparse joint control
combinations are limited-support even when each individual control lies inside
its nominal one-dimensional range. Future geometry studies require measured
round parents for paired comparisons. V1 implements provisional prediction
only; its model-only steering and recommendation methods remain deferred.
Practical automated design is instead implemented by the measured,
restartable BEM optimizer.

The completed study does provide measured seed rules independent of the failed
global surrogate. The
[round-control heuristic reference](reference/round_control_heuristics.md)
publishes reference-length evidence, coupled length/K branches,
coverage-conditioned S bands, alternate high-score zones, and an executable H/V
length/sag starting construction. Its exact-cell seeds now use the diagnostic-
of-record surface-v2.3 winner map.

A bounded ten-case
[wide-coverage closure](plans/round_control_wide_coverage_closure.md)
found at most a 0.268-point local improvement in the selected 45°/50° seams;
the long 50°/450 mm continuation lost 9.944 and 29.793 points. The project
owner chose not to run the two conditional infinite-baffle controls. The
leading provisional explanation is mouth-edge diffraction—wider coverage sends
more energy to the lip, with the disturbance tracking aperture-scaled
frequency—but causality has not been isolated. No further round simulations
are planned for this issue. The measured map and this mechanism hypothesis
carry into intended non-round H/V, corner, sag, and baffle geometry.

## Non-round transfer evidence

The completed
[non-round transfer study](../examples/non-round-transfer-study/study_plan.md)
used 51 new BEM simulations and recorded one zero-budget geometry rejection.
Independent measured H/V K and N seeds are retained without averaging. The
width/height-weighted common length remains the default because the median
S-balanced-minus-weighted development difference was only +0.0097 point,
inside the registered ±0.5-point tie window.

That default is conditional on geometry feasibility. Equal-coverage L4 made
the weighted vertical S nonpositive, while its S-balanced construction passed
the locked transfer gate. Reversed-coverage L5 failed the weighted locked gate
by 3.878 points; S-balanced closure reduced the deficit to 2.533 points. The
optimizer therefore falls back to S-balanced for nonpositive axis S and widens
its first round near L5-like reversed-coverage intents.

All eight equal-H/V square transforms improved on their exact round parents,
with a median +3.372 surface-v2.3 points. This is strong corner-transfer
evidence but not a global additive square-mouth score correction.

## Prior evidence carried forward

Earlier searches supplied hypotheses and experiment-design constraints:

- useful length changes strongly with mouth and coverage;
- small nominal K/N changes often produce no practically meaningful score or
  geometry change;
- N sensitivity can collapse in low-S geometries;
- quarter-step K refinement did not change practical selections;
- N near 2 and distributed extreme K/N corners were consistently poor;
- frequency-resolved diagnostics are required to learn how controls move or
  smooth energy bunching.

These are prior evidence, not final universal horn rules. The canonical study
tested independent L/K/N effects in every retained mouth/coverage cell and used
locked validation before releasing the exported model.

## Later geometry learning

Conical extension/throat initialization and square/independent-HV transfer are
complete. Sag and complementary H/V profile work remain staged in the
[geometry research roadmap](plans/geometry_research_roadmap.md).

Historical observations and superseded plans are available in
[the archive](archive/pre-control-decoupling-2026-07/README.md), but they do not
control current scheduling or candidate selection.
