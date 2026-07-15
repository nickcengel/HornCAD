# Test4 STL tessellation comparison

These files show both mesh layers used by the all-BEM pipeline. Every STL is
the **complete closed three-dimensional acoustic boundary**. The all-BEM model
does not use a single quadrant, symmetry planes, or a 2π baffle assumption; it
solves the full free-air obstacle in 4π space.

## Authored geometry tessellation

- `test4-authored-seed-12x12.stl`: former STL wire density, 4,128 triangles.
- `test4-authored-seed-12x16.stl`: selected STL wire density, 5,376 triangles.

These meshes encode HornCAD's surface geometry before wavelength remeshing.
The first number controls samples around each cross-section; the second controls
stations along the horn axis.

## Final acoustic meshes

- `test4-netgen-5khz-6epw-from-12x12.stl`: 31,002 triangles, maximum aspect
  ratio 32.62.
- `test4-netgen-5khz-6epw-from-12x16.stl`: 30,816 triangles, maximum aspect
  ratio 2.16.

Both final meshes enforce the same 5 kHz / six-elements-per-wavelength acoustic
edge requirement. Comparing this pair shows the effect of authored STL wire
density after Netgen remeshing.

The closed boundary includes the driven throat closure, internal horn surface,
mouth/lip, simplified exterior surface, and rear closure required to form the
free-air rigid obstacle. Face-domain labels are not representable in STL; the
solver's NPZ mesh artifact retains the rigid/throat labels separately.
