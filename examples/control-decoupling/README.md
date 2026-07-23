# Round control-decoupling study

This directory contains the registered experiment and retained artifacts for the
canonical symmetric, square, zero-extension OSSE control study. Its local
documents are kept with the data because they define how this particular dataset
was approved, generated, completed, and converted into a portable model.

## Reading order

1. [Launch review](launch_review.md) records the frozen pre-launch audit: scope,
   manifest identity, resource policy, storage policy, and known limitations.
2. [Study plan](study_plan.md) defines the registered domain, sampling design,
   execution order, terminal states, and analysis terms.
3. [Model pipeline](model_pipeline.md) defines the fitting, validation,
   rule-extraction, and `round_control_v1` export required after BEM completion.
4. The global [geometry research roadmap](../../docs/plans/geometry_research_roadmap.md)
   defines how this released baseline is later augmented with extension, throat
   angle, round-to-square morphing, separate H/V behavior, and sag.

The first three documents are study-specific provenance and must remain with the
example. The geometry roadmap is global because it governs later studies rather
than this manifest alone.

## Authority and generated artifacts

- `manifest.json` is authoritative for registered coordinates and reuse decisions.
- `benchmarks.json` registers external historical comparisons; benchmarks do not
  alter the experiment.
- `runtime_state.json`, `index.html`, search reports, and candidate reports are
  generated views of execution state and results.
- Each retained completed candidate keeps its project YAML, STL, report, and
  compressed `bem/responses.npz` required for future diagnostics.
- `analysis/bunching_physical_scales.md` is a regenerable snapshot testing
  frequency-energy bunching against analytic geometry scales, extremum spacing,
  matched control changes, and a one-dimensional Webster reflection screen;
  its JSON companion retains the full machine-readable evidence.

Do not infer new queued work from an older report or planning document. Changes
to the registered experiment require an explicit revised manifest and launch
review rather than an edit to generated HTML.
