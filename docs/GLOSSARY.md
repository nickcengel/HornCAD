# HornCAD Glossary

This glossary is the source of truth for project terminology. When code,
reports, or roadmap text drift from these terms, update the wording.

## Coordinate Systems

### Axial Distance, `z`

Distance forward from the throat along the horn centerline.

### Throat-Radial Angle, `p`

Angle around the throat axis used to choose a radial OS-SE curve.

- `p = 0 deg`: horizontal principal direction
- `p = 90 deg`: vertical principal direction

This is not a mouth-curvature angle.

### Profile Radius, `r(z, p)`

Radial distance from the horn centerline for one OS-SE curve at axial distance
`z` and throat-radial angle `p`.

This is an OS-SE coordinate. It is not the same thing as
`mouth.curvature.radius`.

## Mouth Geometry

### Mouth Boundary

The final perimeter of the horn opening in the mouth plane or curved mouth
surface. For a rectangle or rounded rectangle, this is not a circle.

`mouth.shape.type: rectangle` uses exact flat sides. If
`mouth.shape.corner_radius` is greater than zero, the corners are exact circular
arcs.

`mouth.shape.type: rounded_rectangle` uses exact flat sides plus circular
corners when `mouth.shape.corner_radius` is numeric. When `corner_radius` is
`null`, it uses the configured superellipse approximation.

### Mouth Boundary Point

The `(x, y)` point where a radial curve at angle `p` meets the mouth boundary.

### Derived Mouth Dimension

If exactly one of `mouth.width` or `mouth.height` is omitted, HornCAD derives
the missing dimension before geometry generation.

Current derivation rule:

- solve `S` from the specified principal mouth dimension using that axis'
  coverage, `K`, `Q`, `N`, length, and setback
- use that same `S` on the other principal profile with the other axis'
  coverage and `K`
- compute the missing mouth dimension from the other profile endpoint

This is a principal-axis convenience rule. It is not an area-expansion solve.

### Boundary Distance, `R_boundary(p)`

Distance from the mouth center to the mouth boundary point along throat-radial
angle `p`.

For M1 principal-axis checks:

- horizontal boundary distance = `mouth.width / 2`
- vertical boundary distance = `mouth.height / 2`

This is not a mouth radius. It is a distance to a rectangular or
rounded-rectangular boundary along one direction.

### Mouth Curvature Radius

Mechanical radius of the cylindrical or spherical mouth surface, configured as
`mouth.curvature.radius` or derived from `mouth.curvature.sag`.

This term is reserved for mouth curvature only.

### Mouth Curvature Sag

User-authored depth of the curved mouth surface, configured as
`mouth.curvature.sag`.

Sag is a compact way to specify mouth curvature. It is not the same as local
curvature setback at every mouth boundary point.

### Mouth Curvature Setback

Derived axial depth consumed by curved mouth geometry at a specific mouth
boundary point. It reduces the local profile length available to a radial curve.

For a cylindrical mouth, setback varies primarily with horizontal coordinate
`x`. For a spherical mouth, setback varies with both `x` and `y`.

For a cylindrical mouth curved horizontally:

- curvature setback at `x = 0` is `0`
- curvature setback at `x = mouth.width / 2` is the configured sag
- horizontal principal profile uses the configured sag as its curvature setback
- vertical principal profile uses `0` curvature setback

## Profiles And Sections

### Principal Profile

One of the two M1 diagnostic OS-SE curves:

- horizontal principal profile
- vertical principal profile

M1 uses these to inspect boundary fitting and profile shape before generating
the full radial curve family.

### Radial Curve

An OS-SE-derived curve for one throat-radial angle `p`. M2 generates the full
family of radial curves.

### Section

A cross-section slice through the horn at some axial distance. M2 generates
sections together with radial curves because both describe the same inside
surface and area expansion.

For a curved mouth, constant-`z` sections are only closed while all radial curves
still exist at that `z`. M2 area diagnostics use this shared closed-section
interval and do not invent closed sections after some radial directions have
already reached the mouth.

### Output Scope

Top-level output control for generated geometry extent:

- `quarter`
- `half`
- `full`

This is validated and reported now. It will control emitted geometry scope when
curve/surface exports exist.

Area diagnostics still require a closed surface basis and are computed from the
full symmetric surface internally.

## Fitting And Validation

### Target

A known desired value supplied by configuration or derived from configuration.

Examples:

- mouth boundary distance at a given throat-radial angle
- target area curve for area-expansion checks
- configured bounds such as `osse.s_bounds`

