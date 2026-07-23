# Launch review

No BEM work is started by the planner or materializer. This file describes the
exact materialized queue that must be reviewed before launch.

- Frozen manifest SHA-256: `d3e0c8e4be17cfba943f452d25e5a159c50b6949b3ae0815a3dd613fe6c1d1b5`
- Required feasible, profile-distinct factorial/validation candidates: 566
- Conditional axis-closure candidates: 86
- Absolute new-BEM ceiling if every closure probe triggers: 652
- Search directories: 209
- Parallelism: two independent searches, ten solver workers each.
- Scheduling: adjacent independent waves overlap to eliminate per-wave idle
  tails; the only barrier is before evidence-gated axis closure.
- Storage: validate and retain responses.npz, STL, and reports; delete each raw
  project-NumCalc work tree immediately after its candidate completes.
- Domain: 30-50 degree coverage half-angle and 250-450 mm round mouth diameters.
- Geometry: axisymmetric, round-mouth, zero-extension OS-SE horns only.

| Ordered wave | Searches | Candidates |
| --- | ---: | ---: |
| core-axis | 25 | 171 |
| boundary-sentinel | 23 | 24 |
| axis-closure | 86 | 86 |
| two-factor-face | 25 | 208 |
| three-factor-corner | 25 | 113 |
| locked-validation | 25 | 50 |

Every feasible, profile-distinct canonical center, axis, face, and corner runs.
There is no score-based factorial pruning because control effects may reverse by
mouth, coverage, derived S, or length. Locked validation runs last and is never
used to fit or select candidates.

Axis-closure searches are materialized but run only when the corresponding inner
endpoint points outward by the registered score/diagnostic rule. N=2 is never a
regular grid point; it is only the lower safety-bound probe after N=4 improves
over N=8.

The runner requires the exact hash above through
`--reviewed-manifest-sha256`; changing and rematerializing the manifest invalidates
that approval. A failed search releases its slot and is recorded while unrelated
work continues. The study reports blocked rather than complete if any isolated
failure remains.
