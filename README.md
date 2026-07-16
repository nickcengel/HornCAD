# HornCAD

HornCAD designs horn and waveguide geometry and evaluates it with FEM or
free-air BEM acoustics.

## Start here

- Open `app/HornCAD.html` to design a horn and export its YAML project file.
- Run `python app/export_horncad.py project.yaml` to generate an STL.
- Run `python app/run_fem_suite.py project.yaml --output-dir results/my-fem-run`
  for the interior FEM workflow.
- Run `python app/run_bem_suite.py project.yaml --output-dir results/my-bem-run`
  for the free-air, symmetry-reduced NumCalc BEM workflow.

Both solver suites generate `interactive_report.html` with cursor readout,
coverage, magnitude-only throat impedance, and acoustic design parameters.
Custom sweep bounds use `--start-hz`, `--stop-hz`, `--points-per-octave`, and
`--elements-per-wavelength`.

## Repository map

- `app/` — design application and command-line analysis tools.
- `examples/` — reviewable projects and compact solver results.
- `automated_tests/` — software regression tests, not horn projects.
- `docs/reference/` — maintained technical reference material.
- `docs/plans/` — current work plans only.

The maintained example is
`examples/osse-400x280-reference/`. It contains the project YAML, acoustic STL,
and separate FEM and BEM results with interactive reports.

See `app/README.md` for command details and `docs/README.md` for documentation.
`pyproject.toml` and `Makefile` remain at the root because Python packaging and
standard build tools expect project metadata there.
