# Expand HornCAD’s BEM Process into a Validated Comparison Pipeline

  ## Summary

  Turn the current 3D BEM prototype into a reproducible acoustic-analysis pipeline suitable for geometry comparisons and
  eventual optimization. The workflow will use a uniform piston throat source, wavelength-controlled meshing, complex mouth-
  field observations, ideal-aperture and full-exterior radiation modes, convergence checks, resumable sweeps, and machine-
  readable metrics.

  The geometry origin remains the throat center. Radiation observations use the mouth center as their reference origin. Driver
  lumped-element modeling is explicitly out of scope.

  ## Key Changes

  ### 1. Formalize the acoustic model

  - Represent the throat source as an explicit circular cap moving uniformly in (+z).
  - Author the excitation as piston velocity or volume velocity and convert it to the complex Neumann boundary condition;
    default to unit volume velocity for calibrated complex results.

  - Keep all other physical surfaces rigid.
  - Record source area, normal direction, velocity, volume velocity, medium properties, coordinate origins, and boundary
    assignments in the run manifest.

  - Replace the resonance-sensitive single-layer formulation with a resonance-safe combined-field exterior Neumann formulation,
    validated against analytic cases.

  - Keep the exterior geometry physically meaningful and separate it from artificial observer surfaces.

  ### 2. Introduce frequency-aware acoustic meshing

  - Replace side_samples and stations as the primary public controls with:
      - maximum_frequency_hz
      - elements_per_wavelength
      - optional geometry-curvature tolerance

  - Default production resolution to 8 elements per wavelength:
    [
    h_\text{target}=c/(8f_\text{max})
    ]

  - Provide named tiers:
      - Preview: 6 elements/wavelength
      - Production: 8 elements/wavelength
      - Verification: 10 and 12 elements/wavelength

  - Refine by actual triangle edge length, not ring counts alone, with additional refinement at the throat, mouth rim, corners,
    rapid curvature, and morph transitions.

  - Eliminate boolean-generated sliver triangles and enforce limits for maximum edge, aspect ratio, minimum angle, orientation,
    watertightness, and connectedness.

  - Fail before solving if any acoustically relevant edge exceeds the selected wavelength limit; do not accept percentile-only
    compliance.

  - Emit a mesh report containing triangle/DOF counts, edge statistics, quality failures, minimum wavelength, supported maximum
    frequency, and estimated solve cost.

  - Use one mesh sized for the sweep’s highest frequency so comparisons across frequency share the same discrete geometry.

  ### 3. Add mouth-field observers

  - Define the mouth-center radiation origin at the center of the authored mouth:
    [
    O_\text{radiation}=(0,0,z_\text{mouth})
    ]

  - Add a conformal aperture observer just outside the actual curved mouth surface; default offset is 1 mm along the exterior
    normal.

  - Preserve, at every sample and frequency:
      - complex pressure (p)
      - complex outward normal velocity (v_n)
      - magnitude and phase
      - local position, normal, and area weight

  - Also generate a planar mouth-view projection for intuitive (x/y) heatmaps without treating that visualization plane as a
    physical boundary.

  - Produce pressure magnitude, phase, normal-velocity magnitude, phase, and local impedance plots.
  - Calculate aperture diagnostics including magnitude uniformity, phase spread, active area, modal asymmetry, and power flow.

  ### 4. Separate aperture behavior from exterior diffraction

  Provide two explicit radiation modes from the same run:

  - full_exterior_bem: includes the finite mouth edge, exterior horn body, scattering, and diffraction.
  - ideal_baffled_aperture: radiates the solved complex mouth pressure/velocity through an ideal infinite-baffle aperture
    calculation, intentionally excluding finite-edge and rear-body effects.

  For both modes:

  - Calculate horizontal, diagonal, and vertical far-field cuts.
  - Support optional full spherical directivity grids.
  - Normalize plots to on-axis per frequency while retaining unnormalized complex pressure.
  - Use the mouth center as the phase and radial reference.
  - Plot labeled −6 dB contours and calculate −6 dB beamwidth.
  - Compare the two modes in complex pressure before conversion to dB, producing an edge/exterior-diffraction difference
    result.

  ### 5. Make sweeps reliable and optimizer-ready

  - Split the process into reusable stages: geometry → mesh → solve → observers → radiation → metrics → plots.
  - Store each completed frequency atomically so long sweeps can resume after interruption.
  - Parallelize independent frequency solves within configurable memory limits.
  - Cache deterministic geometry and mesh artifacts by content hash.
  - Write a run manifest containing normalized HornCAD configuration, source definition, solver/library versions, mesh report,
    tolerances, frequency grid, observer definitions, coordinate references, convergence status, runtime, and artifact hashes.

  - Store complex multidimensional fields in NPZ/HDF5; reserve CSV for compact far-field cuts and summary metrics.
  - Expose a callable Python API returning structured results rather than requiring plots or parsing console output.
  - Generate optimizer-facing metrics such as beamwidth error, coverage consistency, directivity smoothness, off-axis variance,
    mouth phase spread, diffraction penalty, solver cost, and convergence confidence.

  - Reject candidates with invalid geometry, unsupported mesh resolution, solver non-convergence, or failed mesh-convergence
    criteria.

  ## Validation and Test Plan

  - Verify mesh sizing and rejection against known wavelength limits at several maximum frequencies.
  - Validate piston boundary area, orientation, uniform velocity, and integrated volume velocity.
  - Validate the BEM formulation against analytic pulsating-sphere and simple piston/baffle reference problems.
  - Confirm mouth pressure and normal velocity satisfy the boundary representation and yield consistent acoustic power.
  - Compare aperture integration against analytic rectangular and circular uniform-aperture directivity.
  - Run automated 6/8/10/12-elements-per-wavelength studies and compare complex pressure, −6 dB beamwidth, null locations, and
    mouth fields.

  - Establish production acceptance tolerances from the 8-versus-10/12 comparison; deep-null depth will not be an optimization
    metric unless converged.

  - Verify that translating the radiation reference changes phase consistently but not normalized far-field magnitude.
  - Verify ideal-aperture and full-exterior modes agree in controlled cases and diverge where finite-edge diffraction is
    expected.

  - Test interrupted-run recovery and deterministic reproduction from a saved manifest.
  - Cross-check representative HornCAD geometries against AKABAK using the same piston boundary, mesh target, reference point,
    frequencies, and observation cuts.

  ## Delivery Sequence

  1. Refactor the current solver into structured geometry, mesh, source, solve, observer, and result APIs.
  2. Implement acoustic mesh sizing, quality reports, and pre-solve rejection.
  3. Formalize the unit-volume-velocity piston and resonance-safe BEM formulation.
  4. Add resumable complex-frequency results and provenance manifests.
  5. Add conformal mouth pressure/velocity observations and planar plots.
  6. Add ideal baffled-aperture radiation and comparisons with full exterior BEM.
  7. Add convergence automation, analytic validation cases, and AKABAK cross-checks.
  8. Add stable acoustic metrics and connect them to the candidate-matrix runner.
  9. Permit automated optimization only after representative production meshes pass convergence criteria.

  ## Assumptions and Defaults

  - Frequency range is user-authored; the highest requested frequency controls the mesh.
  - Production mesh target is 8 elements per wavelength.
  - Verification uses 10 and 12 elements per wavelength.
  - Geometry origin is the throat center; radiation origin is the mouth center.
  - The source is a uniform axial piston with unit volume velocity, not a modeled compression driver.
  - Mouth results preserve complex pressure and normal velocity.
  - Both ideal-aperture and full-exterior radiation are first-class outputs.
  - Full exterior BEM includes edge diffraction; ideal-aperture mode intentionally excludes it.
  - Observer surfaces never alter the acoustic boundary or require enclosing boxes.