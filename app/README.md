# HornCAD App

`HornCAD.html` is a standalone browser tool. Open it directly, adjust the controls, and export the design as YAML.

## Files

- `HornCAD.html` - browser app for designing horn geometry and authoring YAML.
- `export_horncad.py` - Python STL exporter for the same geometry path.
- `webster_1d.py` - one-dimensional acoustic screening model.
- `aperture_directivity.py` - normalized H/V far-field aperture estimate.
- `helmholtz_2d.py` - independent H/V pressure-acoustics FEM solver.
- `helmholtz_bem_3d.py` - coupled three-dimensional Helmholtz BEM solver.
- `local_lip_bem.py` - one-way local rigid-lip scattering from saved FEM mouth fields.
- `output/` - ignored output from the Python exporter.

## Browser Output

The browser always previews the open acoustic surface. The Body/Acoustic surface option controls the mode recorded in YAML; STL generation happens on the command line. The YAML root is `horncad_config`, and `body.stl_export_mode` is `body` or `surface`.

Browser YAML exports are named:

```text
HornCAD-Surface-<WxHxL>.YAML
HornCAD-Body-<WxHxL>.YAML
```

## Command-Line STL Export

Use the Python exporter when you want to regenerate an STL from a YAML file exported by the app:

```bash
python app/export_horncad.py path/to/HornCAD-Surface-400x260x250.YAML
```

The exporter reads the YAML settings, writes an STL to `app/output/`, and uses the same naming convention as the browser:

```text
HornCAD-<Surface|Body>-<WxHxL>.STL
```

Useful options:

```bash
python app/export_horncad.py path/to/config.YAML --mode body
python app/export_horncad.py path/to/config.YAML --mode surface
python app/export_horncad.py path/to/config.YAML --output-dir exports/
```

Running without a YAML file exports the built-in defaults:

```bash
python app/export_horncad.py
```

## Webster 1D Acoustic Screening

Run the lossless one-dimensional Webster model against a browser-exported design:

```bash
python app/webster_1d.py path/to/HornCAD-Body-400x260x250.YAML
```

The solver samples HornCAD's actual section polygons into an area profile, including the conical extension, squareness morph, and enabled profile modifiers. It derives and validates horizontal and vertical `S`; either value being negative rejects the design.

By default, the model sweeps 100 Hz to 20 kHz and terminates the equivalent circular mouth with a baffled-piston radiation impedance. It writes three files to `app/output/`:

```text
<design>-Webster1D.csv
<design>-Webster1D-Area.csv
<design>-Webster1D-Normalized-Impedance.png
<design>-Webster1D.json
```

The frequency CSV contains complex input impedance, throat reflection, mouth pressure, mouth volume velocity, and radiated power for a unit throat volume velocity. The area CSV records the sampled geometry. The PNG plots complex throat input impedance normalized by `rho*c/throat_area` over logarithmic frequency. The JSON file records assumptions, run settings, derived `S`, summary metrics, and artifact paths.

Useful options:

```bash
python app/webster_1d.py config.YAML --start-hz 200 --stop-hz 16000
python app/webster_1d.py config.YAML --frequencies 401 --spacing linear
python app/webster_1d.py config.YAML --stations 801 --mouth-load anechoic
python app/webster_1d.py config.YAML --density 1.2041 --sound-speed 343.21
python app/webster_1d.py config.YAML --output-dir experiments/
```

This is a comparative plane-wave model, not a directivity simulation. It assumes lossless rigid walls, uses projected section area, and represents the varying horn as locally uniform transmission-line segments. It does not model transverse modes, H/V directivity, corner behavior, viscothermal loss, or full three-dimensional mouth diffraction.

## Aperture Directivity Estimate

Generate normalized horizontal and vertical directivity heatmaps from 250 Hz to 10 kHz:

```bash
python app/aperture_directivity.py path/to/config.YAML
```

