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
- `export_center_profile_surface_zoned.py` - supported STL preview exporter.
- `README.md` - user-facing widget-to-STL workflow.

Generated STL output goes to:

```text
tools/widget-2-stl/output/
```

That directory is ignored by git.

## Important Geometry Lessons

The removed angular-ring mesh path caused repeated failures near the mouth:

- visually flat center spans on the mouth sag surface,
- huge STL files,
- poor high-`N` behavior,
- confusing wireframe artifacts.

The supported exporter uses a square-boundary section topology:

- all four sides sampled with the same method so H and V are peers,
- mouth setback computed from one sag radius with H/V axis participation toggles,
- inner acoustic horn surface is wrapped with an acoustic-normal offset surface,
  a rear mouth closure, and a driver mount flange to form the printable body,
- the inner rear mouth ring sits at `mouth_sag_radius - mouth_rear_offset`;
  the rear closure bridges from that ring to the terminal offset horn wall ring
  instead of trimming and reparameterizing the forward outer horn wall,
- body export prints `constructed_min_wall`; this is the corresponding
  inner-to-outer horn-wall clearance and should be at least `minimum_wall`,
- STL export mode can be `body` or `acoustic_surface`; body mode should be
  watertight, acoustic surface mode is intentionally open,
- mesh exported through `trimesh`,
- current body diagnostics should report watertight, one connected component,
  and consistent winding.
- Browser and Python body export both run deterministic closed-face orientation
  before STL writing; do not rely only on `trimesh.fix_normals` because the
  browser exporter cannot use it.
- Body rear caps must reuse the existing rear inner and rear offset rings.
  Duplicating those boundary vertices creates coincident open edges and visible
  corner slivers even when a post-processed mesh appears repaired.
- Do not revive the old trimmed outer-ring return path. It produced watertight
  meshes, but section diagnostics showed local clearance dropping below the
  intended `minimum_wall` near the mouth return.
- Do not offset the rear mouth return surface itself with averaged vertex
  normals. That produced a closed but folded mesh around the mouth rim.

Do not reintroduce the removed angular comparison exporter or a separate H/V
mesh topology.

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

## Current Dependencies

`trimesh` and `networkx` were installed in the project environment to support
mesh validation/normal repair in the zoned exporter.

## Caution

The main HornCAD project pipeline under `horncad/` is separate from the current
widget-to-STL exploratory workflow. Do not assume widget experiments should be
copied into `horncad/surface.py` until the geometry is stable and intentionally
specified.
