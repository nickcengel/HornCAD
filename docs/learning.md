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
only; steering rules and recommendation operations remain deferred.

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

Conical extension and throat angle, one fixed round-to-square transformation,
separate H/V behavior, rectangular validation, and sag are staged in the
[geometry research roadmap](plans/geometry_research_roadmap.md).
Each stage adds one physical effect through paired contrasts and held-out
prediction tests.

Historical observations and superseded plans are available in
[the archive](archive/pre-control-decoupling-2026-07/README.md), but they do not
control current scheduling or candidate selection.
