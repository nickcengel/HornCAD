# Agent Prompt: OS-SE Curved Rectangular Waveguide Generator

Terminology note: `docs/GLOSSARY.md` is the current source of truth for naming.
Older notes in this context file may use less precise early wording.

You are helping build a Python geometry generator for compression-driver waveguides / horns.

The project is inspired by ATH and the OS-SE waveguide method, but the goal is not to clone ATH. The goal is to generate curve and surface geometry suitable for Fusion 360.

The generator must support:

- OS-SE acoustic profile equations
- independent horizontal and vertical profile controls
- circular compression-driver throat
- smooth transition from circular throat to rectangular or rounded-rectangular mouth
- cylindrical mouth curvature
- spherical mouth curvature
- curve output that can be lofted into surfaces in CAD

The central challenge is that ATH primarily operates in a rotational/radial view around the throat axis, while this project needs a rectangular mouth with decoupled horizontal and vertical behavior and a mouth surface that may not lie on a plane.

---

## References

Use these as the main public references:

- ATH website: https://www.at-horns.eu/
- OS-SE paper: https://www.at-horns.eu/release/OS-SE%20Waveguide.pdf
- ATH 4.8.2 user guide: https://www.at-horns.eu/release/Ath-4.8.2-UserGuide.pdf
- ATH discussion thread: https://www.diyaudio.com/community/threads/acoustic-horn-design-the-easy-way-ath4.338806/

The most important mathematical reference is the OS-SE paper.

---

## Conceptual Model

Treat the horn as a family of radial OS-SE curves.

Each radial curve is defined by angle `p` around the throat axis.

For each `p`, the program should compute:

- local target mouth point
- local mouth radius from horn centerline
- local mouth setback caused by cylinder/sphere curvature
- local profile length `L(p)`
- interpolated acoustic parameters
- solved OS-SE parameter(s), usually `S(p)`
- a radial curve from throat to mouth

Then generate curves or sections that can be lofted into a smooth CAD surface.

---

## Two Coordinate Systems

Keep these two systems separate.

### 1. Throat-Radial Coordinate System

This is the OS-SE / ATH-like coordinate system.

- Angle: `p`
- Axis: around the compression-driver throat axis
- Used for: OS-SE curve generation, H/V interpolation, circular-to-rectangular transition

Typical orientation:

- `p = 0` or `180 deg`: horizontal axis
- `p = 90 deg` or `270 deg`: vertical axis

### 2. Mouth-Curvature Coordinate System

This is the mechanical mouth surface system.

- Used for cylindrical or spherical mouth curvature
- Used to compute mouth setback / sag
- Must not be confused with the OS-SE radial angle `p`

For a cylindrical mouth, setback depends primarily on horizontal coordinate `x`.

For a spherical mouth, setback depends on both `x` and `y`.

---

## UX / User-Specified Inputs

The user should not be asked to specify every variable independently. That will overdetermine the system.

The UX should separate:

- independent design inputs
- dependent solved values
- advanced tuning values

---

# Recommended User Inputs

## Throat

Required:

- `Throat.Diameter`
- `Throat.Angle`

Optional:

- `Throat.ConicExtensionLength` defaults to `0`
- `Throat.ConicExtensionExitAngle` defaults to `Throat.Angle`

Derived:

- `r0 = Throat.Diameter / 2`
- `alpha0 = Throat.Angle`
- `L_conic = Throat.ConicExtensionLength`, or `0` if omitted
- `alpha_exit = Throat.ConicExtensionExitAngle`, or `alpha0` if no separate exit angle is specified
- `r_conic_exit = r0 + L_conic * tan(alpha_exit)`

All authored angle inputs are half-angles. The OS-SE equations use those
half-angles directly.

If no conic extension is requested, use:

```text
L_conic = 0
alpha_exit = alpha0
r_conic_exit = r0
```

When a conic extension is requested, it is a straight conical section that starts at
the circular throat radius `r0` and expands at `alpha_exit` until its specified
length. The OS-SE section starts after this conic extension.

