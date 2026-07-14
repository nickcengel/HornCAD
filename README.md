# HornCAD

HornCAD is currently a standalone browser app for designing and exporting horn and waveguide geometry.

Open the app directly:

```text
app/HornCAD.html
```

The app can export:

- `HornCAD-Surface-<WxHxL>.YAML` or `HornCAD-Body-<WxHxL>.YAML` - widget configuration.

Use the Python exporter to convert YAML to STL:

- `HornCAD-Surface-<WxHxL>.STL` - open acoustic surface.
- `HornCAD-Body-<WxHxL>.STL` - thickened printable body.

The Python package, tests, examples, exploratory widgets, and older design docs have been moved to `archive/`. They are retained for reference but are not part of the current app workflow.

Kept live documentation:

- `docs/horncad_context.md`
- `docs/Research/`

For app-specific notes, see `app/README.md`.

To regenerate an STL from a YAML file exported by the app:

```bash
python app/export_horncad.py path/to/config.YAML
```
