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
  isolated prototype for the extension study; not a live ranking input.
- [Frequency-energy bunching analysis](plans/frequency_energy_bunching_analysis.md):
  planned frequency-resolved learning and steering work.
- [Design recommendation map](plans/design_recommendation_map.md): intended
  model-backed user workflow after the current study validates.

The canonical round study is documented with its artifacts rather than copied
into this directory:

- [registered study plan](../examples/control-decoupling/study_plan.md);
- [model fitting and export pipeline](../examples/control-decoupling/model_pipeline.md);
- [launch review](../examples/control-decoupling/launch_review.md).

The cross-study [geometry research roadmap](plans/geometry_research_roadmap.md)
is global because it governs the extension, mouth-shape, H/V, and sag studies
that follow the round baseline.

`examples/control-decoupling/manifest.json` is authoritative for the currently
registered simulations. Generated reports describe live progress; prose from an
older study must never add work to that manifest.

## Current terminology

- **Length** means only the axial OSSE-profile length.
- **Extension** means the separately authored conical throat extension.
- **Sag distortion** means the axial extent added by mouth sag.
- **Total length** means OSSE length + extension + axial sag distortion.
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
