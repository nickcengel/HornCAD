# HornCAD

HornCAD is currently a standalone browser app for designing and exporting horn and waveguide geometry.

Open the app directly:

```text
app/HornCAD.html
```

The app can export:

- `HornCAD-Surface-<WxHxL>.YAML` or `HornCAD-Body-<WxHxL>.YAML` - design configuration.

Use the Python exporter to convert YAML to STL:

- `HornCAD-Surface-<WxHxL>.STL` - open acoustic surface.
- `HornCAD-Body-<WxHxL>.STL` - thickened printable body.

Historical experiments and superseded designs live in `archive/` and are not part of the current workflow.

Kept live documentation:

- `docs/horncad_context.md`
- `docs/candidate_matrix.md`
- `docs/Research/`

For app-specific notes, see `app/README.md`.

To regenerate an STL from a YAML file exported by the app:

```bash
python app/export_horncad.py path/to/config.YAML
```

To run the one-dimensional Webster acoustic screening model:

```bash
python app/webster_1d.py path/to/config.YAML
```

To generate the complete reduced 3D FEM review directly from YAML:

```bash
python app/run_fem_suite.py path/to/config.YAML \
  --output-dir analysis/my-study --title "My horn"
```

To run a complete free-air all-BEM analysis directly from YAML:

```bash
python app/run_bem_suite.py path/to/config.YAML \
  --output-dir analysis/my-bem-study --title "My horn"
```