---

## Mouth Dimensions

Required:

- `Mouth.Width` or `Mouth.Height`

Derived:

- `a_mouth = Mouth.Width / 2`
- `b_mouth = Mouth.Height / 2`

If exactly one mouth dimension is omitted, derive it from the specified
principal dimension and the H/V profile settings. Solve `S` using the specified
axis' coverage, `K`, `Q`, `N`, length, and setback, then apply that same `S` to
the other principal profile with its own coverage and `K`. This is a
principal-axis setup convenience, not an area-expansion solve.

---

## Maximum Length

Required:

- `L_max`

This is the maximum centerline depth of the horn.

For curved mouths, local length becomes:

```text
L(p) = L_max - setback(p)
```

where `setback(p)` is caused by the mouth curvature.

---

## Horizontal Acoustic Profile

Required:

- `Coverage_H`
- `K_H`

Advanced / optional:

- `S_H_initial`
- `Q_H`
- `N_H`

---

## Vertical Acoustic Profile

Required:

- `Coverage_V`
- `K_V`

Advanced / optional:

- `S_V_initial`
- `Q_V`
- `N_V`

---

## Recommended Acoustic Parameter UX

Treat `K` as the primary acoustic character parameter.

Treat `S(p)` as the dimensional boundary-fitting variable.

Treat `Q` and `N` as advanced shape / termination controls.

M1/M2 behavior:

- user specifies `K_H`, `K_V`
- user specifies or accepts defaults for `Q` and `N`
- solver solves `S(p)` for each radial direction

M3 behavior:

- mouth boundary fit is a hard constraint
- coverage stays fixed as author intent
- `K` may move only when horizontal or vertical `K` bounds have span
- `S(p)` is recomputed for every candidate
- area expansion is the primary optimization objective
- the target area curve is the candidate's equivalent round OS-SE reference
- smoothness is checked with a log-area derivative-change diagnostic
- H/V profile smoothness is checked with an adjacent profile-slope diagnostic
- candidate ranges are scaled by mouth aspect ratio, H/V coverage delta, and
  initial area error, then clipped to global hard bounds
- `S(p)` span and adjacent changes over `p` are penalized and reported
- candidate search may move `morph.rate`, `N`, `Q`, and `K` when the
  corresponding bounds have span

Avoid moving `K`, `S`, `Q`, and `N` without enough constraints and good bounds.

---

## Parameter Bounds

Use these as validation bounds for user inputs and as initial numerical solve
bounds where applicable.

```text
Throat.Angle: 0 to 90 degrees
Throat.ConicExtensionExitAngle: 0 to 90 degrees
K: 0 to 10
S: 0 to 4
Q: 0.99 to 1.00
N: 2 to 10
```

Notes:

- `Throat.Angle` and `Throat.ConicExtensionExitAngle` are authored half-angles.
- Internal OS-SE equations use half-angles.
- Apply the same `K` bounds to `K_H`, `K_V`, and interpolated `K(p)`.
- Apply the same `S`, `Q`, and `N` bounds to solved per-angle values and any advanced user overrides.

---

## Mouth Curvature

Required:

- `Mouth.CurvatureType`

Allowed values:

- `flat`
- `cylinder`
- `sphere`

User should specify ONE of:

- `Mouth.Sag`
- `Mouth.CurvatureRadius`

Prefer sag as the UI input because it is easier to understand mechanically.

---

## Mouth Shape

Required:

- `Mouth.Shape`

Allowed values:

- `ellipse`
- `rounded_rectangle`
- `rectangle`

Recommended parameters:

- `Mouth.CornerRadius`
- `Mouth.ShapePower`

Use either an explicit rounded-rectangle curve or a superellipse approximation.

---

## Morph Parameters

Required or defaulted:

- `Morph.Start`
- `Morph.Rate`

Meaning:

- `Morph.Start`: physical axial distance where circular-to-rectangular morph begins
- `Morph.Rate`: easing exponent / transition speed
- Morph end is always the mouth and is not a user parameter.

