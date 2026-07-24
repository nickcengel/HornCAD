# Surface score v1/v2 rank comparison

This standalone viewer ranks the same exact-response-deduplicated round-horn
evidence independently with surface score v1 and v2.

The completed selections subsequently calibrated the narrow-coverage
correction in experimental surface score v2.1. The original comparison remains
frozen: it records the evidence that exposed the 25-degree weakness rather than
retroactively replacing its v2 scores.

- The plot shows the v1 candidate at the selected rank by default.
- Press and hold the plot to show the v2 candidate at that rank; release to
  restore v1.
- Higher/lower buttons, arrow keys, and rank buttons navigate the top 25.
- Quantile buttons jump through the complete selected population.
- Mouth and coverage selectors rank globally, by either coordinate, or within
  an exact 5×5 cell.
- Preference buttons record whether plot 1, plot 2, or neither is clearly
  better. Optional notes are stored with the exact candidate pair.
- Selections autosave in browser storage and can be exported or imported as
  JSON for reproducible analysis.

Every candidate card links to its original report. The viewer uses the same
frequency, angle, and color viewport for both sides and overlays the −3, −6,
and −9 dB contours plus a dashed line at the displayed candidate's intended
coverage angle.

Rebuild from retained NPZ responses without running BEM:

```shell
.venv/bin/python -m app.tools.generate_surface_score_rank_comparison
```

After changing only the viewer UI, rebuild HTML without rescoring NPZ:

```shell
.venv/bin/python -m app.tools.generate_surface_score_rank_comparison --render-only
```

The frozen implementation plan is
[`docs/plans/surface_score_v1_v2_rank_viewer.md`](../../docs/plans/surface_score_v1_v2_rank_viewer.md).
