# Blinded coverage-surface ranking experiment

This standalone experiment presents twenty rounds of ten retained round-horn
coverage surfaces. The original first ten rounds each contain one response
sampled from every decile of the current surface score. The added ten rounds are
fine-discrimination sets: each contains the ten closest unused scores around a
successive score quantile. Together those close groups span poor through
excellent current scores, but any one group has a narrow score range. Candidate
identity, geometry, score, provenance, and absolute coverage/frequency
coordinates remain hidden until all rounds are locked.

Drag each round into best-to-worst order. Every plot also has an optional notes
field. Notes are keyed to the blinded plot ID, remain attached when a card is
moved, autosave with the order, and appear beside the revealed candidate in the
final report. Because these are axisymmetric round horns, each card shows one
coverage surface. Frequency uses the ordinary logarithmic Hz scale; angle is
normalized only so every target edge remains at ±1 without revealing coverage.

Build:

```sh
.venv/bin/python -m app.tools.surface_ranking_experiment build \
  examples/control-decoupling/model_source/training_index.json \
  examples/surface-diagnostic-ranking-experiment
```

Run:

```sh
.venv/bin/python -m app.tools.surface_ranking_experiment serve \
  examples/surface-diagnostic-ranking-experiment
```

Then open <http://127.0.0.1:8765/>.

The server writes `rankings.json` after the first autosave. A locked round cannot
be edited. When all twenty rounds are locked, it also writes `final_report.html`
with the user order, current score order, rank differences, per-round and pooled
agreement statistics, candidate-report links, and every per-plot note.

`private_manifest.json` contains the unblinding key and is intentionally never
served by the experiment server. Rebuilding refuses to overwrite an existing
`rankings.json`.

## Surface diagnostic v2 outcome

The completed rankings calibrated and validated the multiscale -3/-6/-9 dB
beamwidth-quality diagnostic described in
[`docs/plans/surface_diagnostic_v2.md`](../../docs/plans/surface_diagnostic_v2.md).
The selected experimental contour-forward v2 score improved mean broad-round Spearman
agreement from 0.818 to 0.879 and close-round agreement from 0.052 to 0.459.
Close-round pairwise agreement improved from 52.0% to 67.8%.

The complete machine-readable evidence is in
[`surface_diagnostic_v2_calibration.json`](surface_diagnostic_v2_calibration.json);
[`surface_diagnostic_v2_calibration.html`](surface_diagnostic_v2_calibration.html)
is the readable release report.