This integrates a uniform-velocity source over HornCAD's projected mouth outline and includes phase differences from mouth curvature. Every frequency is normalized to 0 dB on-axis. The output is useful for examining aperture size and shape, but it is not a Helmholtz simulation: it does not include the horn's internal pressure distribution, nonuniform mouth velocity, edge diffraction, or H/V mode coupling.

## Helmholtz 2D Directivity

Run independent horizontal and vertical pressure-acoustics FEM models from 250 Hz to 10 kHz:

```bash
python app/helmholtz_2d.py path/to/config.YAML
```

Each model uses the corresponding HornCAD wall profile, a symmetry boundary along the horn axis, rigid horn and baffle surfaces, a throat source, an exterior air domain, and a first-order outgoing-wave boundary. Receiver pressure is sampled on a semicircular arc and normalized to the axial receiver at every frequency.

The default mesh uses six linear elements per wavelength at 10 kHz. Increase convergence with `--elements-per-wavelength 8` or move the outgoing boundary with `--exterior-extent 0.5`. Exact null depths should not be trusted until both settings have been checked.

This is substantially more informative than the uniform-aperture estimate, but it remains a 2D approximation. Each plane assumes invariance in its missing dimension, and the first-order absorbing boundary leaves some exterior-domain sensitivity. It cannot reproduce H/V coupling, diagonal radiation, three-dimensional corner modes, or the loading of the complete rectangular aperture.

## Helmholtz 3D BEM Directivity

Run the coupled 3D boundary-element comparison pipeline at ten logarithmically spaced frequencies from 500 Hz to 8 kHz:

```bash
python app/helmholtz_bem_3d.py path/to/config.YAML
```

The solver builds a closed acoustic obstacle from the printable HornCAD body and a circular throat cap. The horn-facing disk is a uniform axial piston; by default its integrated volume velocity is exactly 1 m³/s. Its pressure Neumann condition is derived from that velocity and the recorded medium properties. All other physical surfaces are rigid.

The exterior radiation problem uses a regularized combined-field Neumann equation to avoid fictitious interior resonances. Select `--solver-backend ngsolve-fmm` for native matrix-free layer operators, singular quadrature, FMM evaluation, weakly singular hypersingular regularization, and Laplace-Calderon-preconditioned GMRES. Python remains the geometry, sweep, and artifact layer. The legacy `bempp-dense` backend is retained as a small-problem numerical reference; results made before the 2026-07-15 Calderon sign correction must be regenerated.

The default production sweep is 500 Hz--8 kHz at six elements per wavelength.
The ten logarithmically spaced frequencies include both endpoints and match
the default 10-process by 2-thread execution plan on a 20-core workstation. Use
`--mesh-tier verification-8`, `verification-10`, or `verification-12` for
convergence runs. Watertightness, orientation, connectedness, edge length,
minimum angle, and aspect ratio are checked before solving.

The default `netgen` surface mesher remeshes the closed authored shell before
solving. It removes the extreme slivers retained by global subdivision and is
required for the current 2--10 kHz production path. `--surface-mesher
subdivide` retains the historical mesh for controlled comparisons. The default
GMRES tolerance is `1e-4`; use `1e-3` for scaling previews and `1e-5` for a
verification rerun.

The authored STL tessellation supplied to Netgen defaults to 12 samples around
each section and 16 stations axially. This is distinct from acoustic 6-EPW
resolution. A Test4 meshing-only study found that 12×16 removes the persistent
aspect-32 transition produced by 12×12 (maximum aspect approximately 2.4),
reduces the 2 kHz mesh by 11%, and leaves 8 kHz mesh size and time essentially
unchanged. Higher seed density did not consistently reduce the final mesh and
some combinations damaged closure. See
`analysis/all_bem_backend_optimization/mesh-seed-study.md`.

Each frequency is stored atomically as a complex NPZ artifact, so an interrupted run resumes without recomputing completed frequencies. The JSON manifest records normalized inputs, source and coordinate definitions, mesh quality and cost, solver tolerances and versions, artifact hashes, and convergence status. Compact optimizer-facing metrics are written to CSV.

