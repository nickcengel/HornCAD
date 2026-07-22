# Launch review

No BEM work is started by the planner or materializer. This file describes the
exact materialized queue that must be reviewed before launch.

- Frozen manifest SHA-256: `f2f7c87cbdde9cb86b50828006b9dfc6c7cc287da96791a8dd39dd82ee2cab43`
- New BEM candidates before evidence-based pruning: 570
- Search directories: 336
- Parallelism: two independent searches, ten solver workers each.
- Domain: 30-50 degree coverage half-angle and 250-450 mm square mouths.
- Geometry: symmetric, square, zero-extension round OS-SE horns only.

| Ordered wave | Searches | Candidates |
| --- | ---: | ---: |
| core-axis | 25 | 171 |
| boundary-sentinel | 23 | 24 |
| face-sentinel | 15 | 60 |
| face-continuation | 155 | 155 |
| corner-sentinel | 13 | 30 |
| corner-continuation | 80 | 80 |
| locked-validation | 25 | 50 |

Core center/axis contrasts always run. Face and corner sentinels run before their
continuations, so a preregistered dead stratum can be stopped without suppressing
the measurements needed to identify it. Locked validation runs last and is never
used to select or prune candidates.

The runner requires the exact hash above through
`--reviewed-manifest-sha256`; changing and rematerializing the manifest invalidates
that approval. A failed search releases its slot and is recorded while unrelated
work continues. The study reports blocked rather than complete if any isolated
failure remains.
