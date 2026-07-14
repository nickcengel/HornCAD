# HornCAD Design Flow

This flow is for normal design work.

## 1. Author The Fixed Intent

Start with physical design intent:

- throat diameter and throat half-angle
- optional conic extension length and exit angle
- mouth width, height, shape, corner radius, and curvature sag/radius
- horizontal and vertical OS-SE coverage half-angles
- roundover contribution targets if used for reporting
- profile `K` and `N` values
- morph rate and morph start
- `surface.mode`, normally `slice`
- an initial `length.max`

`length.max` is a real design value. The solver should not move it silently.

In normal `slice` mode, HornCAD uses authored seed values directly and ignores
search bounds. `Q` is fixed at `0.995`. `S` is solved internally and is not
authored. If the H/V basis profiles or generated radial diagnostics require
negative `S`, output generation fails instead of silently reversing the terminal
roundover.

`profile` mode preserves the older radial-profile search path. In that mode,
bounds can move `morph.rate`, H/V `N`, H/V `K`, and mouth sag when sag bounds
have span.

## 2. Generate Output

Use:

```bash
python -m horncad.refine <project.yaml> --workers auto
```

HornCAD writes one project output directory beside the project file:

- `output/{project_stem}_area_fit.png`
- `output/{project_stem}_hv_profiles.png`
- `output/{project_stem}_inside_surface.stl`
- `output/{project_stem}_radial_plan.png`
- `output/{project_stem}_radial_profiles.png`
- `output/{project_stem}_report.md`

The inside-surface STL is generated from the superellipse slice surface with
terminal shape power 20 when `surface.mode: slice`. In `profile` mode, the STL
is generated from the radial profile surface.

## 3. Inspect Principal Profiles

The first question is whether the horizontal and vertical master profiles are
credible.

Use:

- `*_hv_profiles.png`
- `*_report.md`

Look at:

- H/V equation parameters
- solved `S`
- whether solved `S` is inside bounds
- roundover contribution %
- roundover length guidance

Interpretation:

- `S` is the low-level equation mechanism required to reach the boundary.
- roundover contribution describes how much radial growth is provided by the
  OS-SE terminal shaping term.
- if `S` is outside bounds, the profile is invalid under current constraints.
- if roundover contribution is too large, consider increasing `length.max`,
  changing profile seeds/bounds, or changing coverage.
- roundover length guidance estimates the `length.max` needed for the current
  profile settings to hit the authored roundover target exactly.

## 4. Inspect Area Behavior

After principal profiles look plausible, inspect expansion behavior.

Use:

- `*_area_fit.png`
- area and smoothness tables in `*_report.md`

This answers whether the output surface preserves the intended area expansion.

## 5. Inspect Radial Distribution Only When Needed

Use these when debugging sampling or mouth-boundary behavior:

- `*_radial_plan.png`
- `*_radial_profiles.png`

These are secondary diagnostics. They are not the first place to judge the
design.

## 6. Iterate Explicitly

Typical loop:

1. Author geometry and initial `length.max`.
2. Generate output.
3. Inspect H/V roundover contribution and internal solved `S`.
4. Check roundover length guidance.
5. Revise `length.max`, roundover targets, or profile seeds/bounds explicitly.
6. Inspect area behavior.
7. Inspect morph timing if area fit improved by delaying most of the morph.
8. Repeat until the principal profiles and area behavior are both acceptable.

Future length analysis should estimate the `length.max` required for a target
roundover contribution, but it should initially be report-only.

## Future Surface-Normal Diagnostics

Area and radial-profile plots can miss surface artifacts. A design can have
reasonable section area while the surface normals twist, bunch, or change exit
tangent abruptly. Future diagnostics should treat the horn as a parametric surface
`S(u, v)` and inspect normal-vector behavior:

- adjacent normal angle change along `z`
- adjacent normal angle change around each section
- second differences of normals to catch local lumps
- exit-normal deviation from the intended mouth tangent field
- corner-localized curvature and normal concentration

These diagnostics should be considered before using acoustic simulation results
as optimizer feedback, because they describe whether the generated surface is
geometrically coherent enough to be worth simulating.

## 7. Run Commands

Use `<project.yaml>` as the project file path placeholder.

Validate and print the resolved configuration:

```bash
python -m horncad.config <project.yaml>
```

Generate project output with all available CPU workers:

```bash
python -m horncad.refine <project.yaml> --workers auto
```

Run project output in a single process for debugging:

```bash
python -m horncad.refine <project.yaml> --workers 1
```

Candidate evaluation supports multiprocessing. Use `--workers auto`
for full runs and `--workers 1` for deterministic single-process debugging.
