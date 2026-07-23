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

Open `search_report.html` in that output directory. Candidate STL and report
names encode mouth width, mouth height, length, optional extension, coverage,
K, and N. Public reports are written directly in each candidate's `bem/`
folder; NumCalc's hashed working directory remains an internal resumable solver
detail. Running the same command again resumes interrupted candidates and
completed NumCalc frequencies. Use `--dry-run` first to materialize and
geometry-check the initial candidate set without running BEM.

Open `interactive_report.html` in the output directory. The standard report has
cursor readout, H/V coverage heatmaps with explicit −6 dB contour lines and
horizontal guides at the project’s intended ±H/V coverage angles, normalized
throat-impedance magnitude, and the horn acoustic parameters.
Impedance is normalized by the effective circular throat's characteristic
impedance, `ρc/Sₜ`; throat reactance is not plotted.

The report also writes `coverage_diagnostics.json` and displays four coverage
diagnostics for horizontal, vertical, and combined behavior:

- **Coverage Match** integrates the smoothed −6 dB half-angle error over the
  diagnostic band, with separate recorded under-coverage and over-coverage
  components.
- **Coverage Smoothness** combines fine ripple after local smoothing with
  broader wiggle away from a one-third-octave trend, then applies a calibrated
  score gain so chaotic, peaky, or bumpy coverage traces lose score quickly even
  when their average width is close to target.
- **Waist Stability** scores the depth of the broad lower-band narrowing trough
  over the first two octaves after the crossover transition. A waist at zero
  degrees is 0%, a waist at half the intended half-angle is 50%, and no
  detected interior waist is 100%.
- **Window Uniformity** samples the normalized response at half the intended
  coverage angle, such as 22.5° for a 45° target, and scores the weighted RMS
  dB deviation from that trace's average level across the diagnostic band. It
  also scans from 0° to the measured −6 dB half-angle and applies an extra
  penalty for positive off-axis regions inside that window.

All headline diagnostics use 100% for ideal and lower values for worse
behavior. Combined H/V diagnostics are weighted in proportion to physical mouth
width and height, so the larger mouth dimension contributes more to the combined
score. The crossover weighting assumes a 12 dB/oct acoustic amplitude slope
with −6 dB, or about 50%, at crossover; error near crossover contributes less
than error after the transition reaches full weight one half-octave above
crossover. The JSON records those weights and also retains weighted total,
under-coverage, over-coverage, raw smoothness, fine-ripple, and broad-wiggle
errors, the smoothness score gain, waist frequency/depth when detected, window
probe angle, deviation statistics, positive-zone statistics, ripple RMS,
crossover angle, and highest-frequency endpoint error for diagnosis.

The automatic diagnostic passband begins only when both planes sustain genuine
−6 dB crossings for at least one-third octave. A missing crossing after that
point is counted as 90° rather than discarded. The upper bound is the final
simulated frequency. This is a coverage-control bound, not a claim that an
arbitrary horn has a classical length-derived cutoff frequency.

Current reports also write `surface_diagnostics.json`. Its final surface score
combines in-window profile error, slice-energy stability, mean containment,
outward-rise violation, and the secondary −6 dB line. The four coverage-control
scores above remain visible diagnostic views; they are not interchangeable with
the surface-score components. See
[`docs/reference/bem_surface_diagnostics.md`](docs/reference/bem_surface_diagnostics.md)
for the implemented definitions.

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
- `run_stage_aware_bem_queue.py` — multi-search queue that keeps NumCalc cores
  occupied while other candidates mesh or generate diagnostics.
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
- `docs/archive/` — superseded plans and frozen research snapshots retained for
  provenance, not current scheduling.

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

The documentation authority map is in `docs/README.md`. The active canonical
BEM experiment is specified in `examples/control-decoupling/study_plan.md`,
with its model export pipeline alongside it. The later cross-study geometry
program is defined in `docs/plans/geometry_research_roadmap.md`.

The round-control API loads `models/round_control_primary_v1/` as a legacy
reference estimator. It is not a validated global interpolation surrogate;
future geometry studies must anchor comparisons to nearby measured round
parents. Augmented v1 remains research comparison evidence. Both a targeted
quadratic consolidation and a simulation-free nonlinear follow-up failed their
locked challenges, so no v2 model was released; see
`examples/round-control-nonlinear-evaluation/README.md`.
Measured, non-predictive starting rules remain available in
`models/round_control_heuristics_v1/` and are documented in
`docs/reference/round_control_heuristics.md`.

`pyproject.toml` and `Makefile` remain at the root because Python packaging and
standard build tools expect project metadata there.
