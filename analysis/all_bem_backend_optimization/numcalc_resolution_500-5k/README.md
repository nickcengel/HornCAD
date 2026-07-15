# NumCalc 500 Hz--5 kHz resolution and scheduling study

Date: 2026-07-15. Test object: Test4. Solver: native Apple-arm64 NumCalc built
from Mesh2HRTF commit `e45d0436a6fbeca3db13828cbae23ca109225be3`.

## Accepted resolution rule

Use one positive-X/positive-Y quadrant mesh sized at the maximum frequency of
the complete sweep, with HornCAD `MeshSettings(max_frequency, 6 EPW)` and the
existing Netgen `maxh_factor=0.5`. Reuse that exact mesh at every frequency.

For the 500 Hz--5 kHz Test4 sweep this produces 7,897 constant triangular
panels. The nominal setting is already conservative because Netgen applies the
existing `maxh_factor=0.5` sizing factor in addition to the EPW target.

The acceptance criteria against the 10-EPW mesh are:

- no more than 1.5% change in on-axis complex-pressure magnitude;
- no more than 0.25 dB change wherever the 10-EPW result is above -30 dB; and
- no unexplained beam or null displacement in the complex cuts.

## 5 kHz convergence

All runs used ML-FMM. The original 6-EPW case used five angles per cut; it was
re-exported and rerun with the same 19-angle grid as the 8-EPW case before the
production rule was selected.

| Nominal tier | Quadrant panels | Estimated RAM | Iterations | Residual | Solver wall time |
|---:|---:|---:|---:|---:|---:|
| 6 EPW | 7,897 | 0.391 GiB | 62 | 2.84e-10 | 10.75 s |
| 8 EPW | 13,734 | 0.640 GiB | 74 | 1.61e-10 | 22 s |
| 10 EPW | 21,737 | 1.083 GiB | 75 | 6.15e-10 | 39 s |

The matched-grid 6→8 EPW on-axis ratio is
`1.00141 - 0.01377j`, a 0.15% amplitude change. Above the -30 dB acceptance
floor, maximum normalized-magnitude changes are 0.133 dB horizontal, 0.183 dB
diagonal, and 0.213 dB vertical. Maximum normalized complex-pressure
differences are 0.00627, 0.00217, and 0.00273 respectively. The 6-EPW mesh
therefore passes the stated production criteria.

The additional 8→10 EPW comparison remains a useful convergence cross-check.
Its on-axis ratio is `0.99014 + 0.00206j`, a 1.0% amplitude change.
Maximum normalized complex differences are 0.00485 horizontal, 0.00291
diagonal, and 0.00201 vertical. Magnitude differences are 0.137 dB horizontal
and 0.131 dB vertical. The diagonal difference is 0.038 dB above -20 dB and
0.220 dB above -30 dB. Its 0.56 dB maximum occurs below -35 dB near the rear
of the cut and is outside the accepted optimization floor.

Neither an 8-EPW production default nor a 12-EPW run was therefore justified.

## Low-frequency geometry/loading check

At 500 Hz on the shared 5 kHz mesh, moving from nominal 6 to 8 EPW changes
on-axis pressure by 0.68%. At the common 0°, 45°, and 90° samples, normalized
magnitude changes are at most 0.0161 dB and normalized complex differences are
at most 0.00081. The maximum-frequency 6-EPW mesh therefore also passes the
low-frequency geometry/loading check.

NumCalc explicitly converts solved velocity potential to pressure with
`p = i rho omega phi`. The remaining absolute-pressure disagreement with the
earlier NGSolve backend is not a unit-label issue and remains unresolved.
Consequently, NumCalc self-convergence and normalized directivity are accepted;
cross-backend absolute SPL is not yet an acceptance metric.

## Sweep scheduler

`app/run_numcalc_sweep.py` now provides the production execution path:

- defaults to 500--5,000 Hz, 10 points/octave, and 6 EPW;
- produces 35 logarithmic frequencies including both endpoints;
- builds and caches one shared quadrant mesh;
- gives each frequency an independent NumCalc process and evaluation grid;
- schedules highest frequency first;
- uses NumCalc's own per-frequency RAM estimates with 15% headroom;
- caps concurrency by CPU count, requested workers, and RAM;
- rejects non-converged CGS output even when NumCalc exits with status zero;
- records wall time, residual, iterations, and process peak RSS;
- resumes atomically completed frequencies without remeshing or re-estimating;
- uses supervisor threads around native subprocesses, avoiding macOS POSIX
  semaphore restrictions; and
- stores the boundary mesh once, with relative links from frequency cases.

The final solve-free Test4 production plan contains 35 frequencies and selects
20 single-thread NumCalc processes on the 20-core machine. The worst NumCalc
estimate plus headroom is 0.450 GiB/process, so 20 concurrent cases reserve
about 9.0 GiB under the configured 48 GiB limit. Planning the full run took
12.6 s and occupied 3.0 MB with the shared mesh.

A ten-frequency/ten-worker smoke run completed all ten ~3.1 s solver jobs in
one concurrent wave. Total elapsed time including mesh construction, export,
and estimates was 9.09 s. A cached no-op resume of the three-frequency smoke
completed in 0.0028 s.

## Review artifacts

- `test4_5khz_6epw/` contains the accepted mesh, NumCalc input, boundary fields,
  and 57 far-field pressures.
- `test4_5khz_8epw/` contains the first convergence-check mesh and results.
- `test4_5khz_10epw/` contains the verification mesh and corresponding fields.
- `production-dry-run-manifest.json` records all 35 frequencies, RAM estimates,
  and the selected 20-worker plan without claiming that the sweep was run.

## Remaining gate before trusting absolute SPL

Do not infer calibrated SPL or radiation impedance by comparing NumCalc and
NGSolve until their source and pressure normalization discrepancy is resolved.
The backend is ready for a normalized-directivity sweep and for NumCalc-internal
optimization comparisons.
