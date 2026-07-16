# Active BEM search recovery note

## Objective

Run the maintained OS-SE 400×280 mm horn candidate search in free air from
500–5000 Hz using 6 elements per wavelength and 12 points per octave. The quick
budget permits 16 completed BEM candidates. Confirmation, when finalists are
selected, uses 16 PPO.

## Command

From the HornCAD repository root:

```bash
.venv/bin/python app/tools/run_bem_search.py \
  examples/osse-400x280-reference/bem-search/search.yaml \
  --output-dir examples/osse-400x280-reference/bem-search
```

The command is resumable. Re-running it continues incomplete candidate and
frequency work from `search_state.json` and each candidate's BEM run directory.

## Expected phases

1. Evaluate the seed.
2. Evaluate retained coupled candidates distributed across positive-S, mouth
   exit-angle, and curvature-radius geometry.
3. Learn lever effects from sampling-stable completed candidates.
4. Propose adaptive candidates, screening only confidently inferior or duplicate
   proposals.
5. Produce the Pareto set and finalist comparison after the quick budget is met.

## Review and recovery

- Open `search_report.html` for live status and completed diagnostics.
- Inspect `search_state.json` for the current phase, candidate status, rejected
  count, and proposal count.
- A stopped shell does not require deleting results; run the same command again.
- Do not mix results from a changed search YAML into this run. A changed
  configuration requires a deliberately new or regenerated search state.
