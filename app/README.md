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

## Python Reference Export

The browser is the primary app. Use the Python exporter only when you need a script-generated reference STL:

```bash
python app/export_horncad.py
```

The exporter writes to `app/output/`.
