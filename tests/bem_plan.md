# Expand HornCAD’s BEM Process into a Validated Comparison Pipeline

## Restart Here: Corrected Primary Model (2026-07-14)

The primary analysis target is **not** the full printable-body exterior BEM
prototype. That prototype was useful for exercising geometry, source
normalization, resumable artifacts, and output generation, but it does not
match the requested AKABAK-style comparison problem.

Resume work through these two coupled workstreams:

1. Select and benchmark an Apple Silicon solver stack that runs natively on
   ARM64, scales across the M1 Ultra's 20 CPU cores, stays within a configurable
   portion of its 64 GiB memory, and supports a nonlocal Helmholtz radiation
   operator on the mouth aperture. Bempp-cl may remain a dense numerical
   reference, but its Apple OpenCL route is incompatible and its ExaFMM-t
   backend failed the local complex-operator validation on ARM64.
2. Replace the full printable-body problem with the reduced acoustic model:
   the internal horn surface, a prescribed-volume-velocity throat piston, and a
   computational mouth closure. The mouth closure is a coupling interface, not
   a rigid cap. It must apply a spatially coupled exterior radiation-impedance
   or boundary-integral operator and retain nonuniform complex pressure and
   normal velocity.

The workstreams are coupled: evaluate solver tools against this exact reduced
problem, not against an unrelated generic Helmholtz benchmark.

### Required boundary model

- Horn wall: rigid, `v_n = 0`.
- Throat piston: uniform prescribed normal velocity, normalized by default to
  integrated volume velocity `Q = 1 m3/s`.
- Mouth aperture: a meshed computational closure with a nonlocal exterior
  half-space radiation operator relating the complete pressure and velocity
  distributions across the aperture.
- Printable thickness, rear body, and exterior enclosure: excluded from the
  primary model. Keep the full-body exterior solve only as an optional later
  diffraction/scattering comparison.
- Primary frequency range: 500 Hz through 5 kHz. A lower-frequency run is only
  a software smoke test and is not acoustically relevant acceptance evidence.

### Acceptance evidence

- Native ARM64 dependency and version manifest.
- Measured runtime, peak memory, and scaling at useful core counts up to 20.
- One shared mesh sized for 5 kHz, with wavelength and quality checks.
- Complex throat impedance and complex mouth pressure/normal velocity.
- Radiated power plus horizontal, diagonal, and vertical directivity.
- Resumable per-frequency artifacts over 500 Hz--5 kHz.
- Mesh-convergence comparisons at 6/8/10 elements per wavelength before
  production acceptance.
- Comparison with an equivalently configured AKABAK model using the same
  internal surface, throat source, mouth aperture/baffle assumption, medium,
  frequencies, and observation definitions.

### Current recovery state

- Branch checkpoint before this correction: `9219110`.
- The current dense combined-field full-body solver is too expensive at useful
  resolution; do not extend it as the primary model.
- The `single-layer-preview` option is resonance-sensitive and exists only for
  pipeline experiments.
- A locally patched ExaFMM-t 0.1.1 build ran on ARM64 but produced about 1.56
  relative error against Bempp's dense complex Helmholtz operator. It was
  uninstalled and must not be used for results.
- The last full-body smoke artifact is under `/private/tmp` and is disposable;
  it is not validation of the corrected model.

### Immediate next actions

1. Shortlist native ARM64 FEM/BEM/FMM stacks against the required mouth
   operator and create a small reproducible operator benchmark.
2. Add a geometry API that emits three labeled pieces in metres: internal rigid
   wall, throat disk, and mouth aperture, with shared conforming edge loops.
3. Validate orientation, areas, watertight computational closure, and unit
   volume velocity without invoking a solver.
4. Implement the best-supported nonlocal aperture coupling and run a
   deliberately small but relevant 500 Hz--5 kHz proof sweep.
5. Record performance and numerical comparisons before choosing the production
   backend.

### Progress log: 2026-07-14

