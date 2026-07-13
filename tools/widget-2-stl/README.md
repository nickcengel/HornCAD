# Widget To STL

Use this folder for the current widget-to-STL workflow.

## Files

- `center_profile_surface_explorer.html` - browser widget for designing the surface.
- `export_center_profile_surface_zoned.py` - supported STL exporter.
- `output/` - generated STL files.

## Workflow

1. Open `center_profile_surface_explorer.html` in a browser.
2. Set the widget controls.
3. Set `STL z stations` and `STL half samples` in the View panel.
4. Click `Export YAML` to save the current widget design state.
5. Click `Export STL` to save the current surface mesh.

The browser export writes a binary STL directly from the widget geometry. It uses the same square-boundary section topology as the Python exporter. `STL export` selects either the closed mount/body mesh or the inner acoustic surface.

The YAML export is a widget-native config. It records the visible controls and derived solved `S` values needed to inspect or recreate the design intent.

## Python Fallback

Use this path when you want a script-generated STL file or need to inspect exporter code directly.

1. Copy the same values into `PARAMS` at the top of `export_center_profile_surface_zoned.py`.
2. Generate the STL:

   ```bash
   python tools/widget-2-stl/export_center_profile_surface_zoned.py
   ```

3. Open:

   ```text
   tools/widget-2-stl/output/center_profile_surface_zoned.stl
   ```

## Notes

- `export_center_profile_surface_zoned.py` is the only supported Python exporter for this widget workflow.
- In `body` mode, the supported STL path creates a watertight body from the inner horn surface, mouth return, radial outer offset, and driver mount flange.
- In `acoustic_surface` mode, the STL path exports the oriented inner acoustic surface only.
- Horn stations are distributed by accumulated H/V profile-radius change rather than uniform `z` distance.
- `Side guide K` defines an OS-SE guide profile with the same throat, horizontal coverage, horizontal N, and mouth endpoint as the horizontal basis. `Side guide amount %` applies a signed percentage of `guide - basis` to the side span.
- Generated STL files are ignored by git.
- Agent/developer context for this workflow is in `../../docs/AGENT_HANDOFF.md`.
