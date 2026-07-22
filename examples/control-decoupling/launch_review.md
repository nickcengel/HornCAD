# Launch review

No BEM work is started by the planner or materializer. This file describes the
exact materialized queue that must be reviewed before launch.

- Frozen manifest SHA-256: `395284e7e3f908539346ed5c7290a9e8b5243763f0e7525ce91530c389929e8d`
- Required BEM candidates before evidence-based pruning: 566
- Conditional axis-closure candidates: 86
- Absolute new-BEM ceiling if every closure probe triggers: 652
- Search directories: 417
- Parallelism: two independent searches, ten solver workers each.
- Domain: 30-50 degree coverage half-angle and 250-450 mm square mouths.
- Geometry: symmetric, square, zero-extension round OS-SE horns only.

| Ordered wave | Searches | Candidates |
| --- | ---: | ---: |
| core-axis | 25 | 171 |
| boundary-sentinel | 23 | 24 |
| axis-closure | 86 | 86 |
| face-sentinel | 16 | 60 |
| face-continuation | 148 | 148 |
| corner-sentinel | 10 | 29 |
| corner-continuation | 84 | 84 |
| locked-validation | 25 | 50 |

Core center/axis contrasts always run. Face and corner sentinels run before their
continuations, so a preregistered dead stratum can be stopped without suppressing
the measurements needed to identify it. Locked validation runs last and is never
used to select or prune candidates.

Axis-closure searches are materialized but run only when the corresponding inner
endpoint points outward by the registered score/diagnostic rule. N=2 is never a
regular grid point; it is only the lower safety-bound probe after N=4 improves
over N=8.

The runner requires the exact hash above through
`--reviewed-manifest-sha256`; changing and rematerializing the manifest invalidates
that approval. A failed search releases its slot and is recorded while unrelated
work continues. The study reports blocked rather than complete if any isolated
failure remains.