Default proposal:

```text
Morph.Start = 0.0
Morph.Rate  = 2.0
```

But note: morph rate affects area expansion and therefore acoustic behavior. It should later be solved or optimized against target area expansion.

---

## CAD Wall / Outside Surface

The acoustic geometry is the inside profile.

For CAD solids or STL export, the program also needs an outside profile. The
outside profile is mechanically related to the inside profile but is not
acoustically important.

Optional:

- `outputs.cad.wall_thickness`

Meaning:

- `outputs.cad.wall_thickness` is the nominal distance from the inside acoustic surface to the outside mechanical surface.
- Treat this as a suggested wall thickness, not a hard acoustic parameter.
- A value of `0` means output the inside acoustic face only, not a closed 3D asset.
- The outside surface may need local adjustment for manufacturability, mounting features, driver flange geometry, or minimum wall constraints.
- STL export requires a nonzero wall thickness and should use the inside profile plus an outside profile derived from `outputs.cad.wall_thickness` to create a closed printable mesh.

Default proposal:

```text
outputs.cad.wall_thickness = 0.0
```

---

## Resolution

Required or defaulted:

- `Resolution.AngularSegments`
- `Resolution.LengthSegments`

Meaning:

- `Resolution.AngularSegments` is the target segment budget around throat-radial angle `p`.
- `Resolution.LengthSegments` is the target segment budget along each radial profile.
- These values do not imply equally spaced samples.
- Sampling density should increase where the represented curve changes faster.
- Smooth primitive regions, such as cylindrical mouth curvature, should not consume many points just because they are large.
- Curved or high-acceleration profile regions should receive more points because they need more resolution to describe accurately.

Current implementation:

- Profile and section `z` samples are adaptive by curve/reference-radius change.
- Angular radial-curve samples are adaptive by mouth-boundary change.
- Rounded-rectangle mouths force radial profiles at the start of the corner
  radius, through the radius, and at the end of the corner radius.
- Keep the config names as segment budgets so sampling can change without
  changing project shape.

Default proposal:

```text
Resolution.AngularSegments = 96
Resolution.LengthSegments = 100
```

---

# Dependent / Solved Variables

The program should compute these:

- `r0`
- `alpha0`
- `L_conic`
- `alpha_exit`
- `r_conic_exit`
- remaining OS-SE profile length after conic extension
- `L(p)`
- `setback(p)`
- curvature radius if user specified sag
- sag if user specified radius
- target mouth point for each `p`
- target radial mouth distance `R_mouth(p)`
- `Coverage(p)`
- `K(p)`
- `S(p)`
- OS-SE radial curve for each `p`
- section shape exponent or corner-radius schedule
- cross-sectional area `A(z)`
- optional outside surface derived from inside profile and `outputs.cad.wall_thickness`
- generated points / curves / splines

---

# OS-SE Equations

The OS-SE paper defines a generalized oblate spheroidal profile plus a smooth superellipse termination term.

Use the coordinate system:

```text
[x, y, z] = [r, phi] at z
```

where:

- `z` is axial distance from throat
- `r` is radial distance from the horn axis
- `phi` is angle around the horn axis

A general horn surface may be represented as:

```text
r = r(z, phi)
```

---

## Pure OS Waveguide

For zero throat opening angle:

```text
r_OS(z) = sqrt(r0^2 + z^2 * tan(alpha)^2)
```

Where:

- `r0` = throat radius
- `alpha` = nominal coverage half-angle

---

## OS Waveguide With Throat Opening Angle

```text
r_OS(z) = sqrt(r0^2 + 2*r0*z*tan(alpha0) + z^2*tan(alpha)^2)
```

Where:

- `alpha0` = throat opening half-angle

---

## Generalized OS Waveguide

```text
r_GOS(z) = sqrt(k^2*r0^2 + 2*k*r0*z*tan(alpha0) + z^2*tan(alpha)^2) + r0*(1-k)
```

Where:

- `k` = throat expansion factor

Important behavior:

