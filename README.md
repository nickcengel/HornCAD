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

Open `interactive_report.html` in the output directory. The standard report has
cursor readout, H/V coverage heatmaps with explicit −6 dB contour lines and
horizontal guides at the project’s intended ±H/V coverage angles, normalized
throat-impedance magnitude, and the horn acoustic parameters.
Impedance is normalized by the effective circular throat's characteristic
impedance, `ρc/Sₜ`; throat reactance is not plotted.

The report also writes `coverage_diagnostics.json` and displays three coverage
diagnostics for horizontal, vertical, and combined behavior:

- **Coverage error** is the log-frequency-weighted RMS percentage error from
  the intended −6 dB half-angle; lower is better. The report also gives the
  percentage of the evaluated passband within ±10% of intent.
- **Smoothness** is a 0–100 score for ripple after removing the best-fit gradual
  trend versus log frequency; higher is better.
- **Narrowing** is the signed percentage change between the lower and upper
  evaluated passband endpoints; positive means the horn became narrower.

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

Single-run coverage heatmaps include the simulated −6 dB contours, intended
±H/V coverage guides, readable logarithmic frequency grids, and cursor readout
of frequency, angle, and dB. Comparison reports show −6 dB half-angle and
normalized throat-impedance magnitude.

## Tool groups

Routine work starts with these commands:

- `run_bem_suite.py` — complete free-air NumCalc BEM analysis.
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

`pyproject.toml` and `Makefile` remain at the root because Python packaging and
standard build tools expect project metadata there.