- Checkpoint `fbe21b4` adds `app/acoustic_domain.py`. It emits a closed,
  conforming surface with separately labeled rigid wall, throat piston, and
  mouth aperture. On the test project at 32/32 seed resolution it has 9,216
  triangles, a 0.000506353 m2 throat, a 0.108743 m2 mouth, and one positive
  watertight air volume. Tests verify labels, cap areas, normal orientation,
  shared loops, and the throat normal-velocity sign.
- Native solver shortlist result: use MFEM for the first parallel interior FEM
  prototype. Homebrew MFEM 4.9 installs as an ARM64 shared library with
  OpenMPI, Hypre, Metis, OpenBLAS, and SuiteSparse. A compiled complex-operator
  probe ran successfully at 1 and 4 MPI ranks. The bottle has MPI enabled but
  not OpenMP, so allocate cores with MPI processes.
- Keep DOLFINx/PETSc as the second candidate. Its official complex Helmholtz
  example and facet-submesh support fit the formulation, but neither DOLFINx
  nor PETSc was installed locally and bringing up that stack is more involved.
- MFEM does not supply the desired acoustic aperture operator. HornCAD must
  assemble the nonlocal complex mouth block and couple it to the boundary
  trace DOFs. The operator requires its own analytic validation before a horn
  result is accepted.
- Next implementation step: generate a tetrahedral air-volume mesh that
  preserves the three boundary attributes, load it into parallel MFEM, assemble
  the complex interior Helmholtz system, and add the aperture block.
- Checkpoint `fabeda6` adds tetrahedralization through Gmsh with physical
  attributes 1=wall, 2=throat, 3=mouth, and 4=air. Nine tests pass. A native
  MFEM probe loaded and partitioned the generated mesh over four MPI ranks while
  retaining all attributes.
- Do not trust Gmsh's requested `MeshSizeMax` alone. A 30 mm request applied to
  a coarse closure produced a measured 65.1 mm maximum tetrahedron edge because
  the input surface constrained the volume mesh. Production meshing must first
  seed/refine the closed surface below `c/(elements_per_wavelength*f_max)`, then
  reject the tetrahedral result if any measured edge exceeds the same limit.
- Checkpoint `9286d7e` adds the nonlocal Rayleigh aperture impedance operator.
  At `ka ~= 0.5`, a 486-panel circular-piston test matches the analytic
  specific radiation impedance within 0.23%. Complex pressure/velocity
  round-trip and conditioning checks also pass.
- Checkpoint `b50958f` adds a serial sparse reference coupling using
  scikit-fem/SciPy. It assembles `K - k^2 M + i*omega*rho*W*inv(Z)` on the mouth
  trace and the prescribed throat Neumann load. A 500 Hz reduced-horn solve has
  3,974 pressure DOFs, 963 mouth nodes, positive radiated power, and a
  `6.2e-14` relative residual; meshing plus solve takes about 2.3 seconds.
- The reference mesh uses a hard measured 31 mm edge contract and is not a
  5 kHz production mesh. Its remeshed throat area differs from the authored
  polygon by 12.9%; unit volume velocity is correctly normalized on the final
  mesh, but production requires throat-area convergence as well as edge
  convergence.
- The Python reference explicitly validates signs and coupling algebra. The
  next step is to implement the same aperture action as an MFEM operator and
  distribute its mouth trace over MPI ranks; do not attempt a nominal 5 kHz
  production sweep by forming and inverting an unnecessarily dense global
  matrix in the serial reference.
- The mixed unknown form `[p, v_mouth]` is now verified against the condensed
  `Z^-1` reference to tight numerical tolerances. It removes an explicit
  aperture inverse and is the form to carry into the production operator.
- Native MFEM source and CMake configuration live in `app/mfem/`. At 500 Hz its
  complex UMFPACK solve matches the Python reference: 40,137.5 W radiated
  power, 0.000440309 m2 throat, 0.105677 m2 mouth, and `6.13e-13` residual.
  This is a strong independent assembly/sign cross-check.
