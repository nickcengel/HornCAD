# Documentation index

This index distinguishes maintained specifications from historical research
records. A document under `docs/plans/` is an active future-work contract. Old
execution plans belong under `docs/archive/` and must not be used to schedule
new BEM work.

## Authoritative current documents

- [HornCAD geometry](reference/horncad_geometry.md): geometry equations,
  coordinate conventions, authored length, and export behavior.
- [BEM surface diagnostics](reference/bem_surface_diagnostics.md): implemented
  angle-frequency diagnostics and final surface score.
- [Throat-impedance diagnostic](reference/throat_impedance_diagnostics.md):
  experimental model output for the extension study; neither a ranking input
  nor part of the surface score.
- [Frequency-energy bunching analysis](plans/frequency_energy_bunching_analysis.md):
  planned frequency-resolved learning and steering work.
- [Design recommendation map](plans/design_recommendation_map.md): intended
  model-backed workflow beyond the released prediction-only API.
- [Horn design application API](reference/design_application_api.md): Python
  prediction inputs/outputs plus explicitly deferred diagnosis, recommendation,
  and experiment-selection operations.
- [Learning status](learning.md): released round-model status and the boundary
  between validated evidence and later geometry learning.

The canonical round study is documented with its artifacts rather than copied
into this directory:

- [registered study plan](../examples/control-decoupling/study_plan.md);
- [model fitting and export pipeline](../examples/control-decoupling/model_pipeline.md);
- [launch review](../examples/control-decoupling/launch_review.md).

The cross-study [geometry research roadmap](plans/geometry_research_roadmap.md)
is global because it governs the extension, mouth-shape, H/V, and sag studies
that follow the round baseline.

`examples/control-decoupling/manifest.json` is authoritative for the completed
registered simulations. Generated reports and `runtime_state.json` record their
terminal execution state; prose from an older study must never add work to that
manifest. Released portable models are
`models/round_control_primary_v1/` and
`models/round_control_augmented_v1/`.

## Current terminology

- **Length** means only the axial OSSE-profile length.
- **Extension** means the separately authored conical throat extension.
- **Profile-plus-extension length** means OSSE length + extension.
- **Mouth sag** is a local axial setback, not an additive length.
- **Measured exported span** means the actual `max(z) - min(z)` of the selected
  surface or body export.
- **S** is derived from the authored geometry; it is not an independent control
  in the round control-decoupling study.
- Coverage values are half-angles.

## Evidence and archives

The PDFs under `reference/research/` are background literature, not HornCAD
implementation specifications. The 200 mm and 60-degree summaries under
`reference/` are explicitly historical boundary evidence.

Superseded search regimes, generated snapshots, and the earlier learning log
are retained under [the July 2026 archive](archive/pre-control-decoupling-2026-07/README.md).
They preserve provenance but are not current policy, queues, model releases, or
statements of live status.
