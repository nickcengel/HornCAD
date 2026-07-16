# HornCAD application

The application is divided by responsibility:

- `browser/` — the standalone interactive designer.
- `tools/` — Python geometry and acoustic-analysis commands.
- `native/` — C++ backend source.

## Design and geometry

Open `browser/HornCAD.html` directly in a browser. Click **Import YAML** to resume an
existing version-2 HornCAD project; all design controls, modifier splines, and
the preview are restored. **Export YAML** saves the acoustic profile, mouth,
body, and mesh sampling settings.

Generate either acoustic-surface or printable-body STL geometry with:

```bash
python app/tools/export_horncad.py project.yaml --mode surface --output-dir exports
python app/tools/export_horncad.py project.yaml --mode body --output-dir exports
```

## Standard acoustic analyses

Interior FEM:

```bash
python app/tools/run_fem_suite.py project.yaml \
  --output-dir results/my-horn/fem --title "My horn — FEM"
```

Free-air all-BEM using NumCalc and two mirror symmetries:

```bash
python app/tools/run_bem_suite.py project.yaml \
  --output-dir results/my-horn/bem --title "My horn — BEM"
```

The default BEM sweep is 500–8000 Hz, 10 points per octave, and 6 elements per
wavelength. Both suites accept:

```text
--start-hz 500 --stop-hz 8000 \
--points-per-octave 10 --elements-per-wavelength 6
```

The standard deliverable is `interactive_report.html`. It contains cursor-
enabled H/V coverage heatmaps with explicit −6 dB contour lines and dashed
horizontal guides at the project’s intended ±H/V coverage angles, plus
normalized throat-impedance magnitude; throat
reactance is intentionally omitted. Impedance is normalized by `ρc/Sₜ`, using
the effective circular throat area. Solver directories also contain machine-readable
`responses.npz` and `metrics.csv`.

Frequency axes use labeled 1/2/5 logarithmic ticks with fine decade subdivisions;
coverage angles use 30-degree major grid lines. These grids are rendered above
the opaque heatmap rather than behind it. The H/V heatmaps share one dB color
scale so the legend, scale, and Plotly toolbar do not overlap.
Contour and intended-coverage overlays do not capture hover events; cursor
readout always reports the underlying heatmap frequency, angle, and dB value.

## Reports and comparisons

Regenerate a report from a completed run:

```bash
python app/tools/interactive_results.py report results/my-horn/bem
```

Compare two to four completed FEM or BEM runs in one interactive window:

```bash
python app/tools/interactive_results.py compare \
  results/horn-a/bem results/horn-b/bem \
  --names "Horn A" "Horn B" --output results/comparison.html
```

Comparison reports show the -6 dB H/V coverage lines, normalized impedance
magnitude, and the project acoustic parameters. A compact completed example is in
`examples/osse-400x280-reference/`.

## Supporting tools

- `tools/webster_1d.py` — fast one-dimensional acoustic screening.
- `tools/aperture_directivity.py` — idealized projected-aperture estimate.
- `tools/helmholtz_2d.py` — independent H/V two-dimensional FEM approximation.
- `tools/interior_fem.py` and `tools/generate_fem_review.py` — standard FEM backend.
- `tools/numcalc_bem_backend.py`, `tools/run_numcalc_sweep.py`, and
  `tools/generate_numcalc_review.py` — standard BEM backend.
- `tools/interactive_results.py` — standard interactive reporting and comparison.

The lower-level backend modules are implementation details. Routine work should
start with `tools/run_fem_suite.py` or `tools/run_bem_suite.py`.