```text
k = 1 -> pure OS profile
k = 0 -> conical profile: r_GOS(z) = r0 + z*tan(alpha)
```

---

## Optional Conic Throat Extension

The generator may include a user-specified conic extension before the OS-SE
section.

This is useful when the compression driver or adapter needs a straight conical
transition immediately after the throat.

User inputs:

- `L_conic` = conic extension length
- `Throat.ConicExtensionExitAngle` = conic extension exit half-angle `alpha_exit`

The conic extension starts at the throat:

```text
r_conic(0) = r0
```

The conic radius is:

```text
r_conic(z) = r0 + z*tan(alpha_exit)
```

Valid domain:

```text
0 <= z <= L_conic
```

The radius where the OS-SE section starts is:

```text
r1 = r_conic_exit = r0 + L_conic*tan(alpha_exit)
```

For the following OS-SE section, use:

```text
r0_profile = r1
alpha0_profile = alpha_exit
```

and evaluate OS-SE in a local coordinate:

```text
z_profile = z_global - L_conic
```

The OS-SE profile length is reduced by the conic length:

```text
L_profile(p) = L(p) - L_conic
```

Feasibility requirement:

```text
L_profile(p) > 0
```

If `L_conic = 0`, this reduces to the normal OS-SE case.

---

## Superellipse Termination Term

The superellipse quadrant form is:

```text
(z/a)^n + (r/b)^n = 1
```

A usable function form is:

```text
r_SE(z) = b * (1 - (1 - z^n/a^n)^(1/n))
```

With:

```text
a = L
b = s*L
```

This becomes:

```text
r_SE(z) = s*L * (1 - (1 - z^n/L^n)^(1/n))
```

ATH / OS-SE introduces a truncation coefficient `q`:

```text
r_TERM(z) = (s*L/q) * (1 - (1 - (q*z/L)^n)^(1/n))
```

Where:

- `s` = termination flare amount
- `q` = truncation coefficient, typically near `0.99` to `1.00`
- `n` = superellipse exponent
- `L` = profile length

Interpretation:

- `s = 0` means no added termination flare
- larger `s` increases mouth radius
- larger `n` preserves more of the underlying OS profile and concentrates termination closer to the mouth
- `q` trims the final part of the quadrant

---

## Full OS-SE Profile

```text
r_OSSE(z) = r_GOS(z) + r_TERM(z)
```

Expanded:

```text
r_OSSE(z) = sqrt(k^2*r0^2 + 2*k*r0*z*tan(alpha0) + z^2*tan(alpha)^2)
            + r0*(1-k)
            + (s*L/q) * (1 - (1 - (q*z/L)^n)^(1/n))
```

Valid domain:

```text
0 <= z <= L
```

---

# Important Implementation Note: Degrees vs Radians

UI values may be in degrees.

Python math functions use radians.

Convert:

```python
alpha_rad = radians(alpha_deg)
alpha0_rad = radians(alpha0_deg)
```

---

# ATH Morph Equation

The OS-SE paper describes ATH morphing as a transformation toward a target mouth outline.

For `z < zf`:

```text
r_m(z, phi) = r(z, phi)
```

For `z >= zf`:

```text
r_m(z, phi) = r(z, phi) + ((z - zf) / (L - zf))^gamma * (r_M(phi) - r(L, phi))
```

Where:

- `zf` = fixed part of the original shape
- `r_M(phi)` = target mouth outline radius
- `gamma` = morph rate, `gamma >= 1`

Properties:

```text
r_m(0, phi) = r0
r_m(L, phi) = r_M(phi)
```

This is useful but not sufficient for this project because our morph changes enclosed area and we must control area expansion.

---

# Project Enhancement: Curved Rectangular Mouth

ATH morphing is not enough for this project because the mouth is:

- rectangular or rounded-rectangular
- potentially non-planar
- cylindrical or spherical
- generated from decoupled H/V profiles

We need an enhanced morph system.

---

## Rectangular / Rounded-Rectangular Mouth Boundary

Supported implementations:

