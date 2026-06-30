# HornCAD Design Flow

This flow is for normal design work. Comparison review is only for comparing
finished candidates.

## 1. Author The Fixed Intent

Start with physical design intent:

- throat diameter and throat half-angle
- optional conic extension length and exit angle
- mouth width, height, shape, corner radius, and curvature sag/radius
- horizontal and vertical OS-SE coverage half-angles
- roundover contribution targets/tolerances
- profile `K`, `Q`, and `N` seeds/bounds
- morph rate seed/bounds and morph start
- an initial `length.max`

`length.max` is a real design value. Normal refinement should not move it
silently.

When `K` bounds have span, K may participate in candidate search. K movement is
penalized against the authored seeds so it is a useful lever, not a free one.

## 2. Inspect Principal Profiles

The first question is whether the horizontal and vertical master profiles are
credible.

Use:

- `*_refined_principal_views.png`
- `*_refinement_report.md`

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

## 3. Inspect Area Behavior

After principal profiles look plausible, inspect expansion behavior.

Use:

- `*_refined_area_fit.png`
- area and smoothness tables in `*_refinement_report.md`

This answers whether the candidate surface preserves the intended area
expansion.

## 4. Inspect Radial Distribution Only When Needed

Use these when debugging sampling or mouth-boundary behavior:

- `*_refined_radial_plan.png`
- `*_refined_radial_profiles.png`

These are secondary diagnostics. They are not the first place to judge the
design.

## 5. Iterate Explicitly

Typical loop:

1. Author geometry and initial `length.max`.
2. Run refinement.
3. Inspect H/V roundover contribution and internal solved `S`.
4. Check roundover length guidance.
5. Revise `length.max`, roundover targets, or profile seeds/bounds explicitly.
6. Inspect area behavior.
7. Inspect morph timing if area fit improved by delaying most of the morph.
8. Repeat until the principal profiles and area behavior are both acceptable.

Future length analysis should estimate the `length.max` required for a target
roundover contribution, but it should initially be report-only.

## 6. Run Commands

Use `<project.yaml>` as the project file path placeholder.

Validate and print the resolved configuration:

```bash
python -m horncad.config <project.yaml>
```

Generate the M1 design review:

```bash
python -m horncad.design_review <project.yaml>
```

Generate the M3 refinement review with all available CPU workers:

```bash
python -m horncad.refine <project.yaml> --workers auto
```

Run refinement in a single process for debugging:

```bash
python -m horncad.refine <project.yaml> --workers 1
```

Run benchmark scorecards for one or more projects:

```bash
python -m horncad.benchmark <project.yaml> --workers auto -o scorecard.csv
```

Refinement candidate evaluation supports multiprocessing. Use `--workers auto`
for full runs and `--workers 1` for deterministic single-process debugging.
