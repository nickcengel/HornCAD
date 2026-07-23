# HornCAD Geometry Reference

This document describes the current browser app and Python STL exporter. Both implementations use the same design parameters and geometry model.

## Current Workflow

1. Open `app/browser/HornCAD.html` directly in a browser.
2. Adjust the acoustic profile, mouth, body, and sampling controls.
3. Choose `Surface` or `Body`, then export
   `HornCAD-<Mode>-<W>x<H>x<L>.YAML`.
4. Convert that configuration to STL with
   `python app/tools/export_horncad.py <project.YAML>`.

The browser previews the acoustic surface. The Python exporter produces either
that open surface or a printable body according to `body.stl_export_mode`.
`--mode surface` or `--mode body` overrides the YAML; `acoustic_surface` is a
backward-compatible alias for `surface`.

## Coordinates and Dimensions

- `z` follows the horn axis from the start of the OS-SE profile to the mouth.
- `x` is horizontal and `y` is vertical.
- Lengths are millimetres and authored angles are degrees.
- **Length** and `global.length` mean only the axial OSSE-profile length. They
  exclude the optional conical throat extension and mouth-sag distortion.
- **Profile-plus-extension length** is OSSE length + conical extension. It is an
  authored axial chain length, not necessarily the exported bounding-box depth.
- Mouth sag is implemented as a local axial setback. It changes the exported
  axial span; it is not an extra length that can be added algebraically.
- `global.measured_total_length` is informational and records the actual
  `max(z) - min(z)` span of the selected exported geometry. Surface/body mode,
  sag, the mouth rear offset, and other body features can make this differ from
  profile-plus-extension length. The exporter recomputes geometry rather than
  trusting this stored value.
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

Sag subtracts a progressively applied local setback from the profile coordinate.
It does not replace the acoustic basis solve or alter the meaning of OSSE
length. Use the measured exported span when physical depth matters.

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
  operating_intent: {}
  body: {}
  horizontal_basis: {}
  vertical_basis: {}
  section_modifier: {}
  view: {}
  export: {}
```

`global` contains acoustic dimensions and mouth curvature.
`operating_intent` contains intended H/V coverage and the analysis-frequency
band. `body` contains printable-shell and export-mode settings. The basis
sections contain construction coverage, `k`, `n`, and derived `s`.
`section_modifier` stores squareness and optional profile splines. `export`
controls STL sampling.

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
a profile above 0.52 before meshing or BEM. This excludes shallow, disc-like mouth
skirts whose useful horn expansion is concentrated immediately before the mouth;
the constraint is evaluated independently for the horizontal and vertical axes.

## Sampling and Output

The exporter adaptively distributes axial samples according to basis-profile
curvature. `export.stl_side_samples` is the nominal sample count per side, so a
basic ring contains four times that many vertices, with additional refinement
around squared-mouth corners.

The browser and Python exporter use this basename:

```text
HornCAD-<Mode>-<W>x<H>x<L>
```

where:

- `<Mode>` is exactly `Surface` or `Body`;
- `W` and `H` are the nominal mouth dimensions rounded to whole millimetres;
- `L` is `global.length`, the nominal OSSE-profile length rounded to a whole
  millimetre—not measured span and not profile-plus-extension length.

The browser writes `<basename>.YAML`; BEM-search export writes
`<basename>-BEM-search.YAML`. The Python exporter writes `<basename>.STL`.
Candidate-search artifacts intentionally use a different, analysis-specific
stem:

```text
<W>x<H>x<L>[_E<extension>]_<coverage>_K<K>_N<N>
```

for symmetric axes, or

```text
<W>x<H>x<L>[_E<extension>]_H<h-coverage>_K<h-K>_N<h-N>_V<v-coverage>_K<v-K>_N<v-N>
```

for asymmetric axes. Candidate geometry and reports append `_Surface.STL` and
`_Report.html`; `project.yaml` and `bem/responses.npz` keep fixed public names.

Without `--output-dir`, the Python exporter writes to `app/tools/output/`.
Use `--output-dir` to choose another directory. Accepted overrides are
`--mode surface`, `--mode acoustic_surface` (alias), and `--mode body`.

## Source of Truth

- `app/browser/HornCAD.html` defines the browser controls, preview, and YAML writer.
- `app/tools/export_horncad.py` defines command-line YAML loading and STL generation.
- `docs/reference/research/` contains background papers; it is not an implementation specification.

When behavior or schema changes, update both implementations, the project in
`examples/osse-400x280-reference/`, the root usage guide, and this reference.