At each frequency the pipeline preserves complex pressure and outward normal velocity on a conformal mouth observer offset 1 mm into the exterior. It calculates two first-class radiation results from the same solution: full exterior BEM (including the finite body and edge diffraction) and an ideal infinite-baffle aperture integral (excluding those effects). Both retain unnormalized complex pressure and use the mouth centre as phase origin; normalized plots are derived products.

Useful controls:

```bash
python app/helmholtz_bem_3d.py config.YAML --mesh-tier preview
python app/helmholtz_bem_3d.py config.YAML --solver-backend ngsolve-fmm
python app/helmholtz_bem_3d.py config.YAML --geometry-side-samples 6 --geometry-axial-stations 8
python app/helmholtz_bem_3d.py config.YAML --surface-mesher netgen --netgen-maxh-factor 0.5
python app/helmholtz_bem_3d.py config.YAML --fmm-min-order 6 --fmm-order-factor 0.8 --fmm-separation 1.5
python app/helmholtz_bem_3d.py config.YAML --elements-per-wavelength 10
python app/helmholtz_bem_3d.py config.YAML --observer-offset-mm 1 --no-resume
python app/helmholtz_bem_3d.py config.YAML --maximum-workers 0 --memory-limit-gib 48
python app/helmholtz_bem_3d.py config.YAML --direct-solve-max-dofs 500
python app/helmholtz_bem_3d.py config.YAML --formulation single-layer-preview
```

`--maximum-workers 0` (the default) balances the complete native-FMM solve:
standalone RHS construction is effectively serial per frequency, while GMRES
scales across native threads. On the 20-core reference machine the default is
therefore ten frequency workers with two threads each. Frequencies are queued
highest first to expose memory or convergence failures early. The measured FMM
memory model includes fixed process cost, DOF-dependent storage, and 15%
headroom; `--memory-limit-gib 48` also reserves roughly one quarter of the
machine for the operating system and final artifact generation. The execution
plan is printed before solving, and a sandbox-induced serial fallback is
reported as a warning. Receiver points are evaluated in one native batch rather
than a serial Python loop.
GMRES is used at every mesh size by default; dense LU is cubic and is reserved
for deliberately tiny reference cases through `--direct-solve-max-dofs`.
The `single-layer-preview` formulation assembles one dense operator and is
intended for low-cost proof-of-concept sweeps. It can fail near fictitious
interior resonances. The default `combined-field` formulation is resonance-safe,
uses four operators, and remains the production-validation target.
The experimental `--operator-assembler fmm` path must not be used for accepted
results until the installed ExaFMM backend passes a dense complex-operator
comparison on the target platform.

### One-way local-lip scattering

Use a saved MFEM mouth field as a curved free-field monopole sheet and scatter
it from a watertight mouth-end section of the authored thick body:

```bash
python app/local_lip_bem.py config.YAML path/to/d000_mouth.csv 500 \
  --retained-depth-mm 25 --elements-per-wavelength 6 \
  --output-dir analysis/local-lip-500
```

The retained depth is measured behind the rearmost point of the curved mouth,
which keeps the complete perimeter connected. The clipped rear annulus is a
numerical closure and therefore must be varied in a retained-depth convergence
study. Outputs include the local STL, provenance manifest, calibrated complex
incident/scattered/total H/D/V pressures, the complex lip difference, and a
comparison plot. This is a one-way model: the lip scatters the saved FEM field
but does not feed back into the interior solution or throat impedance.

Proof-scale meshes below 2,000 unknowns use dense LU. Larger cases use the
combined-field GMRES path and fail rather than accepting non-convergence. The
current result is an exploratory local-scattering model, not yet the accepted
coupled free-air solution.

Run a retained-depth study with identical numerical settings using:

```bash
python app/run_local_lip_study.py config.YAML path/to/d000_mouth.csv 500 \
  --depths-mm 25 50 100 --elements-per-wavelength 6 \
  --termination-impedance-factor 1 \
  --output-dir analysis/local-lip-depth-500
```

