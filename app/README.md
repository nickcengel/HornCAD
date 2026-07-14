# HornCAD App

`HornCAD.html` is the current app. It is a standalone browser tool: open the file directly, adjust the controls, then export STL or YAML from the page.

## Files

- `HornCAD.html` - browser app for designing and exporting horn geometry.
- `export_horncad.py` - Python reference exporter for the same geometry path.
- `output/` - ignored Python exporter output.

## Export Modes

- `Acoustic surface` exports the open inner acoustic surface.
- `Body` exports the thickened printable body with mouth return and mounting flange.

Browser exports are named:

```text
HornCAD-Surface-<WxHxL>.STL
HornCAD-Body-<WxHxL>.STL
HornCAD-Surface-<WxHxL>.YAML
HornCAD-Body-<WxHxL>.YAML
```

## Command-Line STL Export

The browser is the primary app. Use the Python exporter when you want to regenerate an STL from a YAML file exported by the app:

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
