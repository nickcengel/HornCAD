# Surface score v1/v2 rank viewer

Status: implementation plan

## Purpose

Create a standalone, read-only comparison of the retained round-horn evidence
ranked independently by surface score v1 and v2. The viewer must make the
practical difference between the rankings visible without changing any study
result, model, or active BEM process.

## Evidence and scoring

1. Read the released round-control training index and retain every available
   round response, regardless of fit/validation/historical role.
2. Deduplicate exact BEM responses by response SHA-256 before ranking.
3. Recalculate v1 and v2 from the retained NPZ on the fixed 48-points-per-octave
   evaluation grid. Fail if recalculated v1 disagrees with the indexed v1
   response beyond the documented numerical tolerance.
4. Rank the same deduplicated evidence independently by v1 and v2. Preserve
   IDs, provenance, geometry, scores, response hashes, and candidate-report
   links in a machine-readable comparison artifact.

## Interaction

- Open at rank 1 of the top 25.
- Show the v1-ranked coverage plot by default.
- While the plot is pressed or touched, show the v2 plot at the same rank;
  restore v1 on release or pointer cancellation.
- Provide explicit higher-rank and lower-rank buttons, keyboard arrow
  navigation, and direct rank buttons for ranks 1–25.
- Provide quick jumps to representative quantiles of the complete ranking.
- Provide independent mouth and coverage selectors. `All` preserves the global
  ranking; either selector may filter one coordinate, and selecting both ranks
  within the exact mouth/coverage cell. Recompute the available top-25 range
  and quantile ranks within the filtered evidence.
- Keep the two plots in the identical viewport, frequency scale, angle scale,
  and color scale so the toggle is a direct visual comparison.
- Show the active candidate ID, geometry, score, provenance, and report link
  outside the press target.

## Verification

- Deterministic rebuilds must produce byte-identical JSON and HTML.
- Every displayed response hash must be unique within the ranking population.
- Both rankings must contain the same evidence set.
- The viewer must clamp rank navigation to its valid range and restore v1
  after pointer release, pointer cancellation, loss of focus, and Escape.
- Generation and tests use no BEM and do not write inside the active
  extension/throat-angle study.