- exact rectangle
- exact rounded rectangle when `corner_radius` is numeric
- superellipse approximation when `rounded_rectangle.corner_radius` is `null`

```text
abs(x/a)^m + abs(y/b)^m = 1
```

Where:

- `a = local half-width`
- `b = local half-height`
- `m = shape power`

Examples:

```text
m = 2       -> ellipse
m = 4..8    -> rounded rectangle
m -> large  -> near rectangle
```

Use this because it is smooth and easy to sample.

Exact rounded rectangles use flat side segments and circular corner arcs.

---

## Superellipse Radius From Angle

For a superellipse centered at origin:

```text
abs(x/a)^m + abs(y/b)^m = 1
```

The radial distance from center at angle `p` is:

```text
R_boundary(p) = 1 / ((abs(cos(p))/a)^m + (abs(sin(p))/b)^m)^(1/m)
```

Then:

```text
x = R_boundary(p) * cos(p)
y = R_boundary(p) * sin(p)
```

This gives the target mouth point for each radial curve.

---

## Area of Superellipse

The exact area of a superellipse is:

```text
A = 4*a*b*Gamma(1 + 1/m)^2 / Gamma(1 + 2/m)
```

Special cases:

```text
m = 2 -> A = pi*a*b
m -> infinity -> A = 4*a*b
```

Use this for area-expansion control.

---

# Area Expansion Target

The morph from circular throat to rectangular mouth is not cosmetic.

It changes cross-sectional area.

Therefore it affects acoustic expansion.

Default target:

Use a circular OS-SE horn as the acoustic area reference. The reference horn
uses polar-area-weighted horizontal/vertical acoustic values:

```text
coverage_ref = sum(coverage(p) * R_boundary(p)^2) / sum(R_boundary(p)^2)
k_ref        = sum(K(p) * R_boundary(p)^2) / sum(R_boundary(p)^2)
q_ref        = q
n_ref        = n
```

Solve the circular reference against an equivalent-area mouth.

```text
A_target(z) = pi * R_ref_OSSE(z)^2
```

Where `R_ref_OSSE(z)` is a reference round OS-SE profile.

The actual rectangular section should satisfy approximately:

```text
A_actual(z) ~= A_target(z)
```

The goal is not necessarily constant first derivative or zero second derivative.

The goal is:

- smooth area expansion
- no sudden area acceleration
- no sudden area deceleration
- smooth first derivative
- smooth second derivative

---

# Choosing the Reference Round OS-SE Profile

Use the polar-area-weighted circular reference.

Choose reference round mouth radius:

```text
R_ref_mouth = sqrt(A_mouth / pi)
```

Then solve or select reference OS-SE parameters so the round horn reaches this area at `L_max`.

Manual overrides may be added for:

- morph rate
- morph start as a physical `z` position

---

# Cylindrical Mouth Curvature

For a cylindrical mouth whose curvature is horizontal:

```text
z_offset(x) = R - sqrt(R^2 - x^2)
```

Where:

- `x` = horizontal coordinate at mouth
- `R` = cylinder radius

If user specifies sag at side:

```text
R = (x_max^2 + sag^2) / (2*sag)
```

Where:

```text
x_max = Mouth.Width / 2
```

Local length:

```text
L(p) = L_max - z_offset(x_mouth(p))
```

---

# Spherical Mouth Curvature

For a spherical mouth:

```text
z_offset(x,y) = R - sqrt(R^2 - x^2 - y^2)
```

If user specifies sag at corner:

```text
rho_max = sqrt((Mouth.Width/2)^2 + (Mouth.Height/2)^2)
R = (rho_max^2 + sag^2) / (2*sag)
```

Local length:

```text
L(p) = L_max - z_offset(x_mouth(p), y_mouth(p))
```

---

# Radial Profile Generation

For each angle `p`:

1. Compute final mouth boundary point:

```text
R_mouth(p)
x_mouth(p) = R_mouth(p) * cos(p)
y_mouth(p) = R_mouth(p) * sin(p)
```

2. Compute mouth setback:

