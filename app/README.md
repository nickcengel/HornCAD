# HornCAD App

`HornCAD.html` is a standalone browser tool. Open it directly, adjust the controls, and export the design as YAML.

## Files

- `HornCAD.html` - browser app for designing horn geometry and authoring YAML.
- `export_horncad.py` - Python STL exporter for the same geometry path.
- `webster_1d.py` - one-dimensional acoustic screening model.
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
