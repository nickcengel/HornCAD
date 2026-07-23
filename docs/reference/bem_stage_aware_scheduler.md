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
