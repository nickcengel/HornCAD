# Widget To STL

Use this folder for the current widget-to-STL workflow.

## Files

- `center_profile_surface_explorer.html` - browser widget for designing the surface.
- `export_center_profile_surface_zoned.py` - preferred STL exporter.
- `export_center_profile_surface_working.py` - older angular exporter, kept for comparison.
- `output/` - generated STL files.

## Workflow

1. Open `center_profile_surface_explorer.html` in a browser.
2. Set the widget controls.
3. Copy the same values into `PARAMS` at the top of `export_center_profile_surface_working.py`.
4. Generate the preferred STL:

   ```bash
   python tools/widget-2-stl/export_center_profile_surface_zoned.py
   ```

5. Open:

   ```text
   tools/widget-2-stl/output/center_profile_surface_zoned.stl
   ```

## Notes

- Use `export_center_profile_surface_zoned.py` first. It samples the top and bottom spans by `x`, which currently gives the best mouth behavior.
- Use `export_center_profile_surface_working.py` only for comparison with the widget's original angular-ring sampling.
- Generated STL files are ignored by git.
- Agent/developer context for this workflow is in `../../docs/AGENT_HANDOFF.md`.
