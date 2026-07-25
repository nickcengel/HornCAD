# Round-control 6° composite extension map

Status: complete; 23-case S-recovery closure, four-case wide A8 bridge, and
25-case lower-coverage A6/A8 completion measured and analyzed

## Purpose

Combine the completed round-control evidence with the directly measured
6-degree extension evidence. Rank this standalone map by composite score v1.0:

```text
0.75 × surface score v2.3 + 0.25 × throat impedance score v2.3.0
```

This does not make the composite score authoritative for every repository
ranking. Surface score v2.3 remains the round-control diagnostic of record.
The composite is authoritative only for this extension-selection analysis.

## Reused evidence

Use the already refreshed diagnostic records without recalculating BEM or
surface diagnostics:

- 1,542 exact-response-deduplicated zero-extension round responses;
- all completed 6-degree extension responses from the 216-case extension and
  throat-angle study.

The merger verifies surface v2.3, throat-impedance v2.3.0, and composite v1.0
on every retained response. It exact-response-deduplicates the combined
population and preserves candidate-report links and response hashes.

The map reports the best measured composite configuration in every
mouth/coverage cell, maps extension alongside L/K/N/S, and retains separate
surface and impedance components. Per-extension views must distinguish missing
parent-matched evidence from a measured loss.

## Existing finding and triage

For the original 25 primary parents, none of the measured 20, 40, or 60 mm
extensions improved composite score. Median changes were -5.02, -5.68, and
-5.42 points respectively. High-scoring zero-extension cells with good throat
loading are no-action cells.

Additional simulations are restricted to low-loading cells. Seven cells whose
current composite parent differs from the parent used by the extension study
receive an ordinary/matched triplet:

- 45° / 250 mm;
- 45° / 350 mm;
- 45° / 400 mm;
- 50° / 250 mm;
- 50° / 300 mm;
- 50° / 350 mm.
- 50° / 400 mm.

The 50°/450 mm current composite parent already has an ordinary measured
extension, so it receives only the two matched variants. The comparatively
strong 45°/300 and 45°/450 mm cells receive no new simulations.

Use the most promising existing extension length in each selected cell. Compare
two ways of restoring the parent's S:

1. increase OSSE length while holding K fixed; and
2. reduce K while holding OSSE length fixed.

Run complete ordinary/length-matched/K-matched triplets in the seven
changed-parent cells. Run length- and K-matched transfers at 50°/450 mm. The
required K values must remain inside the registered K=1–7 range.

The S-recovery closure is exactly 23 new BEM simulations. A later explicit
authorization adds four A8/E40 bridge points, for 27 total:

- 45° / 250 mm;
- 45° / 450 mm;
- 50° / 250 mm;
- 50° / 450 mm.

Each bridge holds the legacy primary A6/E40 candidate's extension, OSSE length,
K, and N fixed. Exact A6 and A12 results already exist for all four. The new A8
point therefore tests the shape and consistency of the throat-angle impedance
response across both wide-coverage rows and the mouth-size extremes. The
observed A6-to-A12 impedance gains at these four coordinates span +13.3 to
+29.8 points.

An additional 25-simulation authorization completes matched A6/A8 coverage at
E40 across every 30°, 35°, and 40° cell:

- run A8 on all 15 mouth/coverage cells;
- run A6 on the 10 cells lacking an exact current-parent A6/E40 response;
- reuse exact A6/E40 evidence at 30°/250, 30°/450, 35°/450, 40°/300, and
  40°/450.

This produces a complete 15-cell A6/A8 lower-coverage comparison from 25 new
responses plus five exact reused responses. Length, K, N, extension, and parent
are held fixed within each angle pair. No A12 simulations are authorized.

## Length-allocation check

Before freezing coordinates, compare the selected parent and extension against
existing zero-extension candidates at nearby OSSE length, S, and total axial
span. The purpose is to determine whether composite performance responds to
additional OSSE profile length rather than extension.

If an essential zero-extension length-only control is absent, substitute that
control for a lower-value cell case. Do not exceed the 24-case cap.
Holding S constant is not assumed to require shortening: solve OSSE length from
the actual 6-degree geometry independently for every candidate.

## Execution and output

Freeze candidate coordinates and hashes before BEM. Use independent
one-candidate searches through the stage-aware scheduler with the shared
20-process NumCalc limit. Run the four-point angle addendum only after the
23-point closure queue finishes, so it cannot disrupt the active queue. Retain
compact NPZ responses, reports, project/search YAML, runtime ledgers, and the
shared study index.

After completion:

- rebuild the composite extension map with the new responses;
- publish ordinary, S-matched, and zero-extension length-allocation contrasts;
- add a measured 6-degree extension layer to the round heuristic artifact;
- do not promote the failed general 0°/6°/12° paired predictor.

## Completed findings

All 52 authorized new simulations completed. None of the 23 S-recovery
extension candidates beat its zero-extension parent under the registered
75% surface-v2.3 / 25% throat-impedance-v2.3.0 composite. After merging the
closure, zero extension remains the composite winner in all 25 round cells.
The best measured extension trails the zero-extension winner by a median 4.58
composite points.

This does not remove extension from later surface-first optimization. Four
cells retain a measured extension branch whose surface gain exceeds 0.5 point:
30°/450 mm, 35°/350 mm, 40°/250 mm, and 50°/350 mm. Zero extension is the
initialization rule; extension remains an early branch when the user's ranking
or weak throat loading makes the tradeoff relevant.

In the complete 15-cell matched 30°–40° A6/A8 grid, A8 improved throat
impedance in 14 cells, with a median gain of 6.90 points; it improved the
registered composite in 14 cells, with a median gain of 1.88 points. All four
wide-coverage bridge points also improved impedance and composite from A6 to
A8. These are measured matched responses for initialization and support
warnings. They do not promote a general throat-angle response predictor.