The runner keeps every depth's complete artifacts and writes per-depth metrics,
adjacent complex-pressure convergence, a comparison plot, and an explicit
acceptance result. Provisional gates require the deepest adjacent pair to stay
within 5% complex L2 error, 0.5 dB normalized-pattern change, and 1 degree
beamwidth change in every H/D/V cut.

`--termination-impedance-factor 1` replaces the artificial rigid aft closure
with the local characteristic impedance `Z=rho*c`; other positive values scale
that impedance. The physical lip and return remain rigid. This Robin condition
is assembled into the dense combined-field matrix, not applied as a
postprocessing correction. The manifest records closure faces, source-sheet
offset, impedance factor, and positive absorbed power.

For programmatic studies, construct `PipelineSettings` and call `run_pipeline(...)`. The returned structure contains the mesh report, observer geometry, complex per-frequency results, manifest, and artifact paths. A single mesh always covers the entire sweep. Production acceptance still requires an explicit 8/10/12 convergence study; deep-null depth is not a stable optimization metric until that study passes.

## Reduced Interior-Aperture Reference

`acoustic_domain.py` builds the primary reduced model: internal rigid wall,
driven throat disk, and a computational mouth aperture. `aperture_radiation.py`
implements the nonlocal infinite-baffle Rayleigh operator, and
`interior_fem.py` provides the serial reference coupled solve.

### Complete FEM suite from YAML

Run mesh generation, a resumable parallel frequency sweep, and all standard
review plots with one command:

```bash
python app/run_fem_suite.py path/to/HornCAD-Body-400x280x300.YAML \
  --output-dir analysis/my-study --title "400 × 280 study"
```

Defaults are the accepted study settings: quadrant symmetry, eight elements
per wavelength at 5 kHz, 500 Hz–5 kHz, 12 points per octave, 20 TetWild
threads, and up to 10 concurrent frequency solves. The output directory
contains:

```text
interior_quadrant.msh
mesh_report.json
run_settings.json
fields/
figures/coverage_heatmaps.png
figures/throat_impedance_magnitude.png
figures/solver_performance.png
metrics.csv
responses.npz
```

The coverage review is explicitly a Rayleigh infinite-planar-baffle reference.
It evaluates solved mouth velocity at the actual nonplanar mouth coordinates,
so mouth-setback phase is retained, but it is not a curved- or
spherical-baffle solution and it contains no finite-lip diffraction. The
`responses.npz` artifact records the radiation-model identifier, time
convention, receiver radius, and normalization convention used by the review.

The same artifact also contains a free-field curved monopole-sheet baseline
under the `free_field_*` keys, including calibrated complex H/V receiver
pressure and normalized levels. This source sheet is not a zero-thickness rigid
screen: it is a prescribed equivalent-source integral in unrestricted space,
with no lip boundary or diffraction. Removing the Rayleigh image source makes
its calibrated pressure exactly half the infinite-baffle result
(`-6.0206 dB`) while leaving peak-normalized directivity unchanged. A separate
`figures/free_field_monopole_heatmaps.png` makes that baseline explicit.

The YAML hash and numerical settings in `run_settings.json` prevent accidental
reuse of a mesh generated for another design or resolution. Re-running the
same command resumes completed frequencies. Use a different output directory
for changed settings; `--force-remesh` deliberately deletes that directory's
existing raw fields and rebuilds the mesh.

Useful controls:

```bash
python app/run_fem_suite.py config.YAML --output-dir analysis/run \
  --start-hz 500 --stop-hz 5000 --points-per-octave 12 \
  --elements-per-wavelength 8 --workers 10 --mesh-threads 20
python app/run_fem_suite.py config.YAML --output-dir analysis/run \
  --binary /path/to/horncad_mfem_interior
```