```text
setback(p)
```

3. Compute local length:

```text
L(p) = L_max - setback(p)
```

4. Apply optional conic extension:

```text
L_profile(p) = L(p) - L_conic
r0_profile = r0 + L_conic*tan(alpha_exit)
alpha0_profile = alpha_exit
```

If `L_profile(p) <= 0`, report an infeasible geometry.

5. Interpolate acoustic parameters:

```text
K(p)        = K_V + (K_H - K_V) * cos(p)^2
Coverage(p) = Coverage_V + (Coverage_H - Coverage_V) * cos(p)^2
```

6. Usually hold:

```text
Q(p) = Q_default
N(p) = N_default
```

7. Solve:

```text
S(p)
```

such that:

```text
r_OSSE(L_profile(p), L_profile(p), r0_profile, alpha0_profile, Coverage(p), K(p), S(p), Q, N) = R_mouth(p)
```

8. Generate curve samples.

Conic extension samples:

```text
z_i from 0 to L_conic
r_i = r0 + z_i*tan(alpha_exit)
```

OS-SE samples:

```text
z_profile_i from 0 to L_profile(p)
r_i = r_OSSE(z_profile_i, L_profile(p), r0_profile, alpha0_profile, ...)
z_global_i = L_conic + z_profile_i
```

9. Convert to 3D point along radial direction:

```text
x_i = r_i * cos(p)
y_i = r_i * sin(p)
z_i = z_global_i
```

Then apply any cross-section morph / area correction as needed.

---

# Numerical Methods

Forward OS-SE evaluation is closed-form.

But inverse fitting is generally numerical.

Use numerical solving or candidate search for:

- `S(p)`
- optional `Q` or `N` if area-aware refinement enables them
- morph exponent / shape power if matching target area
- common-length reconciliation

Recommended methods:

- bisection for robust bounded solve
- secant method for faster solve
- Newton-Raphson only if derivative is reliable

Recommended first implementation:

```text
Use bisection with sane bounds for S.
```

Because this is predictable and stable.

---

# Suggested Solve Bounds

Start with conservative bounds:

```text
S_min = 0.0
S_max = 2.0
```

If no solution is bracketed within `0 <= S <= 2`, report that the design is
infeasible or ask the user to relax dimensions, length, coverage, or other fixed
parameters. Do not silently expand beyond the configured parameter bounds.

Report infeasible conditions clearly.

---

# Infeasible / Overdetermined Designs

The system can be overconstrained if the user fixes too many values.

Do not let the user independently fix all of these without solving/relaxing something:

- `L_max`
- `Mouth.Width`
- `Mouth.Height`
- `Coverage_H`
- `Coverage_V`
- `K_H`
- `K_V`
- `S_H`
- `S_V`
- `Q`
- `N`

Recommended UX:

- user specifies dimensions and primary acoustic controls
- program solves fitting parameters
- advanced mode allows locking more variables
- if locked variables make the design impossible, report why

---

# Recommended First Implementation Scope

Implement in this order.

## Phase 1: Core Math

- OS-SE forward profile
- cylinder setback
- sphere setback
- superellipse boundary
- superellipse area

## Phase 1 Output Target: Design Review Bundle

Before CAD export, the first useful output should be a direct Python-generated
design review bundle.

The bundle should validate the project shape, solve the principal horizontal and
vertical profiles, and write both graphics and a text/markdown report.

Recommended command shape:

```text
python -m horncad.design_review examples/test_project/test_project.yaml
```

Output directory:

```text
design_review
```

This directory name is fixed. The user should not need to configure it.

Recommended artifacts:

```text
design_review/
  {project_stem}_hv_profiles.png
  {project_stem}_report.md
  {project_stem}_resolved.yaml
```

Where `project_stem` is derived from the input project file name without its
extension. For example, `examples/test_project/test_project.yaml` should
produce filenames prefixed with `test_project`.

The user should not need to specify output filenames for standard artifacts.
The project file controls what artifact types are enabled; the implementation
derives filenames.

Plot requirements:

