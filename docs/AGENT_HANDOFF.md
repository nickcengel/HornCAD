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
- square-boundary side samples are corner-biased, not uniform. Keep a high
  minimum side sample count because the mouth lip/outside-surface junction and
  high-squareness corners are sensitive to under-sampling,
- horn stations are adaptive in `z`: station spacing follows accumulated
  `max(abs(delta H radius), abs(delta V radius))`, not uniform distance along
  the horn. This keeps each slice closer to a constant amount of profile change
  and avoids wasting samples where the profiles change slowly. A smooth throat
  weighting term is added to the same cumulative metric so critical throat
  geometry gets extra stations without a hard sampling transition,
- mouth setback computed from one sag radius with H/V axis participation toggles,
- inner acoustic surface is wrapped with a radial outer offset, a mouth return cap,
  and a driver mount flange to form the printable body,
- the driver mount flange starts at the first horn ring. With a conic extension,
  that first ring is the beginning of the conic section; do not extend mount
  geometry behind the horn start in negative `z`,
- the outer horn wall starts at `horn_start_z + mount_flange_thickness`, not at
  the acoustic throat. If adaptive stations do not land exactly on that plane,
  interpolate the outer wall start ring there,
- on the `new-outside-surface` branch, station-local surface normals derive a
  smoothed scalar expansion for each slice point; that scalar is applied along
  stable radial directions. The outside field is station-preserving: it starts
  from that offset field, blends toward the authored yellow mouth-offset
  boundary as stations approach the mouth, and uses one blend value for each
  whole station/ring. The station blend must start early enough to turn the
  outside wall smoothly into the mouth boundary; delaying it with a high-power
  ramp makes the last segment snap backward into a pointed lip. Do not use
  per-sample wall clamps near the mouth; they preserve a distance number by
  creating corner pops and sliver artifacts. The yellow ring,
  `mouth_sag_radius - mouth_rear_offset`, is the outside surface's mouth
  boundary. Do not append projected or radial-offset rear return rings to the
  outside field,
- the mouth lip/return is only the face from the pink acoustic mouth ring to the
  yellow mouth-offset ring. Do not add a red-style cap/closure from a rear
  return ring to a separate outside terminal ring; that is the failed topology
  this branch is avoiding,
- resample near-mouth outside rings by path length before meshing. The station
  blend can create sub-millimeter strips just behind the yellow boundary; deleting
  those rings sharpens the wall into a chord, so redistribute that suffix instead,
- STL export mode can be `body` or `acoustic_surface`; body mode should be
  watertight, acoustic surface mode is intentionally open,
- mesh exported through `trimesh`,
- current body diagnostics should report watertight, one connected component,
  and consistent winding.
- Browser and Python body export both run deterministic closed-face orientation
  before STL writing; do not rely only on `trimesh.fix_normals` because the
  browser exporter cannot use it.
- Body cap rings must reuse the existing boundary rings at the rear mouth and
  outer horn intersection. Duplicating those boundary vertices creates coincident
  open edges and visible corner slivers even when a post-processed mesh appears
  repaired.
- The mouth cap may use intermediate rings only if their mouth-surface radius
  steps monotonically from the inner rear mouth radius down to the outer trim
  radius. Do not add intermediate rings that remain on the same return radius as
  the inner rear mouth; those caused visible corner poke-throughs.

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
