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
  from 400 mm. Existing K/N winners seed a selected 45-degree anchor when
  available.
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
   diagonal neighbors and refines to K=0.25 and N=1 resolution.
3. At the closed K/N winner, measure five local S points centered on the current
   S at offsets -0.30, -0.15, 0, +0.15, and +0.30.
4. If the best local S is within 0.075 of the center, declare the alternating
   search converged.
5. Otherwise use the new length as the next seed and repeat, for at most three
   rounds. Reaching that limit is reported as unresolved, not converged.

K is limited to 1 through 7 and N to 2 through 40. A K/N winner at an upper
limit remains boundary-limited. Lower limits K=1 and N=2 are accepted safety
limits.

## Scheduling and reporting

`app.tools.run_coupled_kn_length_program` waits for all 40/50 baselines and the
active 45-degree K/N prerequisite. It first runs the canonical 45-degree
extensions in two concurrent streams, then selects coupled anchors from the
expanded evidence and runs two independent anchors concurrently. Each stream
uses ten NumCalc workers, keeping the intended 20-core load while permitting
geometry and report work in one stream to overlap solves in the other.

Every completed local-S round regenerates the main index. Generated studies are
siblings of the baseline searches and use names such as
`400x400-coupled-r01-kn` and `400x400-coupled-r01-s`, so their reports and
candidate artifacts remain discoverable by the existing index scan.

No additional 60-degree search should be generated or queued.