A target is not necessarily an optimization objective by itself.

### Constraint

A rule that a valid project or solved value must satisfy.

Examples:

- `S` must stay within `osse.s_bounds`
- mouth curvature radius must be large enough for the configured mouth size
- conic extension must leave positive OS-SE profile length

### Solve Variable

A parameter the program is allowed to change to satisfy an objective.

Current M1 solve variable:

- `S`

Current M3 candidate variables:

- `morph.rate`
- `N`
- `Q`

Current fixed OS-SE parameter:

- `K`

Future milestones may allow additional solve variables, but only when the
objective supplies enough constraints to make the solution meaningful.

### Objective

The goal used by the solver to choose solve variable values.

Current M1 objective:

- boundary fit: choose `S` so a principal profile reaches its target boundary
  distance

Future objectives:

- area-expansion fit: choose allowed solve variables so generated sections track
  a target area curve
- smoothness or regularization: prefer values that avoid abrupt shape changes or
  stay near authored values

If two solve variables are free, one scalar objective such as boundary fit is
not enough. For example, solving both `S` and `K` against only boundary distance
is underconstrained because many pairs can hit the same boundary distance.

M3 treats mouth boundary fit as a hard constraint and area expansion as the
optimization objective. For every candidate `morph.rate`, `N`, and `Q`, it
recomputes `S(p)` so the candidate still reaches the mouth boundary.

M3 uses the candidate's equivalent round OS-SE reference as the target area
curve. If a candidate moves `Q` or `N`, its target round reference moves with
it. The objective is still meaningful because the candidate rectangular surface
is compared to the equivalent round surface, not to itself.

### Effective Search Range

Project-specific range used by M3 for candidate search. It is centered on the
authored/default value, widened by the design difficulty, and clipped to global
hard bounds.

Design difficulty currently uses:

- mouth aspect ratio delta
- H/V coverage delta
- initial RMS log area error

### `S(p)` Smoothness

How smoothly solved `S` changes around throat-radial angle `p`. M3 reports
overall `S` span, expected `S` span, excess span, RMS deviation, and max
adjacent `S` change. Expected `S` span scales with mouth aspect ratio and H/V
coverage delta.

### Boundary Fit

M1 operation that solves `S` so a principal profile reaches its configured mouth
boundary distance over the available local length.

Boundary fit is not area-expansion validation.

### Boundary Fit Error

Difference between the sampled final profile distance and the target boundary
distance.

### Area Expansion

Cross-sectional area growth along the horn. This is evaluated after section
geometry exists. Area expansion is not validated by M1 principal-profile plots.

For non-planar mouths, area diagnostics must state what section basis is used.
M2 uses closed constant-`z` sections over the shared radial-curve length.

### Area Smoothness

Derivative continuity of the area curve. M3 reports max log-area slope change
between adjacent section intervals so abrupt kinks are visible even when RMS
area error is low.

### Profile Smoothness

Derivative continuity of the principal H/V profiles. M3 reports max adjacent
profile slope change and penalizes excess change so endpoint kinks cannot hide
behind a good area score.

### Target Area Curve

The desired cross-sectional area as a function of axial distance.

Default from M2 onward:

- compute a circular OS-SE reference horn
- use mean horizontal/vertical acoustic values for the reference:
  - mean coverage
  - mean `K`
  - shared `Q`
  - shared `N`
- solve the circular reference against an equivalent-area mouth

The target area curve is the area of that reference horn:

```text
A_target(z) = pi * R_ref(z)^2
```

### Morph Rate

User-authored value controlling how aggressively sections transition from
circular near the throat toward the configured mouth boundary shape.

This affects area expansion and should be reported as authored or overridden,
not treated as cosmetic styling.

### Morph Start

Physical axial distance where circular-to-mouth-shape morphing begins.

This is a raw distance in the configured length unit, not a normalized fraction.

### Morph End

The mouth. It is not a user parameter.

## OS-SE Parameters

### `K`

Generalized OS profile parameter. Treat as authored acoustic character unless an
explicit future solve mode allows it to move.

### `S`

Termination flare amount. M1 solves `S` for boundary fit while holding `K`,
`Q`, and `N` fixed.

In M3, `S(p)` is recomputed for every candidate. It is not treated as the sole
area-expansion control.

### `Q`

Termination truncation coefficient. M3 may search this when `q` is listed in
`refinement.solve`.

### `N`

Superellipse termination exponent. M3 may search this when `n` is listed in
`refinement.solve`.
