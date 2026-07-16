# HornCAD

HornCAD designs horn and waveguide geometry and evaluates it with interior FEM
or free-air BEM acoustics.

## Quickstart

1. Open `app/HornCAD.html` in a web browser. Start a new design or click
   **Import YAML** to resume an exported HornCAD project.
2. Design the horn and use **Export YAML** to save its project file.
3. Run one of the analysis commands below from the repository root.

Free-air BEM example with explicit sweep and mesh controls:

```bash
python app/run_bem_suite.py path/to/project.yaml \
  --output-dir results/my-horn/bem \
  --title "My horn — BEM" \
  --start-hz 500 \
  --stop-hz 8000 \
  --points-per-octave 10 \
  --elements-per-wavelength 6
```

Interior FEM uses the same controls:

```bash
python app/run_fem_suite.py path/to/project.yaml \
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

To export geometry without running an acoustic analysis:

```bash
python app/export_horncad.py path/to/project.yaml \
  --mode surface --output-dir exports
```

## Repository map

- `app/` — design application and command-line analysis tools.
- `examples/` — reviewable projects and compact solver results.
- `automated_tests/` — developer regression tests, not horn projects.
- `docs/reference/` — maintained technical reference material.
- `docs/plans/` — current work plans only.

The maintained example is
`examples/osse-400x280-reference/`. It contains the project YAML, acoustic STL,
and separate FEM and BEM results with interactive reports.

Developers and automated validation use `make validate` to run
`automated_tests/`. These tests catch unintended changes to geometry, meshing,
symmetry, solver adapters, numerical conventions, and report generation. They
are not part of running a normal horn project.

See `app/README.md` for command details and `docs/README.md` for documentation.
`pyproject.toml` and `Makefile` remain at the root because Python packaging and
standard build tools expect project metadata there.
