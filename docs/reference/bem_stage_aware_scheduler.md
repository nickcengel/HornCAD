# Stage-aware BEM scheduler

The stage-aware scheduler keeps native solver cores occupied while other
candidates are meshing, generating reports, or calculating diagnostics. It is
intended for future multi-candidate studies; it does not alter already-running
legacy queues.

`app.tools.run_stage_aware_bem_queue` may supervise more search processes than
would be safe with the old whole-search slot accounting. Each native NumCalc
process runs through `app.tools.numcalc_slot_wrapper`, which acquires one
cross-process file-lock slot. Operating-system locks are released automatically
if a worker exits unexpectedly.

For the normal two-by-ten-core workload, use four orchestration workers and a
global capacity of twenty NumCalc processes:

```shell
.venv/bin/python -m app.tools.run_stage_aware_bem_queue \
  --runtime-state examples/my-study/stage_aware_runtime.json \
  --queue-workers 4 \
  --numcalc-processes 20 \
  examples/my-study/searches/*/search.yaml
```

The additional orchestration workers do not authorize additional simulations.
Each search retains its own authored evaluation budget and resumable ledger.
The global semaphore limits actual NumCalc processes, while RAM estimation,
mesh preparation, diagnostics, and report generation may overlap.

The scheduler validates that each search has an explicit solver-worker count
and that no individual search requests more processes than the global
capacity. Its runtime ledger records each completed search and the tail of its
captured output for failure diagnosis.

Before launching a retained search, the queue inspects its search ledger. A
failed retained candidate is automatically relaunched with the explicit
`--retry-failed` path without creating another proposal. NumCalc
non-convergence escalates automatically from the retained iteration count to
500, 1000, and at most 2000 iterations within the same queue event. A zero
process exit is accepted only when the search ledger itself says `complete`;
`stopped`, `failed`, or missing state is recorded as a queue failure. Each
attempt and iteration ceiling is retained in the runtime ledger. This prevents
a fixed one-candidate search from being counted as successful merely because
its report was written after solver non-convergence.

Study-specific runners should expose a `resume` command that selects only
non-complete search ledgers and calls the same queue. Repeating that command is
idempotent: completed responses are not recomputed, interrupted candidate
ledgers are requeued, and report/index refresh runs after every completed queue
event.

## Required use in future studies

All BEM studies prepared after the round-control ridge-closure study must use
the stage-aware queue and shared NumCalc semaphore. A study-specific runner must
not fall back to whole-search slot accounting.

The queue overlaps separate search processes; it does not make candidates
inside one search concurrent. A future study must therefore expose enough
independent search work to occupy global capacity through the tail. Prefer one
candidate per search for fixed registered designs. If candidates must share a
search, the launch audit must demonstrate that at least two independent search
streams remain until the final two candidates. A design that would leave the
last search processing candidates sequentially fails scheduler preflight.

The study runtime ledger must record the scheduler type, queue-worker count,
global NumCalc capacity, and search-sharding policy. These are execution
requirements only; they do not authorize extra candidates.
