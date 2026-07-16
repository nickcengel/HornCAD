# HornCAD

HornCAD designs horn and waveguide geometry and evaluates it with interior FEM
or free-air BEM acoustics.

## Quickstart

1. Open `app/browser/HornCAD.html` in a web browser. Start a new design or click
   **Import YAML** to resume an exported HornCAD project.
2. Design the horn and use **Export YAML** to save its project file.
3. Run one of the analysis commands below from the repository root.

Free-air BEM example with explicit sweep and mesh controls:

```bash
python app/tools/run_bem_suite.py path/to/project.yaml \
  --output-dir results/my-horn/bem \
  --title "My horn — BEM" \
  --start-hz 500 \
  --stop-hz 8000 \
  --points-per-octave 10 \
  --elements-per-wavelength 6
```

Interior FEM uses the same controls:

```bash
python app/tools/run_fem_suite.py path/to/project.yaml \
  --output-dir results/my-horn/fem \
  --title "My horn — FEM" \
  --start-hz 500 \
  --stop-hz 8000 \
  --points-per-octave 10 \
  --elements-per-wavelength 6
```

To search for improved free-air BEM candidates, export both the project YAML
and **BEM Search YAML** from the browser, keep them in the same directory, then
run:

```bash
python app/tools/run_bem_search.py path/to/my-horn-BEM-search.YAML \
  --output-dir path/to/my-horn-search
```

Open `search_report.html` in that output directory. Running the same command
again resumes interrupted candidates and completed NumCalc frequencies. Use
`--dry-run` first to materialize and geometry-check the initial candidate set
without running BEM.

Open `interactive_report.html` in the output directory. The standard report has
cursor readout, H/V coverage heatmaps with explicit −6 dB contour lines and
horizontal guides at the project’s intended ±H/V coverage angles, normalized
throat-impedance magnitude, and the horn acoustic parameters.
Impedance is normalized by the effective circular throat's characteristic
impedance, `ρc/Sₜ`; throat reactance is not plotted.

The report also writes `coverage_diagnostics.json` and displays three coverage
diagnostics for horizontal, vertical, and combined behavior:

- **Coverage match** is 100% minus the log-frequency-weighted RMS percentage
  error from the intended −6 dB half-angle.
- **Smoothness** is 100% minus the RMS deviation from a best-fit straight line
  versus log frequency, normalized by intended coverage.
- **Non-narrowing** is the upper-passband half-angle divided by the
  lower-passband half-angle, capped at 100% so widening is not rewarded.

All three headline diagnostics use 100% for ideal and lower values for worse
behavior. The JSON also retains underlying RMS error, fitted-line deviation,
endpoint angles, and signed narrowing for diagnosis.

The automatic diagnostic passband begins only when both planes sustain genuine
−6 dB crossings for at least one-third octave. A missing crossing after that
point is counted as 90° rather than discarded. The upper bound is the final
simulated frequency. This is a coverage-control bound, not a claim that an
arbitrary horn has a classical length-derived cutoff frequency.

To export geometry without running an acoustic analysis:

```bash
python app/tools/export_horncad.py path/to/project.yaml \
  --mode surface --output-dir exports
```

## Reports and comparisons

Both solver suites generate `interactive_report.html`, `responses.npz`, and
`metrics.csv`. Rebuild the interactive report from a completed run with:

```bash
python app/tools/interactive_results.py report results/my-horn/bem
```

Compare two to four completed FEM or BEM runs in one interactive report:

```bash
python app/tools/interactive_results.py compare \
  results/horn-a/bem results/horn-b/bem \
  --names "Horn A" "Horn B" --output results/comparison.html
```

Comparison diagnostics are recomputed for every run on the same 48-point-per-
octave logarithmic grid over their shared valid passband. Runs are displayed as
columns in separate Combined, Horizontal, and Vertical diagnostic tables.

Single-run coverage heatmaps include the simulated −6 dB contours, intended
±H/V coverage guides, readable logarithmic frequency grids, and cursor readout
of frequency, angle, and dB. Comparison reports show −6 dB half-angle and
normalized throat-impedance magnitude.

## Tool groups

Routine work starts with these commands:

- `run_bem_suite.py` — complete free-air NumCalc BEM analysis.
- `run_bem_search.py` — resumable constrained search for improved BEM candidates.
- `run_fem_suite.py` — complete interior FEM analysis.
- `export_horncad.py` — acoustic-surface or printable-body STL export.
- `interactive_results.py` — report regeneration and multi-horn comparison.

Supporting tools in `app/tools/` include the Webster screening model, idealized
aperture directivity, two-dimensional Helmholtz FEM, and lower-level FEM/BEM
adapters. They are implementation and validation tools rather than the normal
entry points.

## Repository map

- `app/browser/` — standalone browser designer.
- `app/tools/` — geometry, solver, workflow, and reporting commands.
- `app/native/` — native backend source.
- `examples/` — reviewable projects and compact solver results.
- `automated_tests/` — developer regression tests, not horn projects.
- `docs/reference/` — maintained technical reference material.
- `docs/plans/` — active implementation plans and unresolved design decisions.

The maintained example is
`examples/osse-400x280-reference/`. It contains the project YAML, acoustic STL,
and separate FEM and BEM results with interactive reports.

Developers and automated validation use `make validate` to run
`automated_tests/`. These tests catch unintended changes to geometry, meshing,
symmetry, solver adapters, numerical conventions, and report generation. They
are not part of running a normal horn project.

See `docs/reference/horncad_geometry.md` for geometry equations, coordinates,
the YAML schema, and STL behavior. The example project documents the provenance
of its retained FEM and BEM results in its own README.

The planned BEM candidate-search workflow is recorded in
`docs/plans/bem_candidate_search.md`.

`pyproject.toml` and `Makefile` remain at the root because Python packaging and
standard build tools expect project metadata there.
