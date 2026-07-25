# Low-level BEM candidate search

`bem_candidate_search` YAML version 1 is the retained low-level engine for
materializing HornCAD projects, rejecting invalid geometry, running NumCalc,
computing diagnostics, and retaining compact reports and response archives.

It supports both a fixed one-candidate evaluation and a generic manual
multi-candidate Pareto/surrogate search. The generic proposer is useful for
bounded research exploration, but it is not the measured horn optimizer and is
not an authority for automated design intent, multi-round lineage, exact-library
reuse, or global simulation accounting.

The measured optimizer in
[`docs/plans/design_recommendation_map.md`](../plans/design_recommendation_map.md)
uses one fixed `bem_candidate_search` per proposed coordinate. It owns:

- fixed coverage, throat, mouth-shape, and sag-axis enforcement;
- heuristic and evidence-driven proposal rounds;
- the shared hard simulation budget;
- approval and restart state;
- surface/impedance ranking;
- final confirmation and winner outputs.

The low-level search owns the mechanics within one evaluation, including
geometry preflight, solver retry, diagnostics, report generation, and safe
removal of raw solver working data after compact response validation.