- Checkpoint after `d75d1f0` replaces the 18-minute globally coupled direct
  factorization with a matrix-free mixed MFEM operator and restarted GMRES.
  It applies sparse `K-k^2M`, dense nonlocal `Z`, and trace gather/scatter
  separately. A block preconditioner factors only the sparse pressure block
  and the complex aperture block; it never assembles or factors the coupled
  system.
- At 500 Hz the iterative solve reproduces 40,137.5 W and finishes in 0.89 s
  (134 iterations, `5.9e-9` true residual) on the M1 Ultra. On the same coarse
  validation mesh, 4 kHz and 5 kHz now converge in 4.2 s and 6.1 s. Their
  response values are not physically accepted: the measured 28.5 mm maximum
  edge is much too coarse at 5 kHz (68.6 mm wavelength).
- The next task is a wavelength-controlled production mesh (start with at
  least 6 elements/wavelength, 11.4 mm at 5 kHz), followed by mesh convergence.
  Then distribute the pressure space and aperture trace with `ParMesh`/
  `ParFiniteElementSpace`. Until that port is complete, exploit the 20 cores
  by running independent frequencies as bounded processes; each native solve
  is currently serial, aside from optimized library kernels.
- The mouth and throat closures now contain graded interior rings while
  retaining the exact shared perimeter and the original piecewise nonplanar
  mouth surface. This removes long boundary-only Delaunay chords. The
  tetrahedral maximum-edge audit was also vectorized in 250k-element chunks:
  auditing a 1.11-million-tetrahedron trial mesh takes about 3 seconds instead
  of several minutes and uses bounded temporary memory.
- The current STL `classifySurfaces` handoff remains the 5 kHz meshing blocker.
  It remeshes a 9.57 mm source-wall maximum edge into a 14.58 mm wall edge, so
  the 11.44 mm (6 elements/wavelength) contract correctly rejects the mesh.
  More source samples and Netgen/HXT optimization did not cure it. A direct
  labeled discrete-surface experiment did not produce a Gmsh volume and was
  rolled back. Next investigate a conforming Gmsh OCC/geo surface construction
  or a different tetrahedralizer that preserves labeled input facets; do not
  weaken the measured-edge acceptance criterion to make this trial pass.
- `wildmeshing==0.4.0` is installed in `.venv` from its native CPython 3.13
  macOS ARM64 wheel. A first TetWild proof used `max_threads=20`, processed the
  coarse closed acoustic surface in 5.1 s wall time (18.0 s aggregate CPU), and
  returned 976 vertices / 2,889 tetrahedra. This confirms native multicore M1
  Ultra execution. Next add boundary extraction/label transfer and verify
  geometric deviation, maximum edge, positive volumes, and MFEM import before
  making it an optional production backend. TetWild may alter the input
  surface, so label and aperture-area tolerances are mandatory.
- Checkpoint after `d6c5e67` integrates TetWild as an optional backend with
  nearest-triangle wall/throat/mouth label transfer, 5% throat and 2% mouth
  area gates, outward boundary extraction, degenerate-tetrahedron rejection,
  hard maximum-edge audit, Gmsh 2.2 output, and an automated regression test.
- The accepted 5 kHz / 6-elements-per-wavelength proof used 20 threads and
  `edge_length_r=0.011`: 53,848 nodes, 282,443 tetrahedra, 10.387 mm maximum
  edge against an 11.440 mm limit, and 0.249 mm maximum surface deviation.
  Meshing took 199.8 s wall / 640.8 s aggregate CPU. MFEM imported the mesh;
  at 500 Hz it had 53,848 pressure and 4,006 mouth DOFs, converged in 76 GMRES
  iterations (23.75 s solver, 56.9 s total), and produced 41,170 W for the
  deliberately calibrated 1 m3/s source. Throat area was 0.000500634 m2 and
  mouth area 0.105261 m2.

Primary references used for the solver decision:

- MFEM build/platform support: https://mfem.org/building/
- MFEM parallel complex example 35p: https://docs.mfem.org/4.8/ex35p_8cpp_source.html
- DOLFINx complex Helmholtz example:
  https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_helmholtz.html
