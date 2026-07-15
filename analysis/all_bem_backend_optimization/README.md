# All-BEM optimization evidence

This package records backend and mesh scaling work. It is not a frequency
response sweep and contains no design-result claims.

## Validated backend comparison

Identical 466-DOF, 100 Hz HornCAD mesh and throat loading:

| Backend | Wall time | Iterations | Maximum cut error |
|---|---:|---:|---:|
| Corrected Bempp dense LU | 59.07 s | direct | reference |
| Optimized NGSolve FMM | 5.46 s | 33 | 0.267% complex / 0.0176 dB |

The independent pulsating-sphere test remains within 0.6% complex trace error
on a coarse 162--230 DOF sphere. The dense Bempp Calderon-sign correction is
included in the comparison.

## Production mesh scaling

Netgen remeshes a stable 12-by-12 authored geometry seed. Every reported mesh
is watertight and passes the hard maximum-edge audit.

| Maximum frequency | EPW | DOFs | Triangles | Maximum edge | Maximum aspect |
|---:|---:|---:|---:|---:|---:|
| 2 kHz | 6 | 3,350 | 6,696 | 22.38 mm | 6.15 |
| 5 kHz | 6 | 13,828 | 27,652 | 9.21 mm | 5.63 |
| 10 kHz | 6 | 53,465 | 106,926 | 4.68 mm | 3.30 |

`acoustic-boundary-5khz-6epw.stl` and `mesh-5khz-6epw.npz` are the exact
5 kHz scaling mesh. The NPZ includes the rigid/throat face labels.

## Real 5 kHz solve benchmark

- 13,828 surface DOFs
- 134 GMRES iterations
- 292.8 seconds wall time
- 4.97e-5 measured preconditioned relative residual
- approximately 1.97 GB peak resident memory

That benchmark requested `1e-3`, but the then-current internal safety factor
solved twenty times more tightly. The factor was subsequently relaxed. The run
did not evaluate or preserve response fields and must not be used as horn data.

## Native thread scaling

One 5 kHz combined-operator plus preconditioner application:

| Threads | Time |
|---:|---:|
| 1 | 19.98 s |
| 2 | 10.43 s |
| 4 | 5.45 s |
| 8 | 2.90 s |
| 20 | 1.73 s |

The scheduler now sets native NGSolve threads per worker and budgets 150 kB
per surface DOF. A sweep can therefore trade threads per frequency against
frequency-level concurrency without oversubscribing the machine.

## Remaining acceptance work before design conclusions

- run 6/8/10-EPW convergence at a small set of frequencies;
- verify throat shape/area convergence, since the 5 kHz source cap has only 28
  triangles even though unit volume velocity is exactly normalized;
- validate simplified exterior geometry against a fuller exterior reference;
- use a small pilot sweep to confirm frequency-parallel wall time and memory.
