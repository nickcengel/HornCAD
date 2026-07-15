# Native macOS BEM symmetry solver survey

Date: 2026-07-15

## Decision

NumCalc, the C++ numerical core of Mesh2HRTF, is the only surveyed open-source
candidate that clearly satisfies the important requirements simultaneously:

- native macOS execution;
- 3-D exterior Helmholtz acoustics;
- Burton--Miller treatment of fictitious resonances;
- single-level and multilevel FMM;
- prescribed velocity boundary conditions for radiation;
- two simultaneous Cartesian reflection planes; and
- a mesh containing only the independent quadrant.

It deserves a bounded Test4 adapter and benchmark before more effort is spent
modifying NGSolve. No production-backend decision has been made yet.

## NumCalc findings

Source inspected: Any2HRTF/Mesh2HRTF commit
`e45d0436a6fbeca3db13828cbae23ca109225be3` dated 2026-03-20.

The solver input accepts up to three Cartesian symmetry planes. Each can be
sound-hard/even or sound-soft/odd and may be offset from the origin. For our
horn the required entry is two sound-hard planes at `x=0` and `y=0`.

This is materially different from the current NGSolve experiment. NumCalc's
input mesh contains only the quadrant elements. Its conventional BEM assembly
loops over analytic reflections of each input element. Its FMM implementation
creates reflected cluster metadata that points back to the original quadrant
clusters, carries reflection directions and parity factors, and applies the
reflections inside both single-level and multilevel FMM. It therefore has one
unknown and one physical input element per quadrant panel, rather than building
a four-quadrant finite-element space first.

The current source compiled without modification using Apple Clang and the
repository Makefile. The resulting binary was confirmed as a native arm64
Mach-O executable. The build produced only portability/deprecation warnings.
It has no runtime dependency beyond the standard C++ runtime.

NumCalc uses constant triangular or planar-quadrilateral elements and
collocation, rather than NGSolve's continuous linear Galerkin space. It accepts
complex, frequency-dependent `VELO` boundary conditions and arbitrary
evaluation grids, so HornCAD can drive the throat and request the existing
far-field cuts without Blender or the Mesh2HRTF Python package.

NumCalc is single-threaded within one frequency. Its supported execution model
is parallel independent frequency processes, and its current manager includes
per-frequency RAM estimation and resource-aware scheduling. That maps well to
HornCAD's sweep architecture, but a ten-frequency sweep can use at most ten
cores unless we request more frequency samples.

The project is active, has numerical tests against analytic references, and is
licensed under EUPL 1.2. macOS compilation is documented, although upstream
states that macOS is not a formally supported/tested platform.

## Other candidates

| Candidate | Native symmetry result | Suitability |
|---|---|---|
| AcouSTO | Reduces collocation equations for one to three planes, but its input geometry must still contain every mirrored element. | Does not meet the quadrant-geometry objective; older MPI code and conventional dense integration make it a poor primary spike. |
| Bempp-cl | Complete Helmholtz operator algebra and CPU/GPU execution, but no documented reflection-symmetry operator. | Repeats the custom image-operator work already attempted. |
| NGSolve BEM | Periodic FE-space compression exists, but no native reflection-aware BEM/FMM operator. | Current path rebuilds source geometry and exposed an asymmetric-operator thread race. |
| Bembel | Fast Helmholtz IGABEM, but expects spline-patch geometry and has no documented acoustic mirror-plane interface. | Converting arbitrary HornCAD triangle meshes to analysis-suitable spline patches is a separate research project. |
| NiHu | General acoustic/FMM research toolbox; no verified native reflection-plane facility found. | Would require custom symmetry work without a clearer advantage over NGSolve. |
| FastBEM educational packages | Acoustic FMM packages exist, but the downloadable tools are Windows-only and non-commercial. | Rejected by the native-macOS requirement. |
| OpenBEM/AxiBEM | Has axisymmetric reductions, not the two rectangular reflection planes needed by Test4. | Geometry and loading do not satisfy the axisymmetric assumption. |

## Required NumCalc spike

The next work should remain deliberately bounded:

1. Export Test4's existing 500 Hz 6-EPW quadrant mesh directly to NumCalc node
   and element files, preserving outward normals and throat element IDs.
2. Generate an `NC.inp` with two hard symmetry planes, a uniform throat `VELO`
   condition normalized to 1 m3/s over the reconstructed full throat, and the
   same far-field observer directions used by the NGSolve comparison.
3. Run both NumCalc quadrant and NumCalc full-geometry cases at 500 Hz using
   conventional BEM if small enough, then ML-FMM. Compare pressure fields,
   iterations, peak RSS, and wall time. This isolates symmetry speedup within
   one solver before comparing different discretizations.
4. Compare the accepted NumCalc quadrant result with the accepted NGSolve full
   reference. Constant-element and linear-Galerkin meshes need a small
   convergence check; matching DOF counts is not sufficient.
5. Proceed to 5 or 8 kHz only if the 500 Hz symmetry benchmark is both accurate
   and measurably faster than NumCalc full geometry.

The spike should be rejected if NumCalc mirrors the source work so completely
that wall time fails to improve, if the quadrant/full solutions disagree, or if
constant elements require enough extra mesh density to erase the symmetry
savings.
