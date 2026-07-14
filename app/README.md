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

Run the coupled 3D boundary-element model at eight logarithmically spaced frequencies from 500 Hz to 5 kHz:

```bash
python app/helmholtz_bem_3d.py path/to/config.YAML
```

The solver builds a closed acoustic obstacle from the printable HornCAD body and unions a thin cap into the open throat. The horn-facing disk of that cap is the only driven Neumann boundary; the horn walls, mouth body, and exterior body are rigid. This prevents a rear monopole from leaking around the mount while allowing the throat, horn interior, mouth, and exterior field to remain fully coupled.

The exterior radiation problem uses Bempp-cl's second-kind single-layer Neumann equation. GMRES convergence is checked at every frequency because this formulation can become ill-conditioned near fictitious interior resonances. The output contains normalized horizontal, diagonal, and vertical far-field cuts, a discrete low-resolution heatmap, and their CSV matrices. The heatmap keeps each simulated frequency as a separate column without interpolation.

The default `--side-samples 16 --stations 18` mesh is a practical pilot mesh, not a converged 5 kHz production mesh. Increase it with, for example, `--side-samples 20 --stations 22`, and compare lobe locations and broad levels. Deep null depth is especially mesh-sensitive.