- `{project_stem}_hv_profiles.png`: horizontal and vertical profiles overlaid for comparison.
- Plot the conic throat extension separately from the OS-SE section when `L_conic > 0`.
- Mark throat radius, conic exit radius, mouth target radius, and local profile length.
- Keep the plots direct and inspectable; this is a validation artifact, not a presentation rendering.

Project report requirements:

- authored configuration values
- normalized/resolved configuration values after defaults are applied
- unit conventions
- validation bounds and pass/fail status
- derived values such as `r0`, `alpha0`, `L_conic`, `r_conic_exit`, mouth half-dimensions, and curvature radius
- principal-axis local lengths after mouth setback
- solved horizontal and vertical `S` values
- final horizontal and vertical mouth radius error
- warnings and infeasible-condition messages
- output artifact paths

This should be the first implementation target because it exercises config
loading, validation, core math, solving, and output generation without requiring
full radial surfaces or CAD export.

## Phase 2: Principal Axis Curves

Generate:

- horizontal OS-SE curve
- vertical OS-SE curve

Solve `S_H` and `S_V`.

## Phase 3: First Full Inside Surface

Generate radial curves and cross-section slices together for many `p` values.

Interpolate `K` and `Coverage`.

Solve `S(p)`.

Compare actual section area to the polar-area-weighted circular reference target.

## Phase 4: Area-Aware Refinement

Search allowed solve variables or morph controls to reduce area error. For every
candidate, recompute `S(p)` so mouth boundary fit remains a hard constraint.
Compare each candidate against its equivalent round OS-SE reference. Manual
overrides may specify morph rate and morph start `z`.

## Phase 5: CAD Export

Export one or more formats:

- `formats.2d.profiles`: principal and radial profile curves
- `formats.2d.slices`: cross-section slice curves
- `formats.3d.stl`: closed STL mesh when wall thickness is nonzero

There is no top-level `outputs.cad.enabled` flag. CAD output is enabled by
setting individual format flags to `true` or disabled by setting them to `false`.

Roadmap export:

- STL closed mesh for 3D printing

STL export requires more than the acoustic inside surface. It needs a closed
solid mesh made from:

- inside acoustic profile
- outside mechanical profile derived from `outputs.cad.wall_thickness`
- throat and mouth rim closures
- any required flange or mounting geometry

---

# Geometry Outputs

The program should be able to output:

1. design-review plots and project report
2. radial curves
3. cross-section curves
4. mouth boundary curve
5. throat boundary curve
6. surface mesh preview
7. CAD-importable curve data
8. roadmap: STL-ready closed mesh after outside-surface generation is implemented

Recommended initial output:

```text
design_review/
  {project_stem}_hv_profiles.png
  {project_stem}_report.md
  {project_stem}_resolved.yaml
```

Later geometry output:

```text
cad/
  profile curves
  slice curves
  waveguide.stl
```

The `cad/` directory name is fixed. The user enables CAD artifacts through
format flags, not by choosing output paths.

---

# Validation / Debug Outputs

Generate plots and report diagnostics for:

- horizontal principal profile
- vertical principal profile
- `L(p)`
- `S(p)`
- `K(p)`
- `Coverage(p)`
- `R_mouth(p)`
- `Area_actual(z)`
- `Area_target(z)`
- `Area_error(z)`

Generate a project report containing:

- all authored parameters from the input config
- all defaulted parameters
- all calculated parameters used by the solve
- validation bounds and pass/fail results
- warnings and infeasible-condition messages
- artifact paths for generated outputs

This will make it much easier to debug geometry and acoustic continuity.

---

# Practical Defaults

Use these as initial defaults only:

```text
Q = 0.995
N = 2.0 to 4.0
Morph.Start = 0.0
Morph.Rate = 2.0
Mouth.ShapePower = 6.0
Resolution.AngularSegments = 96
Resolution.LengthSegments = 100
```

Do not treat these as final acoustic recommendations.

---

# Important Notes For the Coding Agent

