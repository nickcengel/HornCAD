# Round-control parameter maps ranked by surface score v2.3

This standalone report selects the highest measured surface score
v2.3 in each of the 25 round-control mouth/coverage cells. It uses all 1,532
unique retained responses: the frozen 1,484-response comparison population plus
all 48 ridge-closure responses.

The report contains:

- absolute v2.3 winner maps for score, length, K, N, and S;
- delta maps for length, K, N, and S relative to the v1 winners;
- a 25-row cell audit;
- a cell-filtered coverage viewer toggling between the v2.3 and v1 winners;
- links to retained candidate reports; and
- a deterministic `winners.json` artifact with diagnostic implementation and
  calibration hashes.

Rebuild from retained NPZ responses without running BEM:

```sh
.venv/bin/python -m app.tools.report_round_control_parameter_maps_v2_3
```

The rebuild recalculates v2.3 using the fixed shadow evaluation band. Use
`--workers 1` for a serial audit or leave the default bounded parallel read-only
pass.

V2.3 is calibrated but not independently validated. It became the diagnostic
of record and normal search-ranking score on July 24, 2026; v1 remains a
reproducible historical comparison.
