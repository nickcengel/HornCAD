# Expand HornCAD’s BEM Process into a Validated Comparison Pipeline

## Restart Here: Free-Air Curved-Mouth and Local-Lip Model (2026-07-15)

### Current production status

The accepted implementation is the native NumCalc all-BEM path invoked with
`python app/run_bem_suite.py config.YAML --output-dir analysis/run`. It solves
one positive-X/positive-Y quadrant with NumCalc's native reflection symmetry,
uses a shared maximum-frequency mesh at 6 EPW, schedules independent frequency
processes across available CPU and RAM, and resumes completed cases. Standard
outputs are coverage and throat-impedance magnitude only. The NGSolve and
one-way local-lip sections below are retained as historical validation and
rejected-path records; they are not the production workflow.

### Historical NGSolve all-BEM checkpoint (2026-07-15)

#### Required quadrant symmetry backend

Production all-BEM sweeps must exploit Test4's `x=0` and `y=0` reflection
symmetry. The intended boundary is the open positive-x/positive-y physical
quadrant; symmetry-plane caps are meshing scaffolds only and are removed before
operator assembly. The free-space kernel is the even-even sum of physical,
x-reflected, y-reflected, and xy-reflected sources, so the reconstructed problem
still radiates into 4π space.

An initial four-cross-mesh image prototype passed the analytic quarter-sphere
but exposed inaccurate hypersingular seam interactions on the longer HornCAD
cuts. The accepted implementation instead reflects and merges the clean
quadrant into a connected integration surface, adds periodic point
identifications for both reflection planes, and compresses the H1 space to its
positive-quadrant representatives. NGSolve therefore retains its native
singular quadrature at the seams while solving only the independent even-even
unknowns.

A coarse analytic quarter-sphere converges to an `8.4e-6` true residual with
1.37% trace error. Test4 temporary-cap meshing at 500 Hz produces 416 independent
vertices versus 1,298 full, maximum aspect 5.48, and no non-symmetry boundary
edges. Against the independently remeshed full solve, the periodic-compressed
solution used 416 versus 1,298 DOFs and 28 versus 36 iterations. Complex H/D/V
pressure differed by 0.92% raw and 0.22% after a best complex scale; maximum
normalized level difference was 0.029 dB and the best scale was within 0.9% of
unity. The full integration panel set is still present internally, so this
milestone reduces independent unknowns and iterations but does not yet claim a
fourfold FMM matvec reduction. `--full-geometry` remains the validation path.

Optimization checkpoint: the native backend now uses a component-wise
weakly-singular regularization of the hypersingular operator, a Laplace
single-layer Calderon preconditioner, and tuned FMM controls (minimum order 6,
order factor 0.8, separation 1.5). On the 466-DOF dense-reference horn case it
completed in 5.46 s versus 59.07 s for corrected Bempp dense LU. Normalized
complex directivity differed by 0.245--0.267%, with a 0.0176 dB maximum level
difference. The former native path took 14.6 s on this case.

Netgen surface remeshing replaces global subdivision by default. At 6 EPW it
produced accepted watertight meshes of 3,350 DOFs at 2 kHz, 13,828 at 5 kHz,
and 53,465 at 10 kHz, with maximum aspect ratios 6.15, 5.63, and 3.30. A real
5 kHz / 13,828-DOF solve completed in 293 s and 134 iterations, using about
1.97 GB peak RSS; its measured preconditioned residual was 4.97e-5. This run
used an overly conservative internal tolerance factor that has since been
relaxed and was a scaling benchmark, not response data.

Thread profiling at 5 kHz measured one operator-plus-preconditioner application
at 19.98/10.43/5.45/2.90/1.73 s for 1/2/4/8/20 threads. Whole-solve profiling
then exposed two regimes: standalone RHS/preconditioner applications are
effectively serial per frequency in this NGSolve FMM path, while GMRES reached
about 18.7 cores when assigned 20 threads. The 38,890-DOF Test4 mesh reached
2.43 GiB peak RSS before its diagnostic run was deliberately stopped.