The current serial UMFPACK pressure-block backend is validated only through
5 kHz at this resolution. The CLI rejects a higher stop frequency unless
`--allow-above-validated-limit` is supplied for deliberate backend experiments;
that override does not make the result validated or guarantee that the sparse
factorization will fit in memory.

The native MFEM cross-check is built separately:

```bash
cmake -S app/mfem -B build/mfem -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/mfem
cmake --build build/mfem --parallel 20
build/mfem/horncad_mfem_interior path/to/interior.msh 500
```

When MFEM is built with MPI and 64-bit SuperLU_DIST, CMake also creates
`horncad_mfem_interior_parallel`. Run one frequency with, for example:

```bash
mpirun -np 4 build/mfem/horncad_mfem_interior_parallel \
  path/to/interior.msh 5000 --quadrant-symmetry \
  --output-prefix path/to/f5000
```

The YAML suite can invoke that backend directly. Start with one frequency job
at a time because each MPI solve performs a distributed sparse factorization:

```bash
python app/run_fem_suite.py config.YAML --output-dir analysis/run \
  --binary build/mfem/horncad_mfem_interior_parallel \
  --mpi-ranks 4 --workers 1
```

Build and validation details, including the current 10 kHz status, are recorded
in `docs/fem_parallel_pressure_backend.md`.

Add `--output-prefix path/to/f0500` to write weighted complex mouth pressure and
normal velocity, weighted throat pressure, and a summary containing complex
acoustic input impedance. The executable creates `_mouth.csv`, `_throat.csv`,
and `_summary.csv` files.

For the native Apple Silicon tetrahedral backend, install the optional group:

```bash
python -m pip install -e '.[acoustics-native]'
```

`write_tetwild_volume_mesh(...)` uses TetWild's native ARM64/TBB wheel, transfers
the wall/throat/mouth labels by closest-surface queries, enforces throat and
mouth area tolerances, and rejects any tetrahedron exceeding the requested hard
edge limit. The original Gmsh writer remains available as the portable reference.

The MFEM executable uses a matrix-free mixed operator with restarted GMRES. It
applies the sparse interior Helmholtz matrix and dense nonlocal aperture matrix
as separate blocks. Its preconditioner factors those two diagonal blocks, not
the globally coupled matrix. On the current 3,974-pressure/963-mouth-DOF
validation mesh, the 500 Hz solve takes about 0.9 seconds instead of roughly 18
minutes for the former global complex-UMFPACK validation solve.

Generate the standard coverage heatmaps, magnitude-only throat impedance,
solver-performance plot, compact response array, and numerical metrics from any
MFEM dense-sweep field directory with:

```bash
python app/generate_fem_review.py path/to/fields --output-dir path/to/study \
  --title "Design name"
```

Compare the −6 dB horizontal/vertical coverage and magnitude-only throat
impedance from two or more generated review packages with:

```bash
python app/compare_fem_reviews.py path/to/study-a path/to/study-b \
  --labels "Study A" "Study B" --output-dir path/to/comparison
```

The preconditioner is block-triangular: it solves the sparse pressure block,
injects that pressure trace into the mouth residual, then solves the complex
aperture block. On the accepted 5 kHz mesh this reduced the 5 kHz solve from
992 iterations / 313 seconds to 293 iterations / 92 seconds without changing
the acoustic result.

For designs and sources symmetric about both centre planes, build the positive-X/
positive-Y domain with `build_quadrant_acoustic_domain(...)` and run MFEM with
`--quadrant-symmetry`. The cut faces use the natural rigid/even-pressure
condition. The nonlocal aperture operator includes all four mirrored source
images, source flow is quartered, power is restored to the full aperture, and
field CSVs reconstruct all four quadrants. Validation against full-domain 6/8
EPW solves agrees within 0.35% for impedance magnitude and power while reducing
solve time by up to about 31x.

The original executable remains a serial single-frequency reference. The
parallel executable distributes the pressure space and sparse factorization;
the aperture vector remains replicated because it is much smaller than the
volume pressure problem.
