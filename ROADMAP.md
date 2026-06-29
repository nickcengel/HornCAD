# HornCAD Roadmap

This roadmap defines implementation milestones. The goal is to keep each step
testable before moving into broader geometry or CAD export.

## M0 Project Shape

- Treat `examples/test_project/test_project.yaml` as the canonical example project file.
- Load and validate the project file.
- Apply defaults and emit a resolved configuration.
- Enforce current parameter bounds:
  - throat angle: `0..90`
  - `k`: `0..10`
  - `s`: `0..2`
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
vertical profiles.

Required behavior:

- Run:

  ```text
  python -m horncad.design_review examples/test_project/test_project.yaml
  ```

- Generate standard artifacts under `design_review/`.
- Derive artifact filenames from the project file stem.
- For `examples/test_project/test_project.yaml`, generated files use the `test_project` prefix.
- Generate:
  - `{project_stem}_h_profile.png`
  - `{project_stem}_v_profile.png`
  - `{project_stem}_hv_profiles.png`
  - `{project_stem}_profile_data.csv`
  - `{project_stem}_report.md`
  - `{project_stem}_resolved.yaml`

Report contents:

- authored parameters
- defaulted/resolved parameters
- unit conventions
- validation results
- derived values such as `r0`, `alpha0`, conic exit radius, mouth half dimensions, and curvature radius
- principal-axis local lengths
- solved horizontal and vertical `S`
- final mouth radius error
- warnings and infeasible-condition messages
- generated artifact paths

Acceptance criteria:

- Horizontal and vertical profile plots are generated.
- The conic extension is visible as a distinct segment when configured.
- The report is sufficient to understand what was authored, what was derived, and what was solved.

## M2 Radial Curve Family

Generate the full family of radial curves around throat-radial angle `p`.

Required behavior:

- Interpolate horizontal and vertical coverage and `k` values over `p`.
- Compute local mouth target and mouth setback for each radial direction.
- Solve `S(p)` within configured bounds.
- Use `resolution.angular_segments` and `resolution.length_segments` as adaptive segment budgets, not equal-spacing requirements.

Acceptance criteria:

- Radial curve data can be generated for all configured angular segments.
- Infeasible radial directions are reported clearly.
- Curves reach their target mouth radii within tolerance.

## M3 Section Generation

Generate cross-section slices from the radial curve family.

Required behavior:

- Build circular-to-rectangular or circular-to-rounded-rectangular sections.
- Use the configured morph parameters.
- Preserve the inside acoustic profile as the authoritative surface.
- Compare actual section area against the selected area target.

Acceptance criteria:

- Cross-section slice data can be generated across the horn length.
- Area error diagnostics are available.
- Section transitions are smooth enough for CAD lofting.

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