The default 20-core policy is therefore ten frequency processes with two
native threads each: about ten utilized cores during serial-per-process work
and all twenty during GMRES. A fixed-plus-DOF memory fit to the 13.8k and 38.9k
measurements includes 15% headroom. Highest frequencies enter the dynamic queue
first, execution plans and serial fallbacks are printed, and phase times,
iteration progress, residual, and peak RSS are retained in result metrics.
Receiver evaluation is now one batched native call rather than a Python loop.

An end-to-end 500--1,000 Hz smoke run validated the policy with ten concurrent
1,989-DOF solves. During GMRES each worker used roughly 1.4--2.0 cores, totaling
about 17--18 of 20 cores. All ten frequencies converged in 33--46 iterations;
the slowest completed in 140 s. Batched evaluation of 369 mouth/far-field
points took 0.70--0.75 s per frequency, and measured worker RSS was about
0.37--0.38 GiB. This is scheduler evidence, not a mesh-converged horn result.

The active implementation path is now a single throat-driven, free-air BEM
analysis on the closed acoustic boundary: internal horn wall, lip, simplified
external body, and driven throat cap. Python remains geometry/run glue while
NGSolve's native C++ core supplies matrix-free Helmholtz layer operators,
singular quadrature, FMM evaluation, and Krylov iteration.

The direct exterior Neumann solve uses the Burton--Miller equation in
NGSolve's Calderon convention,

