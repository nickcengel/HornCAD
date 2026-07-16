# HornCAD application and analysis tools

## Design and geometry

Open `HornCAD.html` directly in a browser. It exports a YAML project containing
the acoustic profile, mouth, body, and mesh sampling settings.

Generate either acoustic-surface or printable-body STL geometry with:

```bash
python app/export_horncad.py project.yaml --mode surface --output-dir exports
python app/export_horncad.py project.yaml --mode body --output-dir exports
```

## Standard acoustic analyses

Interior FEM:

```bash
python app/run_fem_suite.py project.yaml \
  --output-dir results/my-horn/fem --title "My horn — FEM"
```

Free-air all-BEM using NumCalc and two mirror symmetries:

```bash
python app/run_bem_suite.py project.yaml \
  --output-dir results/my-horn/bem --title "My horn — BEM"
```

The default BEM sweep is 500–8000 Hz, 10 points per octave, and 6 elements per
wavelength. Both suites accept:

```text
--start-hz 500 --stop-hz 8000 \
--points-per-octave 10 --elements-per-wavelength 6
```

The standard deliverable is `interactive_report.html`. It contains cursor-
enabled H/V coverage heatmaps with explicit −6 dB contour lines and normalized
throat-impedance magnitude; throat
reactance is intentionally omitted. Impedance is normalized by `ρc/Sₜ`, using
the effective circular throat area. Solver directories also contain machine-readable
`responses.npz` and `metrics.csv`.

## Reports and comparisons

Regenerate a report from a completed run:

```bash
python app/interactive_results.py report results/my-horn/bem
```

Compare two to four completed FEM or BEM runs in one interactive window:

```bash
python app/interactive_results.py compare \
  results/horn-a/bem results/horn-b/bem \
  --names "Horn A" "Horn B" --output results/comparison.html
```

Comparison reports show the -6 dB H/V coverage lines, normalized impedance
magnitude, and the project acoustic parameters. A compact completed example is in
`examples/osse-400x280-reference/`.

## Supporting tools

- `webster_1d.py` — fast one-dimensional acoustic screening.
- `aperture_directivity.py` — idealized projected-aperture estimate.
- `helmholtz_2d.py` — independent H/V two-dimensional FEM approximation.
- `interior_fem.py` and `generate_fem_review.py` — standard FEM backend.
- `numcalc_bem_backend.py`, `run_numcalc_sweep.py`, and
  `generate_numcalc_review.py` — standard BEM backend.
- `interactive_results.py` — standard interactive reporting and comparison.

The lower-level backend modules are implementation details. Routine work should
start with `run_fem_suite.py` or `run_bem_suite.py`.
