# Central-angle coupled optimization program

## Purpose

The broad uniform-S searches locate the useful length region at K=4, N=10,
but cannot prove that length remains optimal after K and N change. The central
program therefore alternates K/N closure and local length/S refinement until
both searches return the same neighborhood.

Active 40-degree and 50-degree uniform-S searches remain useful and must finish.
They establish the angle-dependent length ridge and provide an unbiased basis
for selecting the more expensive coupled anchors.

## Priority and anchor selection

The program supersedes further 60-degree work. Completed 60-degree results are
retained as historical evidence, but no new 60-degree search is scheduled.

- At 40, 45, and 50 degrees, always study 400 mm as the matched cross-angle
  control. Also study the highest-scoring baseline mouth when it is distinct
  from 400 mm and beats the control by at least 0.75 surface-score points.
  This keeps a meaningful mouth-scale contrast without coupling a nearly
  redundant runner-up. Existing K/N winners seed a selected 45-degree anchor
  when available. The queue records each decision and score margin in
  `coupled_anchor_selection.json`.
- Edge mouths remain conditional follow-ups. Schedule them only if the matched
  controls show material K/N movement, the best baseline lies at an edge, or
  interpolation uncertainty remains high. Do not automatically close every
  edge before this evidence exists.
- Duplicate selections are collapsed.

Before coupled closure begins, add compact canonical-S extensions to the older
45-degree 300-500 mm grids. Each extension measures missing 0.25-grid points
within 0.55 S of the observed maximum plus the matched S=0.5 turnover reference.
Existing candidates are not rerun. These extensions make the important portion
of each 45-degree curve directly comparable with the newer 40/50-degree grids.

## Alternating closure

For each selected anchor:

1. Start from the best completed baseline or existing K/N candidate.
2. Run adaptive K/N closure at fixed length. The closure measures axial and
   diagonal neighbors at K=0.5. If the complete neighborhood is within 0.5
   surface-score points of its incumbent, record the plateau and move directly
   to local S/length refinement. Otherwise refine N toward 1 resolution.
   Quarter-step K probes are not required: current evidence shows a broad K
   crest whose quarter-step score differences are below useful diagnostic
   resolution.
   Fine-stage diagonals are also omitted when the four axial probes are already
   within 0.5 score points. N is never refined below a one-unit step.
3. At the closed K/N winner, measure five local S points centered on the current
   S at offsets -0.30, -0.15, 0, +0.15, and +0.30.
4. If the best local S is within 0.075 of the center, declare the alternating
   search converged.
5. Otherwise use the new length as the next seed and repeat, for at most three
   rounds. Reaching that limit is reported as unresolved, not converged.

The asymptote handoff does not erase the K/N alternatives. Its closure
certificate retains the complete plateau, including K/N bounds and scores.
When local S selects a materially different length, the next round reopens K/N
there. This separates the physical evidence for a broad K≈4 region from an
algorithmic tendency to keep selecting exactly K=4.

K is limited to 1 through 7 and N to 2 through 40. A K/N winner at an upper
limit remains boundary-limited. Lower limits K=1 and N=2 are accepted safety
limits.

## Scheduling and reporting

`app.tools.run_bem_study_program` owns the complete production queue. After its
per-baseline S closure chains produce one global certificate, it runs authored
K/N grids and canonical 45-degree extensions, then selects and runs coupled
anchors. It maintains two concurrent ten-worker search slots throughout.
`run_coupled_kn_length_program` supplies materialization and anchor functions;
it should not be launched as a separate waiter.

Every completed local-S round regenerates the main index. Generated studies are
siblings of the baseline searches and use names such as
`400x400-coupled-r01-kn` and `400x400-coupled-r01-s`, so their reports and
candidate artifacts remain discoverable by the existing index scan.

No additional 60-degree search should be generated or queued.