- PETSc complex and macOS configuration: https://petsc.org/main/install/install/

  ## Summary

  Turn the current 3D BEM prototype into a reproducible acoustic-analysis pipeline suitable for geometry comparisons and
  eventual optimization. The workflow will use a uniform piston throat source, wavelength-controlled meshing, complex mouth-
  field observations, ideal-aperture and full-exterior radiation modes, convergence checks, resumable sweeps, and machine-
  readable metrics.

  The geometry origin remains the throat center. Radiation observations use the mouth center as their reference origin. Driver
  lumped-element modeling is explicitly out of scope.

  ## Key Changes

  ### 1. Formalize the acoustic model

  - Represent the throat source as an explicit circular cap moving uniformly in (+z).
  - Author the excitation as piston velocity or volume velocity and convert it to the complex Neumann boundary condition;
    default to unit volume velocity for calibrated complex results.

  - Keep all other physical surfaces rigid.
  - Record source area, normal direction, velocity, volume velocity, medium properties, coordinate origins, and boundary
    assignments in the run manifest.

  - Replace the resonance-sensitive single-layer formulation with a resonance-safe combined-field exterior Neumann formulation,
    validated against analytic cases.

  - Keep the exterior geometry physically meaningful and separate it from artificial observer surfaces.

  ### 2. Introduce frequency-aware acoustic meshing

  - Replace side_samples and stations as the primary public controls with:
      - maximum_frequency_hz
      - elements_per_wavelength
      - optional geometry-curvature tolerance

  - Default production resolution to 8 elements per wavelength:
    [
    h_\text{target}=c/(8f_\text{max})
    ]

  - Provide named tiers:
      - Preview: 6 elements/wavelength
      - Production: 8 elements/wavelength
      - Verification: 10 and 12 elements/wavelength

  - Refine by actual triangle edge length, not ring counts alone, with additional refinement at the throat, mouth rim, corners,
    rapid curvature, and morph transitions.

  - Eliminate boolean-generated sliver triangles and enforce limits for maximum edge, aspect ratio, minimum angle, orientation,
    watertightness, and connectedness.

  - Fail before solving if any acoustically relevant edge exceeds the selected wavelength limit; do not accept percentile-only
    compliance.

  - Emit a mesh report containing triangle/DOF counts, edge statistics, quality failures, minimum wavelength, supported maximum
    frequency, and estimated solve cost.

  - Use one mesh sized for the sweep’s highest frequency so comparisons across frequency share the same discrete geometry.

  ### 3. Add mouth-field observers

  - Define the mouth-center radiation origin at the center of the authored mouth:
    [
    O_\text{radiation}=(0,0,z_\text{mouth})
    ]

  - Add a conformal aperture observer just outside the actual curved mouth surface; default offset is 1 mm along the exterior
    normal.

  - Preserve, at every sample and frequency:
      - complex pressure (p)
      - complex outward normal velocity (v_n)
      - magnitude and phase
      - local position, normal, and area weight

  - Also generate a planar mouth-view projection for intuitive (x/y) heatmaps without treating that visualization plane as a
    physical boundary.

  - Produce pressure magnitude, phase, normal-velocity magnitude, phase, and local impedance plots.
  - Calculate aperture diagnostics including magnitude uniformity, phase spread, active area, modal asymmetry, and power flow.

  ### 4. Separate aperture behavior from exterior diffraction

  Provide two explicit radiation modes from the same run:

  - full_exterior_bem: includes the finite mouth edge, exterior horn body, scattering, and diffraction.
  - ideal_baffled_aperture: radiates the solved complex mouth pressure/velocity through an ideal infinite-baffle aperture
    calculation, intentionally excluding finite-edge and rear-body effects.

  For both modes:

  - Calculate horizontal, diagonal, and vertical far-field cuts.
  - Support optional full spherical directivity grids.
  - Normalize plots to on-axis per frequency while retaining unnormalized complex pressure.
  - Use the mouth center as the phase and radial reference.
  - Plot labeled −6 dB contours and calculate −6 dB beamwidth.
  - Compare the two modes in complex pressure before conversion to dB, producing an edge/exterior-diffraction difference
    result.

  ### 5. Make sweeps reliable and optimizer-ready

  - Split the process into reusable stages: geometry → mesh → solve → observers → radiation → metrics → plots.
  - Store each completed frequency atomically so long sweeps can resume after interruption.
  - Parallelize independent frequency solves within configurable memory limits.
  - Cache deterministic geometry and mesh artifacts by content hash.
  - Write a run manifest containing normalized HornCAD configuration, source definition, solver/library versions, mesh report,
    tolerances, frequency grid, observer definitions, coordinate references, convergence status, runtime, and artifact hashes.

  - Store complex multidimensional fields in NPZ/HDF5; reserve CSV for compact far-field cuts and summary metrics.
  - Expose a callable Python API returning structured results rather than requiring plots or parsing console output.
  - Generate optimizer-facing metrics such as beamwidth error, coverage consistency, directivity smoothness, off-axis variance,
    mouth phase spread, diffraction penalty, solver cost, and convergence confidence.

  - Reject candidates with invalid geometry, unsupported mesh resolution, solver non-convergence, or failed mesh-convergence
    criteria.

  ## Validation and Test Plan

  - Verify mesh sizing and rejection against known wavelength limits at several maximum frequencies.
  - Validate piston boundary area, orientation, uniform velocity, and integrated volume velocity.
  - Validate the BEM formulation against analytic pulsating-sphere and simple piston/baffle reference problems.
  - Confirm mouth pressure and normal velocity satisfy the boundary representation and yield consistent acoustic power.
  - Compare aperture integration against analytic rectangular and circular uniform-aperture directivity.
  - Run automated 6/8/10/12-elements-per-wavelength studies and compare complex pressure, −6 dB beamwidth, null locations, and
    mouth fields.

  - Establish production acceptance tolerances from the 8-versus-10/12 comparison; deep-null depth will not be an optimization
    metric unless converged.

  - Verify that translating the radiation reference changes phase consistently but not normalized far-field magnitude.
  - Verify ideal-aperture and full-exterior modes agree in controlled cases and diverge where finite-edge diffraction is
    expected.

  - Test interrupted-run recovery and deterministic reproduction from a saved manifest.
  - Cross-check representative HornCAD geometries against AKABAK using the same piston boundary, mesh target, reference point,
    frequencies, and observation cuts.

  ## Delivery Sequence

  1. Refactor the current solver into structured geometry, mesh, source, solve, observer, and result APIs.
  2. Implement acoustic mesh sizing, quality reports, and pre-solve rejection.
  3. Formalize the unit-volume-velocity piston and resonance-safe BEM formulation.
  4. Add resumable complex-frequency results and provenance manifests.
  5. Add conformal mouth pressure/velocity observations and planar plots.
  6. Add ideal baffled-aperture radiation and comparisons with full exterior BEM.
  7. Add convergence automation, analytic validation cases, and AKABAK cross-checks.
  8. Add stable acoustic metrics and connect them to the candidate-matrix runner.
  9. Permit automated optimization only after representative production meshes pass convergence criteria.

  ## Assumptions and Defaults

  - Frequency range is user-authored; the highest requested frequency controls the mesh.
  - Production mesh target is 8 elements per wavelength.
  - Verification uses 10 and 12 elements per wavelength.
  - Geometry origin is the throat center; radiation origin is the mouth center.
  - The source is a uniform axial piston with unit volume velocity, not a modeled compression driver.
  - Mouth results preserve complex pressure and normal velocity.
  - Both ideal-aperture and full-exterior radiation are first-class outputs.
  - Full exterior BEM includes edge diffraction; ideal-aperture mode intentionally excludes it.
  - Observer surfaces never alter the acoustic boundary or require enclosing boxes.