1. Do not mix the cylinder/sphere curvature angle with the throat-radial angle `p`.

2. The OS-SE radial family defines acoustic expansion.

3. The mouth curvature defines only final mouth setback and local length.

4. The optional conic throat extension consumes part of the local length before the OS-SE section starts.

5. The circular-to-rectangular morph changes area and must be treated as acoustically meaningful.

6. Treat `S(p)` as a dependent boundary-fit solve, not the whole area strategy.

7. Keep `K` as a user-controlled acoustic parameter.

8. Keep `Q` and `N` fixed unless area-aware refinement explicitly enables them.

9. Use closed-form equations for forward geometry.

10. Use numerical methods for inverse fitting.

11. Provide feasibility diagnostics instead of silently producing bad geometry.

12. Reject or warn on any radial direction where `L_conic >= L(p)`.

13. Treat the inside profile as the authoritative acoustic surface. Wall thickness
    and outside-surface generation must not change the solved inside profile.

---

# Minimal Function List

Implement these functions first:

```python
def conic_radius(z, r0, alpha_exit):
    pass


def osse_radius(z, L, r0, alpha0, alpha, k, s, q, n):
    pass


def cylinder_radius_from_sag(x_max, sag):
    pass


def cylinder_setback(x, R):
    pass


def sphere_radius_from_sag(rho_max, sag):
    pass


def sphere_setback(x, y, R):
    pass


def superellipse_radius_at_angle(p, a, b, m):
    pass


def superellipse_area(a, b, m):
    pass


def interpolate_hv(p, horizontal_value, vertical_value):
    # vertical + (horizontal - vertical) * cos(p)^2
    pass


def solve_s_for_target_radius(target_radius, L, r0, alpha0, alpha, k, q, n):
    pass


def generate_radial_curve(p, config):
    pass


def generate_sections(config):
    pass
```

---

# Minimal Configuration Example

Example input configuration:

See also:

- `docs/design_flow.md` for the recommended normal design workflow and output-reading order.
- `examples/test_project/test_project.yaml` for a fuller project-shape sketch with validation and output sections.

```yaml
throat:
  diameter: 25.4
  angle: 5.0
  conic_extension_length: 0.0
  conic_extension_exit_angle: 5.0

mouth:
  width: 380.0
  height: 235.0
  shape: rounded_rectangle
  shape_power: 6.0
  curvature_type: cylinder
  sag: 30.0

length:
  max: 150.0

profiles:
  coverage:
    horizontal: 50.0
    vertical: 31.0
  roundover:
    horizontal:
      target_percent: 30.0
      tolerance_percent: 5.0
    vertical:
      target_percent: 30.0
      tolerance_percent: 5.0
  k:
    horizontal:
      seed: 1.0
      bounds: [1.0, 1.0]
    vertical:
      seed: 1.0
      bounds: [1.0, 1.0]
  q:
    seed: 0.995
    bounds: [0.99, 1.0]
  n:
    seed: 3.0
    bounds: [2.0, 10.0]

morph:
  start: 0.0
  rate:
    seed: 2.0
    bounds: [0.25, 4.0]

refinement:
  s_bounds: [0.0, 4.0]

resolution:
  angular_segments: 96
  length_segments: 100

outputs:
  design_review:
    plots:
      hv_profiles: true
    report: true
    resolved_config: true
  cad:
    wall_thickness: 0.0
    formats:
      2d:
        profiles: true
        slices: true
      3d:
        stl: false
```

---

# Final Success Criteria

The program succeeds when it can:

1. Generate a circular throat.
2. Generate a rectangular or rounded-rectangular mouth.
3. Place the mouth on a flat, cylindrical, or spherical surface.
4. Generate smooth radial OS-SE-derived curves.
5. Solve dependent variables without overconstraining the user.
6. Preserve a smooth area expansion close to a round OS-SE reference.
7. Export design-review plots/reports first, then CAD profile/slice outputs, with STL closed-mesh export identified as a roadmap feature requiring nonzero `outputs.cad.wall_thickness` and outside-surface generation.
