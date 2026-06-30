# HornCAD Roadmap

This roadmap defines implementation milestones. The goal is to keep each step
testable before moving into broader geometry or CAD export.

Terminology is defined in `docs/GLOSSARY.md`.

## M0 Project Shape

- Treat `examples/test_project/test_project.yaml` as the canonical example project file.
- Load and validate the project file.
- Apply defaults and emit a resolved configuration.
- Allow exactly one mouth dimension to be omitted. The missing `mouth.width` or
  `mouth.height` is derived from the specified principal dimension and the H/V
  profile settings by carrying the solved principal `S` to the other principal
  profile.
- Enforce current parameter bounds:
  - throat angle: `0..90`
  - `k`: `0..10`
  - `s`: `0..4`
  - `q`: `0.99..1.00`
  - `n`: `2..10`
- Preserve fixed output subdirectories:
  - `design_review/`
  - `cad/`

Acceptance criteria:

- The test project YAML parses.
- The resolved configuration can be generated without mutating the source project file.
- Invalid values produce clear validation errors.

## M1 Design Review

First real output target.

Implement enough core math to solve and inspect the principal horizontal and
vertical profiles as a boundary-fit diagnostic.

M1 uses boundary fit as its objective: solve `S` while holding `K`, `Q`, and
`N` fixed so each principal profile reaches its configured mouth boundary
distance. M1 does not validate area expansion; that begins when section geometry
exists.

Required behavior:

- Run:

  ```text
  python -m horncad.design_review examples/test_project/test_project.yaml
  ```

- Generate standard artifacts under `design_review/` beside the project file.
- Derive artifact filenames from the project file stem.
- For `examples/test_project/test_project.yaml`, generated files use the `test_project` prefix.
- Generate:
  - `{project_stem}_hv_profiles.png`
  - `{project_stem}_report.md`
  - `{project_stem}_resolved.yaml`

Report contents:

- authored parameters
- defaulted/resolved parameters
- unit conventions
- validation results
- computed values such as conic exit radius and mouth curvature radius
- principal-axis local lengths
- boundary fit objective and target boundary distances
- solved horizontal and vertical `S`
- final boundary fit error
- warnings and infeasible-condition messages
- generated artifact paths

Acceptance criteria:

- A combined horizontal/vertical profile plot is generated.
- The conic extension is visible as a distinct segment when configured.
- The report is sufficient to understand what was authored, what was derived, and what was solved.

## M2 First Full Inside Surface

Generate the first complete inside acoustic surface. Radial curves and section
slices are coupled and must be generated together because mouth shape, morph,
and area expansion all govern the same surface.

Default area-expansion target:

- Use a circular OS-SE reference horn.
- The reference horn uses polar-area-weighted horizontal/vertical acoustic values:
  - sample `coverage(p)` and `K(p)` around the mouth
  - weight each sample by `R_boundary(p)^2`
  - compute `coverage_ref` and `k_ref` from the weighted samples
  - `q_ref = q`
  - `n_ref = n`
- The reference circular horn is solved against an equivalent-area mouth.

Required behavior:

- Run:

  ```text
  python -m horncad.surface examples/test_project/test_project.yaml
  ```

- Generate standard artifacts under `surface_review/` beside the project file:
  - `{project_stem}_area_fit.png`
  - `{project_stem}_surface_report.md`
  - `{project_stem}_resolved.yaml`
- Compute the mouth boundary point, boundary distance, and mouth curvature setback for each radial direction.
- Interpolate horizontal and vertical coverage and `k` values over throat-radial angle `p`.
- Solve `S(p)` within configured bounds for boundary fit.
- Generate radial curves and cross-section slices from the same inside surface.
- Build circular-to-rectangular or circular-to-rounded-rectangular sections.
- Compute actual section area and area-expansion error against the mean circular reference.
- For curved mouths, compute area diagnostics only over closed constant-`z` sections where all radial curves still exist.
- Validate and report top-level `outputs.scope: quarter | half | full`; use the full symmetric surface internally for area diagnostics.
- Use `resolution.angular_segments` and `resolution.length_segments` as segment
  budgets, not equal-spacing requirements. Current `z` sampling is adaptive by
  curve/reference-radius change; angular radial-curve sampling is adaptive by
  mouth-boundary change, with explicit rounded-rectangle corner anchors.

Acceptance criteria:

- Radial curve data can be generated for all configured angular segments.
- Cross-section slice data can be generated across the horn length.
- Infeasible radial directions are reported clearly.
- Curves reach their target mouth boundary distances within tolerance.
- Area-expansion diagnostics are available.
- Section transitions are smooth enough for CAD lofting.

## M3 Area-Aware Refinement

Improve the first full inside surface using explicit area-expansion controls
and solver objectives. M3 is a candidate search, not a fallback chain that tries
`S` once and gives up.

Solver model:

