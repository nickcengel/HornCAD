# Agent Handoff

This file is for future coding agents. Read it before changing geometry, widgets,
or STL generation.

## Recovery Rule

- Use git before modifying files.
- If an experiment may fail, make a checkpoint commit first or verify the current
  commit hash.
- Do not rely on memory to revert. Use git diffs and commits.

## Current Active Workflow

The current exploratory workflow lives in:

```text
tools/widget-2-stl/
```

Key files:

- `center_profile_surface_explorer.html` - interactive design widget.
- `export_center_profile_surface_zoned.py` - preferred STL preview exporter.
- `export_center_profile_surface_working.py` - older angular exporter, kept for comparison.
- `README.md` - user-facing widget-to-STL workflow.

Generated STL output goes to:

```text
tools/widget-2-stl/output/
```

That directory is ignored by git.

## Important Geometry Lessons

The angular-ring mesh path caused repeated failures near the mouth:

- visually flat center spans on the cylindrical mouth,
- huge STL files,
- poor high-`N` behavior,
- confusing wireframe artifacts.

The working preview exporter uses an x-sampled topology:

- upper half of each section sampled uniformly by `x`,
- lower half sampled uniformly by `x`,
- cylindrical mouth setback computed directly from `x`,
- mesh exported through `trimesh`,
- current diagnostics should report one connected component and consistent winding.

Do not reintroduce the four-zone top/side/bottom/side mesh. It folded over itself
because the side zones overlapped the superellipse top/bottom spans.

## Widget State

The widget currently:

- uses the same x-sampled upper/lower section topology as the zoned STL exporter,
- has Top, Side, Front, Iso, and Orbit views,
- supports drag-to-orbit and wheel zoom,
- fits views to projected bounds to avoid truncation,
- still uses simple canvas wireframe rendering, not true hidden-line 3D rendering.

If the user says something like:

```text
I want to revisit side bow profiles for the widget.
```

Interpret that as work on the section modifier model in:

```text
tools/widget-2-stl/center_profile_surface_explorer.html
```

Relevant controls today:

- `Side span bow mm`
- `Top/bottom span bow mm`
- `Bow reaches mouth %`

Current implementation details:

- bow is applied inside `sectionPointFromXY(...)`;
- side bow uses `sideWindow = u*u*(1-v*v)`;
- top/bottom bow uses `topBottomWindow = v*v*(1-u*u)`;
- `mouthFade` suppresses bow near the mouth;
- `bowProgress(...)` controls how bow grows along `z`.

Known open question:

- The current bow controls are low-level and not a satisfying authoring model.
- A better future model may use explicit H/V guide profiles, or separate section
  modifier curves that describe how span curvature changes across a slice.
- Do not casually mix this with the STL mouth topology unless the intended
  surface mapping is stated clearly.

## Current STL Export Commands

Preferred preview STL:

```bash
python tools/widget-2-stl/export_center_profile_surface_zoned.py
```

Older angular comparison STL:

```bash
python tools/widget-2-stl/export_center_profile_surface_working.py
```

## Current Dependencies

`trimesh` and `networkx` were installed in the project environment to support
mesh validation/normal repair in the zoned exporter.

## Caution

The main HornCAD project pipeline under `horncad/` is separate from the current
widget-to-STL exploratory workflow. Do not assume widget experiments should be
copied into `horncad/surface.py` until the geometry is stable and intentionally
specified.
