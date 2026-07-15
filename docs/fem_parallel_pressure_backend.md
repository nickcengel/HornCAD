# Parallel FEM pressure backend

## Objective

Replace the serial UMFPACK pressure-block preconditioner so the reduced
interior/aperture FEM can solve an 8-elements-per-wavelength mesh through
10 kHz on the 20-core, 64 GB Apple Silicon host.

## Reproducible blocker

The test4 10 kHz quadrant mesh is retained locally as
`analysis/test4/interior_quadrant_10khz_8ppw.msh`; its compact report is
`analysis/test4/mesh_report_10khz_8ppw.json`. It contains 468,962 pressure
nodes and 2,643,047 tetrahedra. A single 10 kHz solve fails before GMRES when
UMFPACK factors the pressure block:

```text
UMFPackSolver::SetOperator : umfpack_di_numeric() failed
UMFPACK: ERROR: out of memory
```

The failure is fill growth in the serial direct factorization, not volume-mesh
generation or total system memory during meshing.

A subsequent 10 kHz / 6-EPW feasibility test also failed in the same UMFPACK
numeric factorization before GMRES. Its quadrant mesh contained 170,413
pressure nodes and 938,520 tetrahedra, with a 5.020 mm measured maximum edge
against the 5.720 mm limit. Meshing completed in 275.04 seconds using 20 TetWild
threads; UMFPACK reported out of memory after 16.78 seconds. The full local mesh
and logs are retained under `analysis/test4/10khz_6epw/` and ignored by Git.
Reducing the 10 kHz mesh from 8 to 6 EPW is therefore insufficient to make the
current serial direct pressure preconditioner viable.

## Rejected substitutions

Each candidate was required to converge on the accepted test4 5 kHz mesh and
reproduce its physical residual and acoustic outputs.

- MFEM ILU(0), physical pressure block: 1,000 outer iterations, no convergence,
  relative residual approximately 0.188.
- MFEM ILU(0), positive shifted Laplacian: 1,000 iterations, no convergence,
  relative residual approximately 0.182.
- Symmetric Gauss-Seidel, positive shifted Laplacian: 1,000 iterations, no
  convergence, relative residual approximately 0.183.
- PETSc ILU(2): 1,000 iterations, no convergence, relative residual
  approximately 0.302.
- Nested PETSc GMRES/ILU and additive Schwarz: stable setup but impractically
  slow on the 5 kHz validation problem.
- PETSc nested-dissection LU: avoided the immediate UMFPACK allocation failure
  at 10 kHz but remained in one factorization for several minutes, making a
  53-frequency sweep impractical.
- The installed MFEM/Hypre solver failed during setup through both a serial
  matrix adapter and a one-rank native parallel matrix. No Hypre path was
  accepted.

Rejected experimental code was removed; the production executable remains on
the last validated UMFPACK implementation.

## Implemented backend

Branch `parallel-fem-backend` implements the distributed solver in
`app/mfem/parallel_interior_acoustics.cpp`:

- MFEM `ParMesh`, `ParFiniteElementSpace`, and distributed Hypre pressure matrix;
- MPI-distributed matrix-free mixed operator and flexible GMRES;
- replicated aperture trace and dense radiation operator;
- SuperLU_DIST pressure-block factorization using 64-bit global indices;
- simultaneous real/imaginary pressure solves with one reused factorization.

The new backend reproduces the accepted serial acoustic results:

| Case | Serial solve | Distributed solve | Result |
|---|---:|---:|---|
| 6-EPW convergence mesh, 500 Hz | 1.76 s | 1.18 s (2 ranks) | impedance/power agree to at least 7 significant digits |
| 6-EPW convergence mesh, 5 kHz | 3.97 s | 2.26 s (2 ranks) | impedance/power agree to at least 7 significant digits |
| test4 8-EPW mesh, 5 kHz | 28.63 s | 11.87 s (4 ranks) | impedance/power agree to at least 7 significant digits |
| test4 6-EPW mesh, 10 kHz | UMFPACK out of memory | 89.40 s (4 ranks) | converged in 145 iterations |

The 10 kHz result removes the serial memory blocker at 6 EPW. It does not yet
establish mesh convergence at 10 kHz, and the retained 468,962-DOF 8-EPW mesh
still needs to be attempted. The published 5 kHz test4 review remains the
authoritative production result until the higher-frequency sweep and mesh
comparison are complete.

Four ranks are the current M1 Ultra default. On the test4 5 kHz mesh, eight
ranks took 22.40 seconds versus 11.87 seconds with four; communication and
factorization overhead outweighed the extra cores at this problem size.

## Remaining work

1. Package the 64-bit SuperLU_DIST/MFEM build so it is reproducible outside the
   current development build directory.
2. Measure peak memory at 10 kHz before running several MPI frequencies
   concurrently or attempting the larger mesh.
3. Attempt the retained 10 kHz 8-EPW mesh.
4. Run and review a 500 Hz–8 or 10 kHz sweep, then update the validated CLI limit.
