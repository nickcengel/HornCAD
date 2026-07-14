# HornCAD App

`HornCAD.html` is a standalone browser tool. Open it directly, adjust the controls, and export the design as YAML.

## Files

- `HornCAD.html` - browser app for designing horn geometry and authoring YAML.
- `export_horncad.py` - Python STL exporter for the same geometry path.
- `webster_1d.py` - one-dimensional acoustic screening model.
- `aperture_directivity.py` - normalized H/V far-field aperture estimate.
- `helmholtz_2d.py` - independent H/V pressure-acoustics FEM solver.
- `helmholtz_bem_3d.py` - coupled three-dimensional Helmholtz BEM solver.
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

Run the coupled 3D boundary-element comparison pipeline at eight logarithmically spaced frequencies from 500 Hz to 5 kHz:

```bash
python app/helmholtz_bem_3d.py path/to/config.YAML
```

The solver builds a closed acoustic obstacle from the printable HornCAD body and a circular throat cap. The horn-facing disk is a uniform axial piston; by default its integrated volume velocity is exactly 1 m³/s. Its pressure Neumann condition is derived from that velocity and the recorded medium properties. All other physical surfaces are rigid.

The exterior radiation problem uses a regularized combined-field Neumann equation to avoid fictitious interior resonances. Production meshes enforce every edge at eight elements per wavelength at the sweep's highest frequency. `--mesh-tier preview` selects 6; verification tiers select 10 or 12. Watertightness, orientation, connectedness, edge length, minimum angle, and aspect ratio are checked before solving.

Each frequency is stored atomically as a complex NPZ artifact, so an interrupted run resumes without recomputing completed frequencies. The JSON manifest records normalized inputs, source and coordinate definitions, mesh quality and cost, solver tolerances and versions, artifact hashes, and convergence status. Compact optimizer-facing metrics are written to CSV.

At each frequency the pipeline preserves complex pressure and outward normal velocity on a conformal mouth observer offset 1 mm into the exterior. It calculates two first-class radiation results from the same solution: full exterior BEM (including the finite body and edge diffraction) and an ideal infinite-baffle aperture integral (excluding those effects). Both retain unnormalized complex pressure and use the mouth centre as phase origin; normalized plots are derived products.

Useful controls:

```bash
python app/helmholtz_bem_3d.py config.YAML --mesh-tier preview
python app/helmholtz_bem_3d.py config.YAML --elements-per-wavelength 10
python app/helmholtz_bem_3d.py config.YAML --observer-offset-mm 1 --no-resume
python app/helmholtz_bem_3d.py config.YAML --maximum-workers 0 --memory-limit-gib 48
python app/helmholtz_bem_3d.py config.YAML --direct-solve-max-dofs 500
python app/helmholtz_bem_3d.py config.YAML --formulation single-layer-preview
```

`--maximum-workers 0` (the default) auto-schedules independent frequencies from
the available CPU count and a conservative dense-operator memory estimate. It
also partitions Numba threads between workers, preventing process/thread
oversubscription. On a 20-core, 64 GiB machine, `--memory-limit-gib 48` reserves
roughly one quarter of memory for the operating system and plotting.
GMRES is used at every mesh size by default; dense LU is cubic and is reserved
for deliberately tiny reference cases through `--direct-solve-max-dofs`.
The `single-layer-preview` formulation assembles one dense operator and is
intended for low-cost proof-of-concept sweeps. It can fail near fictitious
interior resonances. The default `combined-field` formulation is resonance-safe,
uses four operators, and remains the production-validation target.
The experimental `--operator-assembler fmm` path must not be used for accepted
results until the installed ExaFMM backend passes a dense complex-operator
comparison on the target platform.

For programmatic studies, construct `PipelineSettings` and call `run_pipeline(...)`. The returned structure contains the mesh report, observer geometry, complex per-frequency results, manifest, and artifact paths. A single mesh always covers the entire sweep. Production acceptance still requires an explicit 8/10/12 convergence study; deep-null depth is not a stable optimization metric until that study passes.
