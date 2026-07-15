# Test4 NumCalc native-symmetry spike

All cases solve 500 Hz radiation from Test4 with a reconstructed total throat
volume velocity of 1 m3/s. NumCalc was built natively with Apple Clang from
Mesh2HRTF commit `e45d0436a6fbeca3db13828cbae23ca109225be3` (2026-03-20).

Each artifact directory contains the exact quadrant or full node/element mesh,
`NC.inp`, raw boundary/evaluation pressure and velocity, the HornCAD metadata,
and a machine-readable `run.json`.

## Symmetry correctness and dense performance

The exact mirrored-full control is constructed by reflecting the same 737
quadrant panels used by the symmetry case. It therefore isolates NumCalc's
reflection implementation from remeshing differences.

| Case | Equations | Matrix entries | Iterations | Residual | Wall time |
|---|---:|---:|---:|---:|---:|
| Native two-plane symmetry, dense | 737 | 543,169 | 73 | 2.33e-10 | 3.40 s |
| Exact mirrored full mesh, dense direct | 2,948 | 8,690,704 | direct | n/a | 18.91 s |

The 15 requested far-field pressures are identical between these cases to
NumCalc's written precision. Native symmetry reduces the dense system to one
quarter of the equations, one sixteenth of the matrix entries, and 17.98% of
the wall time: a measured 5.56x speedup.

The exact mirrored full system's CGS solve was unstable, so its accepted control
uses NumCalc's direct solver. The diagnostic is not retained as an accepted
result. A separately remeshed full body converged iteratively in 11.05 s, but
is not the correct control for symmetry because its panels differ.

## FMM and mesh convergence

| Mesh tier used for the 500 Hz solve | Quadrant panels | Method | Iterations | Residual | Wall time |
|---|---:|---|---:|---:|---:|
| 500 Hz / 6 EPW | 737 | dense | 73 | 2.33e-10 | 3.40 s |
| 500 Hz / 6 EPW | 737 | FMM | 70 | 6.62e-10 | 2.48 s |
| 2 kHz / 6 EPW | 1,656 | FMM | 81 | 7.72e-10 | 4.06 s |
| 5 kHz / 6 EPW | 7,897 | FMM | 102 | 3.46e-10 | 27.32 s |

At 737 panels, FMM differs from dense by 0.0577% in the complex far-field
vector and by at most 0.0037 dB after on-axis normalization. The FMM
implementation is therefore accepted against dense for this case.

The 737-panel result is not mesh-converged. Moving from 737 to 1,656 panels
changes absolute pressure about 19% and normalized cuts by up to 0.30 dB.
Moving from 1,656 to 7,897 panels changes absolute pressure by about 6.6%, but
normalized directivity by at most 0.078 dB. NumCalc's constant-element
collocation therefore needs materially finer meshes than the first smoke test
suggested.

Against the earlier NGSolve full-geometry 500 Hz reference, the 7,897-panel
NumCalc result differs by at most 0.345 dB horizontally, 0.166 dB diagonally,
and 0.065 dB vertically. This cross-discretization comparison is encouraging
but is not yet a convergence proof; the NGSolve reference itself used the
coarse 500 Hz mesh.

## Conclusion

NumCalc passes the option-2 feasibility gate:

- it compiles and runs natively on Apple Silicon;
- it consumes only the quadrant mesh;
- its two-plane reflection result exactly matches its mirrored-full control;
- symmetry produces a measured wall-time reduction; and
- its FMM result matches dense BEM at fixed mesh.

It should replace the NGSolve hybrid path as the leading symmetry-backend
candidate. Before a 500 Hz--5 kHz production sweep, the next work is to choose
a NumCalc-specific mesh rule through a small convergence study and compare one
accepted higher-frequency point against a sufficiently refined independent
reference.
