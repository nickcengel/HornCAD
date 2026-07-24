# Round-control parameter maps ranked by surface score v2.1

This standalone report selects the highest measured surface score v2.1 in each
of the 25 round-control mouth/coverage cells. It uses 1,532 unique retained
responses: the frozen 1,484-response comparison population plus all 48
ridge-closure responses.

The report contains:

- absolute v2.1 winner maps for score, length, K, N, and S;
- delta maps for length, K, N, and S;
- a 25-row table giving the exact per-cell parameter deltas between the v1 and
  v2.1 winners;
- a cell-filtered coverage viewer that shows the v2.1 winner first and toggles
  to the corresponding v1 winner when clicked;
- links to retained candidate reports; and
- a deterministic `winners.json` audit artifact.

The v1 winner is independently reconstructed from the same combined evidence
population. All 25 reconstructed winners match the existing v1 parent map.

Rebuild without running BEM:

```bash
.venv/bin/python -m app.tools.report_round_control_parameter_maps_v2_1
```

Surface score v1 remains the normal search-ranking score. This report is a
side-by-side evaluation of the experimental v2.1 diagnostic.

The completed per-cell human choices are retained in
`human_winner_selections.json` and are bound to the exact `winners.json`
content hash.