\[
[D+i k(M/2-K)]p=[-M/2-K'-i kV]g,
\]

with single-layer Calderon preconditioning. A coarse 230-DOF pulsating sphere
matches the analytic complex boundary pressure within 0.35%. The first
930-DOF HornCAD solve completed in about 60 seconds and 96 iterations at a
relaxed benchmark tolerance; preconditioning and FMM parameter tuning remain
necessary before production sweeps.

This validation also found a sign error in the former Bempp dense reference:
its positive `M/2 + K'` right-hand-side branch had 137% complex trace error on
the pulsating sphere. The corrected negative branch has 0.47% error on the
same reference class. Any old full-body Bempp results produced before this
checkpoint must be treated as invalid and regenerated.

Immediate acceptance work:

- compare corrected Bempp dense and NGSolve FMM results on the identical small
  HornCAD mesh;
- verify far-field extraction at multiple finite radii;
- measure mesh-convergence, memory scaling, and iteration growth;
- improve the order-one Neumann preconditioner before a frequency sweep;
- validate simplified exterior bodies against a full exterior reference.

The next objective is to quantify diffraction from the HornCAD mouth and lip
for a horn radiating in free air. Do not extend the existing printable-body
exterior BEM as the default path. Model only the exterior geometry demonstrated
by convergence to affect the result.

The accepted reduced interior FEM remains the source of the horn's nonuniform
complex mouth field. Development proceeds in two stages:

1. A one-way exterior calculation driven by the saved FEM mouth normal
   velocity. This is the fastest useful lip-diffraction tool and the immediate
   implementation target.
2. A coupled FEM--BEM calculation in which the exterior BEM replaces the
   current Rayleigh mouth operator. This is the eventual authoritative model
   because exterior loading then changes the interior mouth field and throat
   impedance.

### Audit of the current "ideal aperture" result

The current radiation operator in `app/aperture_radiation.py` is the Rayleigh
infinite-planar-baffle kernel. It evaluates source and receiver separations at
the actual nonplanar mouth coordinates, so it retains phase offsets caused by
mouth setback, but the operator is not a rigorous free-air boundary condition
for a curved aperture:

- it uses the doubled free-space Green function derived for a planar rigid
  infinite baffle;
- its coupled pressure-to-velocity matrix uses positions and panel weights but
  not the spatially varying mouth normals;
- it suppresses rear radiation and contains no finite edge around which sound
  can diffract;
- it is not a spherical-baffle model.

The BEM `ideal_aperture_pressure` postprocessor includes a per-panel directional
factor, but it remains an aperture integral and not a solution for a physical
curved baffle. Until replaced, label current plots and artifacts as
`Rayleigh infinite-planar-baffle approximation with curved source coordinates`,
not simply `ideal curved aperture`.

This limitation affects both the plotted directivity and the load used by the
interior FEM. A one-way lip calculation can validly explore scattering of the
saved FEM mouth field, but it must be reported as uncoupled: the FEM field was
calculated under the Rayleigh load and the lip cannot feed back into it.

### Physical and numerical model

The desired exterior problem contains:

- the actual curved mouth coupling surface;
- the terminal portion of the internal wall needed to reach the lip;
- the complete rounded lip or sharp rim geometry;
- a configurable length of the exterior return surface behind the lip;
- unbounded free air everywhere else.

Printable rear thickness, enclosure surfaces, mounting hardware, and the rest
of the body are excluded unless an exterior-depth convergence study shows that
they materially affect the requested result.

The one-way model prescribes the complex normal velocity exported by MFEM on
the mouth. The local lip surfaces are acoustically rigid. It returns calibrated
complex exterior pressure, radiated power, and horizontal/diagonal/vertical
far-field cuts. Unit throat volume velocity remains the source normalization,
and the mouth centre remains the radiation phase origin.

The coupled model replaces the Rayleigh relation with an exterior operator of
the form

\[
p_\mathrm{mouth}=Z_\mathrm{exterior}v_\mathrm{mouth}.
\]

That operator must include the curved interface and local rigid lip so that lip
loading affects mouth pressure, mouth velocity, throat impedance, radiated
power, and directivity.

### Minimal exterior geometry and truncation

"Lip only" is an outcome to demonstrate, not an assumption. Retained exterior
depth is a convergence parameter. Begin with a nested family such as:

- mouth/rim with no exterior return;
- lip plus 25 mm of exterior return;
- lip plus 50 mm;
- lip plus 100 mm;
- full body only as a diagnostic reference if the local sequence does not
  converge.

Record the actual geometry definition and retained depth in every manifest.
Compare adjacent depths using complex pressure before normalization, radiated
power, -6 dB beamwidth, and the finite-lip-minus-free-aperture response. Accept
the smallest model for which further extension changes robust results by less
than established tolerances at all validation frequencies.

A conventional closed-obstacle exterior BEM cannot be truncated by adding an
arbitrary rigid rear cap without study: the cap is a new scatterer. Evaluate
these representations explicitly:

1. A thin, physically plausible closed annular lip/short-return solid. This is
   the preferred first implementation with Bempp because it fits the existing
   closed-surface machinery.
2. An open-screen formulation containing only the real rigid lip surfaces.
   This avoids a false closure but requires suitable open-surface spaces and
   edge treatment.
3. The coupled FEM--BEM interface plus local rigid surfaces. This is the
   preferred accepted architecture once the one-way proof works.

Never interpret agreement from a single artificial closure as proof that the
truncated geometry is adequate.

### Shared data contract

Introduce one `ApertureField`-style representation shared by FEM review and
BEM radiation code. At minimum it contains:

- frequency and time convention;
- sample positions and outward normals in metres;
- positive area weights;
- complex normal velocity and, when available, complex pressure;
- mouth centre and radiation reference;
- source volume velocity and medium properties;
- symmetry reconstruction metadata.

The adapter must read the existing MFEM `_mouth.csv` outputs without losing
their nonuniform complex field. Tests must catch reversed normals, conjugated
time conventions, incorrect quadrant reconstruction, area mismatch, and an
incorrect integrated volume velocity.

### Validation ladder

Validate identical mathematical problems before comparing different physical
models:

1. **Radiation plumbing.** Feed the same saved mouth field to the existing FEM
   coverage calculation and a shared aperture integrator. Use the same
   far-field kernel, angle grid, phase origin, time convention, normals, and
   normalization. Their result should agree to numerical precision. The
   current FEM review uses receivers at 10 m while BEM uses a far-field
   expression; remove that mismatch from the comparison harness.
2. **Analytic BEM references.** Verify a pulsating sphere and a uniform
   circular-piston/baffle case. Demonstrate decreasing complex-pressure error
   at 6/8/10 elements per wavelength.
3. **Controlled finite-edge case.** Compare the same uniform circular or
   rectangular source with no finite edge and with a finite flat baffle/lip.
   An increasing baffle should approach the appropriate reference over the
   validated angular region while a smaller edge produces repeatable
   diffraction.
4. **HornCAD one-way lip proof.** Use an accepted FEM mouth field at 1, 2.5,
   and 5 kHz. Compare free curved-source radiation, Rayleigh-baffle radiation,
   and local-lip BEM radiation. Repeat the most sensitive frequency at 6/8/10
   EPW and across exterior-depth variants.
5. **Coupled verification.** Replace the Rayleigh mouth load with the exterior
   BEM operator and compare one-way and coupled mouth fields, impedance, power,
   and far field. Only the coupled result is eligible to become the accepted
   free-air model.

Deep-null magnitude is not an acceptance metric until both mesh and retained
geometry converge. Prefer complex-pressure norm, main-lobe shape, beamwidth,
power, and symmetry error.

### First comparison artifact

Produce FEM-style logarithmic-frequency heatmaps on a common signed angle grid
from -90 to +90 degrees, with a common dB floor and -6 dB contours. The first
review figure has four rows (or four clearly matched panels) for both horizontal
and vertical planes:

1. current FEM Rayleigh infinite-baffle approximation;
2. the same FEM mouth field through the shared no-lip/free-space integrator;
3. the same field through the finite local-lip BEM;
4. local lip minus no lip, calculated from calibrated complex pressure before
   conversion to the displayed level difference.

Retain unnormalized complex pressure in NPZ/HDF5. CSV is reserved for compact
cuts and metrics.

Initial proof targets, subject to tightening from the reference cases, are:

- shared-integrator plumbing agreement within 0.1 dB throughout the main lobe;
- decreasing analytic-reference error with mesh refinement;
- less than 1 degree change in -6 dB beamwidth from 8 to 10 EPW;
- stable power sign and negligible symmetry error;
- retained-depth convergence of complex main-lobe pressure, power, and
  beamwidth.

### Immediate implementation sequence

1. Extract a shared aperture-field reader and common far-field conventions.
2. Rename plot labels and manifest descriptions that overstate the current
   Rayleigh approximation.
3. Add analytic radiation tests and a controlled finite-edge geometry.
4. Add a one-way, prescribed-mouth-velocity exterior BEM entry point.
5. Add parameterized HornCAD local-lip/return geometry without requiring the
   printable full body.
6. Generate the three-frequency comparison and exterior-depth study.
7. Verify the sensitive case at 6/8/10 EPW.
8. Design and implement the coupled FEM--BEM mouth operator only after the
   one-way geometry and radiation conventions pass these checks.

### Milestone status

- **Rayleigh reference plumbing (completed 2026-07-15).**
  `app/aperture_field.py` now provides a validated shared mouth-field record,
  MFEM CSV adapter, explicit finite-distance Rayleigh pressure evaluator,
  horizontal/vertical direction conventions, and explicit peak or on-axis
  normalization. `generate_fem_review.py` uses this shared path and records the
  model identifier, `exp(+i omega t)` convention, 10 m receiver radius, and
  legacy peak-per-frequency normalization in `responses.npz`. Regression tests
  compare the shared result directly with the former coverage equation. MFEM
  CSV files do not yet export surface normals; the adapter deliberately leaves
  them absent rather than inventing them. Normals become mandatory for the
  subsequent equivalent-source and local-lip formulations.
- **Free-field equivalent-source baseline (completed 2026-07-15).**
  The shared aperture module now evaluates a prescribed curved monopole sheet
  through the ordinary free-space Green function with no rigid screen,
  scattering object, or edge boundary. It preserves calibrated complex H/V
  pressure as well as normalized levels in the FEM review artifact. For a
  fixed mouth velocity this baseline is exactly one half of the doubled
  Rayleigh-baffle pressure (`-6.0206 dB`), so its normalized forward pattern is
  intentionally identical. Tests enforce both facts. This is a mathematical
  no-scatter reference, not a physical zero-thickness horn or accepted free-air
  solution. The first angular change belongs to the next milestone, where a
  finite closed local-lip solid scatters this incident field.
- **Closed local-lip scattering model (completed 2026-07-15, exploratory).**
  `app/local_lip_bem.py` clips the authored thick body to a configurable
  mouth-end slab, producing one oriented watertight annular solid containing
  the terminal inner wall, physical lip, exterior return, and an explicit rear
  numerical closure. Retained depth is measured behind the rearmost curved-mouth
  point; 25 and 50 mm geometry tests verify nested closure positions and
  increasing solid volume. The saved FEM velocity monopole sheet supplies the
  incident field, and a resonance-safe combined-field exterior Neumann solve
  supplies rigid-lip scattering. Results retain calibrated complex incident,
  scattered, total, and lip-difference H/D/V pressure. A 25 mm, 6-EPW, 500 Hz
  test4 proof solved 1,548 unknowns with dense LU; scattered/incident pressure
  norms were 0.105 horizontally and 0.115 vertically, changing the normalized
  patterns by up to 0.355 and 0.069 dB respectively. This proves the executable
  geometry-to-scattering path, not retained-depth convergence or two-way
  acoustic coupling. The rear closure remains an artificial scatterer until a
  depth study passes, and production-sized iterative solves still require a
  convergent preconditioned path.
- **First retained-depth audit (completed 2026-07-15; failed convergence).**
  `app/run_local_lip_study.py` now runs an ordered depth sequence with identical
  source, receiver, mesh, formulation, and solver class; preserves each
  STL/manifest/complex NPZ; and writes per-depth and adjacent-depth metrics.
  The test4 500 Hz, 6-EPW dense-reference study solved 25/50/100 mm models with
  1,548/1,790/2,198 unknowns. The 25-to-50 mm change was 14.3--15.3% complex L2
  and at most 0.255 dB normalized. The 50-to-100 mm change grew to 85.2--89.7%
  complex L2 and 2.08--3.58 dB. Scattered/incident norms rose from about 0.11
  to 0.23 to 0.61. Therefore no return length is accepted. The likely cause is
  rear radiation from the two-sided monopole sheet interacting with increasing
  retained inner-wall length and the artificial rear closure. Do not spend a
  production sweep on this representation. The next formulation must eliminate
  that artificial rear-incident field (a justified one-sided equivalent source
  or, preferably, coupled FEM--BEM) before repeating depth convergence.
- **Absorbing-closure experiment (completed 2026-07-15; rejected).** The aft
  closure can now use a mixed Robin condition with `Z/(rho*c)` recorded in the
  manifest; only labeled closure DOFs are absorbing, while the physical lip and
  return stay rigid. A 1 mm axial source offset avoids the point-source/rim
  coincidence and is applied consistently to incident and scattered fields.
  At `Z=rho*c`, the 25/50/100 mm cases absorbed positive 668/601/478 W, proving
  that the sink was active. Nevertheless, 50-to-100 mm changes remained
  83.2--89.9% complex L2 and 2.11--3.46 dB normalized. This is essentially the
  rigid-closure failure. Therefore aft reflection is not the dominant error;
  the two-sided monopole sheet illuminates the increasing internal-wall area.
  Do not tune termination impedance further. Move to a one-sided equivalent
  representation or coupled FEM--BEM.

## Completed Foundation: Reduced Interior Model (2026-07-14)

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
- A frequency-parallel resolved-mesh proof completed at 1/2/3/4/5 kHz. All
  solves converged, respectively in 93/190/388/652/992 GMRES iterations and
  29.9/60.4/123.0/205.5/313.1 solver seconds. Radiated powers for the unit
  1 m3/s calibration source were 359068/468071/400793/389055/412698 W.
  The five processes ran concurrently to exploit the M1 Ultra cores. The 5 kHz
  solve is too close to the 1,000-iteration ceiling, so improve the Helmholtz
  preconditioner before an 8/10/12 elements-per-wavelength convergence study.
  These are resolved proof values, not yet convergence-certified response data.
- Native MFEM now exports weighted complex pressure/velocity fields at the
  4,006 mouth nodes, weighted complex throat pressure, and acoustic input
  impedance `mean(p_throat)/Q`. The accepted six-frequency mesh was rerun and
  the repository review package now includes all field CSVs, impedance CSV and
  plot, mouth pressure/velocity maps, and preliminary horizontal/vertical
  ideal-aperture coverage heatmaps. The coverage integral includes interference
  across the solved mouth field but explicitly excludes lip diffraction and
  exterior-body scattering; six frequency samples are too sparse for final
  resonance or coverage characterization.
- Plotting convention: every frequency axis must be logarithmic (Bode-style).
  Coverage heatmaps place log frequency on x, angle on y, and show a -6 dB
  contour wherever the plotted quantity makes that threshold meaningful.
  Angular axes use 15-degree increments (0, 15, 30, 45, 60, 75, 90 and
  signed counterparts) unless a task explicitly requires finer labels.
- Impedance figures plot magnitude only by default. Do not add separate
  resistance, reactance, or phase traces unless a task explicitly requests
  them; retain complex impedance in exported numerical data.
- The reduced model is symmetric about both centre planes for a centred uniform
  throat source. The production solver therefore uses the positive-X/positive-Y
  quadrant with even-pressure symmetry boundaries. Its aperture operator sums
  the three mirrored source images and exports a reconstructed full mouth.
- The quadrant implementation matches full-domain 6/8-EPW impedance magnitude
  and power within 0.35% and improves measured solve time by 8.6x--30.7x.
  Representative 6/8/10-EPW convergence is complete at 500/1000/2000/3000/
  4000/5000 Hz. From 8 to 10 EPW, impedance magnitude, power, mouth RMS fields,
  and -6 dB beamwidth all change by less than 0.8%. Use 8 EPW for dense
  production sweeps and 10 EPW as the verification reference for this model.
- The convergence-supported 8-EPW quadrant dense sweep is complete at 81
  logarithmically spaced frequencies from 500 Hz through 5 kHz. All points
  converged; the 5 kHz point used 97 GMRES iterations and 10.6 solver seconds.
  `analysis/3d_comparison/` now contains this dense result rather than the
  former 6-EPW full-domain proof data.
- Checkpoint `0ba9add` improves the mixed matrix-free preconditioner by applying
  the pressure-to-mouth trace coupling in a lower block-triangular solve. On the
  accepted mesh at 5 kHz this reduced GMRES from 992 iterations / 313 seconds to
  293 iterations / 92 seconds without changing the computed response.
- The dense comparison sweep is complete at 81 logarithmically spaced points
  from 500 Hz through 5 kHz. Every point converged. The repository package under
  `analysis/3d_comparison/` compares the same frequencies with the lossless
  Webster impedance model and uniform curved-aperture coverage model, and keeps
  the dense complex mouth fields in compressed form. This completes the useful
  dense sweep, preconditioner improvement, and comparison with the earlier
  simplified analysis. Mesh convergence and exterior lip diffraction remain
  later roadmap items.

Primary references used for the solver decision:

- MFEM build/platform support: https://mfem.org/building/
- MFEM parallel complex example 35p: https://docs.mfem.org/4.8/ex35p_8cpp_source.html
- DOLFINx complex Helmholtz example:
  https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_helmholtz.html
- PETSc complex and macOS configuration: https://petsc.org/main/install/install/

The indented roadmap below is the original full-body BEM proposal. It is kept
only as historical design context. Its `full_exterior_bem` default, complete
printable-body geometry, and generic `ideal_baffled_aperture` comparison are
superseded by the 2026-07-15 free-air curved-mouth/local-lip restart section at
the top of this document. Do not use its delivery sequence as the active work
queue.

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
