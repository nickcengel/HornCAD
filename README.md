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
