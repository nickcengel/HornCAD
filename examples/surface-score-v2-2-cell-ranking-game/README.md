# Surface score v2.2 per-cell ranking game

This blinded experiment contains 25 rounds: one for every cell in the
250–450 mm by 30–50 degree round-control grid. Each round contains ten unique
measured responses.

Selection alternates between the v2.2 and v1 rankings until each score has
contributed five unique candidates. If the next candidate from either ranking
has already been selected, that ranking advances until it finds the next unique
response.

Open `index.html` directly in a browser. Drag plots into best-to-worst order.
The browser autosaves every order and note to local storage. Mark each cell
complete after ranking it. Use **Export rankings** when finished and place the resulting
`surface_score_v2_2_cell_rankings.json` file in this directory.

The public experiment contains blinded plot IDs and coverage data.
`private_manifest.json` is the unblinding key and should not be inspected until
ranking is complete.

Rebuild without running BEM:

```bash
.venv/bin/python -m app.tools.generate_surface_score_v2_2_cell_ranking_game
```
