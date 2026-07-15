# All-BEM backend smoke artifact

This package is an end-to-end plumbing and numerical-reference run, not a
production horn result. It uses the test-project geometry, a deliberately
coarse 466-DOF closed surface, a 100 Hz throat-driven source, five angles per
cut, and the native `ngsolve-fmm` backend.

Key results:

- GMRES iterations: 42
- preconditioned relative residual: 1.51e-10
- analytic pulsating-sphere trace error in the backend test: 0.35%
- corrected dense Bempp versus NGSolve normalized complex directivity error on
  this mesh: 0.055--0.057%
- maximum corrected dense-versus-FMM level difference: 0.0053 dB
- measured same-process solve/prediction time: 14.6 s NGSolve FMM versus
  59.2 s Bempp dense LU (including each backend's assembly/JIT work)

`acoustic-boundary.stl` is a directly viewable copy of the solved closed
surface. `mesh.npz` contains the exact vertices, faces, and throat labels. The frequency
NPZ retains unnormalized complex fields and directivity. The manifest records
the complete normalized configuration and hashes. PNG/CSV files are review
products made from those arrays.

The coarse geometry seed is intentionally below production resolution. Use it
only to inspect the data contract and reproduce backend validation; do not use
its 100 Hz response to make horn-design decisions.
