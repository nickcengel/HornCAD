# HornCAD App

`HornCAD.html` is the current app. It is a standalone browser tool: open the file directly, adjust the controls, then export YAML from the page.

## Files

- `HornCAD.html` - browser app for designing horn geometry and authoring YAML.
- `export_horncad.py` - Python STL exporter for the same geometry path.
- `output/` - ignored Python exporter output.

## Browser Output

The browser always renders the open acoustic surface. The Body/Acoustic surface option controls the YAML export mode only; STL generation happens from the command line. YAML writes `stl_export_mode` as `body` or `surface`.

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

The exporter reads the YAML settings, writes an STL to `app/output/`, and names it with the same convention as the browser:

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
