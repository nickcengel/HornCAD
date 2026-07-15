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

## Required implementation

Port the pressure domain to MFEM's distributed interfaces:

1. Build a `ParMesh` and `ParFiniteElementSpace` for pressure.
2. Partition aperture velocity unknowns consistently across MPI ranks.
3. All-gather the aperture vector for the dense nonlocal radiation product.
4. Apply pressure-to-mouth coupling using owned true DOFs and global aperture
   indices.
5. Run flexible GMRES collectively with an MPI AMG or domain-decomposition
   pressure preconditioner.
6. Validate against existing full/quadrant 5 kHz UMFPACK results before
   resuming test4.
7. Benchmark rank count and per-rank threading on the M1 Ultra, then run the
   53-point 500 Hz–10 kHz sweep.

The 5 kHz published test4 review remains authoritative until this validation
passes.
