# Horn learning status

This page identifies where current learning is recorded. It deliberately avoids
copying coefficients and validation summaries already carried by versioned
model artifacts.

## Released round baseline

The completed canonical round study covers symmetric zero-extension horns at coverage
half-angles 30, 35, 40, 45, and 50 degrees and square mouths 250 through 450 mm.
It independently varies OSSE length, K, and N; S is derived. The registered
design, completion rules, and analysis terms are in the
[study plan](../examples/control-decoupling/study_plan.md).

The portable deliverable is not the raw candidate collection. The validated
primary and augmented models, uncertainty records, and training provenance are
specified by the [model pipeline](../examples/control-decoupling/model_pipeline.md).
V1 implements prediction only; steering rules and recommendation operations are
explicitly deferred.

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
