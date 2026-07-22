# HornCAD Geometry Reference

This document describes the current browser app and Python STL exporter. Both implementations use the same design parameters and geometry model.

## Current Workflow

1. Open `app/browser/HornCAD.html` directly in a browser.
2. Adjust the acoustic profile, mouth, body, and sampling controls.
3. Export a `HornCAD-Surface-<WxHxL>.YAML` or `HornCAD-Body-<WxHxL>.YAML` file.
4. Convert that configuration to STL with `python app/tools/export_horncad.py <file.YAML>`.

The browser previews the acoustic surface. The Python exporter produces either that open surface or a printable body, according to `body.stl_export_mode` or the command-line `--mode` override.

## Coordinates and Dimensions

- `z` follows the horn axis from the start of the OS-SE profile to the mouth.
- `x` is horizontal and `y` is vertical.
- Lengths are millimetres and authored angles are degrees.
- `global.length` excludes the optional conical throat extension.
- `global.measured_total_length` is informational and includes that extension.
- Coverage and throat angles are half-angles.

## Acoustic Basis Profiles

HornCAD builds independent horizontal and vertical OS-SE basis profiles. For either axis, the generalized base radius is

```text
r_base(z) = r0 + z tan(throat_angle)
            + sqrt(k^2 r0^2 + z^2 tan(coverage)^2) - k r0
```

The termination term is

```text
t(z) = (L / q) [1 - (1 - (q z / L)^n)^(1/n)]
```

with `q = 0.995`. HornCAD solves `s` so the profile reaches its authored mouth half-dimension:

```text
r(z) = r_base(z) + s t(z)
```

The optional conical extension precedes this profile. Its exit radius becomes the effective throat radius used by both basis profiles.

## Cross Sections

Each cross section starts from the horizontal and vertical basis radii. A spline controls the transition from the circular throat to the squared mouth shape. Optional horizontal and vertical profile modifiers add local offsets, with separate splines controlling their axial strength.

The mouth surface is curved by `global.mouth_sag`. Horizontal and vertical sag can be enabled independently:

- both enabled: spherical curvature;
- horizontal only: horizontal cylindrical curvature;
- vertical only: vertical cylindrical curvature;
- neither enabled, or zero sag: flat mouth.

Sag changes the local axial position of a point; it does not replace the acoustic basis solve.

## Printable Body

Body export preserves the acoustic surface and constructs an outside mesh from these controls:

- throat start wall thickness;
- minimum wall thickness;
- mouth rear offset;
- mount diameter and flange thickness;
- mount fillet;
- screw-hole count, diameter, and pattern diameter.

The screw holes are subtracted from the completed body. Surface export omits all body and mounting geometry.

## YAML Layout

The current file format has one top-level key:

```yaml
horncad_config:
  type: HornCAD
  version: 2
  units: mm
  global: {}
  body: {}
  horizontal_basis: {}
  vertical_basis: {}
  section_modifier: {}
  view: {}
  export: {}
```

`global` contains acoustic dimensions and mouth curvature. `body` contains printable-shell and export-mode settings. The basis sections contain coverage, `k`, `n`, and the derived `s`. `section_modifier` stores the squareness and optional profile splines. `export` controls STL sampling.

Derived values such as `effective_throat_radius`, `measured_total_length`, and `solved_s` are included for inspection. The exporter recomputes geometry from the authored inputs.

Each horizontal and vertical basis also reports realized mouth-termination
geometry. `mouth_exit_angle_deg` is the wall tangent angle at the mouth.
`mouth_curvature_radius_mm` is the local radius of curvature of the analytic
axis profile at the mouth, and `normalized_mouth_curvature_radius` divides that
radius by the corresponding mouth half-dimension. These inexpensive derived
measurements describe the geometry produced jointly by S, N, K, coverage, and
length; they are preferable to interpreting N as an independent amount of
roundover.

`final_tenth_radial_growth_fraction` measures how much of the total throat-to-mouth
radius increase occurs in the final 10% of axial length. Candidate searches reject
a profile above 0.55 before meshing or BEM. This excludes shallow, disc-like mouth
skirts whose useful horn expansion is concentrated immediately before the mouth;
the constraint is evaluated independently for the horizontal and vertical axes.

## Sampling and Output

The exporter adaptively distributes axial samples according to basis-profile curvature. Each ring uses the configured side-sample budget, with additional attention around squared-mouth corners. Output names are derived from mode and nominal dimensions:

```text
HornCAD-Surface-<width>x<height>x<length>.STL
HornCAD-Body-<width>x<height>x<length>.STL
```

Use `--output-dir` to change the destination and `--mode surface|body` to override the YAML mode.

## Source of Truth

- `app/browser/HornCAD.html` defines the browser controls, preview, and YAML writer.
- `app/tools/export_horncad.py` defines command-line YAML loading and STL generation.
- `docs/reference/research/` contains background papers; it is not an implementation specification.

When behavior or schema changes, update both implementations, the project in
`examples/osse-400x280-reference/`, the root usage guide, and this reference.