- Mouth boundary fit is a hard constraint.
- Coverage remains fixed author intent.
- `K` is axis-specific and may move only when its horizontal or vertical bounds
  have span. K drift away from authored seeds is penalized and reported in the
  objective breakdown.
- `S(p)` is a dependent solve variable, recomputed for every candidate so each
  radial curve reaches the configured mouth boundary.
- The target area curve is the candidate's equivalent round OS-SE reference. If
  a candidate moves `Q` or `N`, its round reference target moves with it.
- Area expansion is the primary optimization objective.
- Area smoothness is checked with a log-area derivative-change diagnostic.
- Candidate variables are derived from bounds. `morph.rate`, `N`, `Q`, and
  horizontal/vertical `K` are searched only when their bounds have span.
- Global parameter bounds are hard safety rails. M3 derives effective search
  ranges from the actual design using mouth aspect ratio, H/V coverage delta,
  and initial area error.
- Candidates are rejected when configured hard constraints fail, such as solved
  `S(p)` outside `refinement.s_bounds`.
- `S(p)` is allowed to vary, but its expected span is scaled by mouth aspect
  ratio and H/V coverage delta. Excess `S` span and abrupt adjacent changes over
  throat-radial angle `p` are penalized and reported.
- Late morph timing is penalized and reported. The default search bound caps
  `morph.rate` at 4, and the objective discourages candidates whose 50% morph
  point lands after 85% of the horn length.
- Principal H/V profile slope changes are penalized and reported so a candidate
  cannot win by producing a sharp terminal kink.
- Principal H/V roundover contribution is reported as a core profile-shape
  diagnostic and compared to authored roundover targets/tolerances.

Required behavior:

- Preserve boundary fit and the inside acoustic surface as the authoritative geometry.
- Use area-expansion error from M2 to search allowed solve variables or morph controls.
- Keep additional solve variables explicit through seed/bounds; equal bounds
  mean fixed, bounds with span mean searchable.
- Support manual override of morph rate.
- Support manual override of morph start as a physical `z` position.
- Treat morph end as the mouth; do not expose it as a user parameter.
- Report which values were authored, defaulted, solved, or overridden.
- Report how many candidates were evaluated, how many were rejected, and whether
  the best candidate landed on search bounds.
- Report smoothness diagnostics so visible area-curve kinks are not hidden by a
  good average fit score.
- Report effective search ranges, `S(p)` behavior diagnostics, and H/V profile
  smoothness diagnostics.
- Report morph timing diagnostics: `z50`, `z90`, `z50` limit, excess `z50`, and
  timing objective weight.
- Report roundover contribution for the H/V master profiles.
- Support multiprocessing for candidate evaluation with `--workers`.
- Generate standard artifacts under `refine_review/` beside the project file:
  - `{project_stem}_refined_area_fit.png`
  - `{project_stem}_refined_hv_profiles.png`
  - `{project_stem}_refined_radial_profiles.png`
  - `{project_stem}_refined_radial_plan.png`
  - `{project_stem}_refined_principal_views.png`
  - `{project_stem}_refinement_report.md`
  - `{project_stem}_refined.yaml`

Acceptance criteria:

- Area-expansion error is reduced or clearly reported as infeasible.
- Boundary fit remains within tolerance after refinement.
- Any moved or overridden values are visible in the report.

## Design Flow: Length, S, And Roundover

HornCAD treats `length.max` as a fundamental design value, not as a hidden
variable that normal refinement silently moves. The user-facing tutorial flow
lives in `docs/design_flow.md`; roadmap work should preserve that separation.

Future length analysis should estimate the `length.max` required to meet a target
roundover contribution percent. It should initially be report-only rather than
mutating the project.

## M4 CAD 2D Output

Generate CAD-oriented 2D outputs under the fixed `cad/` directory.

Required behavior:

- `outputs.cad.formats.2d.profiles: true` enables profile curve output.
- `outputs.cad.formats.2d.slices: true` enables slice curve output.
- Do not require users to specify output filenames.

Acceptance criteria:

- Profile and slice outputs are generated only when their format flags are true.
- Output filenames are derived from the project file stem.
- Outputs are suitable for Fusion 360 / AutoCAD import or loft workflows.

## M5 CAD 3D / STL Output

Roadmap target for closed 3D assets.

Required behavior:

- `outputs.cad.formats.3d.stl: true` requests STL output.
- `outputs.cad.wall_thickness: 0.0` means face-only output, not a closed 3D asset.
- Nonzero `outputs.cad.wall_thickness` allows an outside surface to be generated.
- STL export requires:
  - inside acoustic surface
  - outside mechanical surface
  - throat closure
  - mouth rim closure
  - any required flange or mounting geometry

Acceptance criteria:

- STL output is rejected with a clear message when a closed mesh cannot be produced.
- Nonzero wall thickness does not modify the solved inside acoustic profile.
- Closed mesh output is valid for downstream 3D printing checks.
