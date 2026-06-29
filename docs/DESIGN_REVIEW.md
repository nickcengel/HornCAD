# M1 Design Review Process

M1 solves only the principal horizontal and vertical profiles. It is a boundary
fit diagnostic, not an area-expansion validation.

## Solve Order

For each principal axis:

1. Keep authored `K`, `Q`, and `N` fixed.
2. Compute the target boundary distance from the configured mouth boundary.
3. Compute local profile length after mouth curvature setback and conic extension.
4. Use boundary fit as the objective: solve `S` directly from the OS-SE profile equation so the curve reaches that boundary distance.
5. Check the solved `S` against `osse.s_bounds`.

M1 does not automatically iterate `N` or `Q`. Those are advanced shape controls.
If `S` cannot fit the target within bounds, the design is reported as infeasible
when `validation.reject_if` includes `solved_s_outside_bounds`.

Boundary fit is a valid M1 objective because only one solve variable, `S`, is
free. If future solve modes allow `K`, `N`, or `Q` to move, they need additional
objectives or constraints, such as area-expansion fit or regularization toward
authored values.

## Feasibility Codes

Current structured issue codes:

- `mouth_curvature_radius_too_small`
- `conic_extension_length_gte_local_profile_length`
- `solved_s_outside_bounds`
- `plotted_s_clamped`

Codes listed in `validation.reject_if` stop design-review generation. Other
codes are written to the report as warnings.

## Likely Culprit Logic

If solved `S` is below the lower bound, the base OS profile already overshoots
the target boundary distance. Likely fixes are reducing coverage, reducing
throat or conic exit angle, reducing `K` if appropriate, or increasing the
mouth boundary dimension in that direction.

If solved `S` is above the upper bound, the target boundary distance is too
large for the current local length, coverage, `K`, `Q`, `N`, and `S` upper
bound. Likely fixes are increasing `length.max`, reducing mouth curvature sag,
increasing coverage, increasing the `S` upper bound, or reducing the mouth
boundary dimension in that direction.

See `docs/GLOSSARY.md` for formal definitions.

If the conic extension consumes the local profile length, reduce conic extension
length or mouth curvature sag, or increase `length.max`.

If mouth curvature radius is too small, increase `mouth.curvature.radius` or use
a smaller sag.
