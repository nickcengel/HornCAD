# HornCAD Output: 811b

## Solver Model

- Surface mode: slice
- Hard constraint: mouth boundary fit
- Fixed authored value: coverage
- Internal dependent solve: S(p), solved from authored profile values
- Fixed Q: 0.995
- Area reference: polar-area-weighted circular OS-SE reference using each design's H/V N values
- Output surface: H/V basis profiles lofted through superellipse slices
- Search variables from bounds: none; bounds are ignored in slice mode

## Sampling

| Item | Behavior |
| --- | --- |
| Surface sections | superellipse slices from H/V basis profiles |
| Angular radial curves | diagnostic only in slice mode |
| Profile z samples | adaptive by radial curve change |
| Section z samples | adaptive by target reference-radius change |
| Configured length segments | 100 |
| Configured angular segments | 96 |

## Selected Design

| Field | Value |
| --- | --- |
| Valid under reject_if | yes |
| Workers | not used |
| Morph rate | 1 |
| Horizontal N | 20 |
| Vertical N | 30 |
| Fixed Q | 0.995 |
| Mouth sag | 60 |
| Horizontal K | 1 |
| Vertical K | 3 |
| H/V S range | 0.328719..0.835517 |
| Shared section length | 280 mm |
| Area RMS log tolerance | 0.05 |
| Area tolerance met | no |
| Objective score | not used |
| Inside surface shape power | 20 |

## H/V Master Profiles

| Axis | Coverage deg | K | Local length mm | Profile length mm | Target boundary mm | Solved S | Boundary error mm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| horizontal | 45 | 1 | 280 | 200 | 210 | 0.328719 | 0 |
| vertical | 20 | 3 | 340 | 260 | 97.5 | 0.835517 | 0 |

## Roundover Diagnostics

| Axis | Roundover contribution % |
| --- | --- |
| horizontal | 3.71227 |
| vertical | 16.3542 |

## Area Fit

| Metric | Authored | Output |
| --- | --- | --- |
| Weighted RMS log area error | 0.0782725 | 0.0782725 |
| Throat third RMS log area error | 0.00750201 | 0.00750201 |
| Middle third RMS log area error | 0.0987688 | 0.0987688 |
| Mouth third RMS log area error | 0.164494 | 0.164494 |
| Area fit score | 0.894963 | 0.894963 |
| RMS log area error | 0.110973 | 0.110973 |
| RMS area error | 10.2839% | 10.2839% |
| Max area error |  | 16.5202% |
| Worst reference z |  | 254.425 mm |

## Smoothness

| Metric | Value |
| --- | --- |
| Max log-area slope change | 0.0173472 |
| Max log-area slope change limit | 0.01 |
| Smoothness check | warning |

## Radial Diagnostic S Behavior

| Metric | Value |
| --- | --- |
| S min | -0.474943 |
| S max | 3.00509 |
| S span | 3.48003 |
| Expected S span | 0.752778 |
| Excess S span | 2.72725 |
| RMS S deviation | 1.25157 |
| Max adjacent S change over p | 1.81438 |

## Radial Basis Coherence

| Metric | Value |
| --- | --- |
| RMS radial basis deviation | 0.0385055 |
| Max radial basis deviation | 0.172683 |
| RMS exit slope deviation | 4.87297 |

## Morph Timing

| Metric | Value |
| --- | --- |
| z50 | 50.4384% of length |
| z90 | 94.3269% of length |
| z50 limit | 85% of length |
| Excess z50 | 0% of length |

## Profile Smoothness

| Metric | Value |
| --- | --- |
| Max H/V profile slope change | 1.55154 |
| Max H/V profile slope change limit | 2 |
| Excess H/V profile slope change | 0 |
| Profile smoothness check | passed |

## Bound Notes

- Bounds are ignored in slice mode; authored seed values are used directly.

## Warnings And Infeasible Conditions

- `negative_s_termination`: p=40.5426: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=48.7552: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=59.6919: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=120.308: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=131.245: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=139.457: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=220.543: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=228.755: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=239.692: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=300.308: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=311.245: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.
- `negative_s_termination`: p=319.457: solved S is negative, reversing the terminal roundover direction
  Likely culprit: The interpolated OS-SE base curve overshoots the mouth boundary in this direction. Reduce the base expansion, increase the boundary distance, or increase the available profile length.

## Generated Artifacts

- Area fit: `examples/811b/output/811b_area_fit.png`
- H/V profiles: `examples/811b/output/811b_hv_profiles.png`
- Inside surface: `examples/811b/output/811b_inside_surface.stl`
- Radial plan: `examples/811b/output/811b_radial_plan.png`
- Radial profiles: `examples/811b/output/811b_radial_profiles.png`
- Report: `examples/811b/output/811b_report.md`
