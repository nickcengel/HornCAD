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

The program runs before additional 25-degree or 60-degree follow-up work.

- At 45 degrees, always study 350, 400, and 450 mm mouths. Existing K/N winners
  seed the 350 and 450 mm anchors when available.
- At 40 and 50 degrees, select the smallest mouth, largest mouth, and the
  highest-scoring baseline mouth. This gives endpoint and peak information
  without automatically running closure at all twelve combinations.
- Duplicate selections are collapsed.

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
active 45-degree K/N prerequisite. It then selects anchors from measured scores
and runs two independent anchors concurrently. Each anchor uses ten NumCalc
workers, keeping the intended 20-core load while permitting geometry and report
work in one stream to overlap solves in the other.

Every completed local-S round regenerates the main index. Generated studies are
siblings of the baseline searches and use names such as
`400x400-coupled-r01-kn` and `400x400-coupled-r01-s`, so their reports and
candidate artifacts remain discoverable by the existing index scan.

The older deferred 60-degree/450 mm K/N search is lower priority and should run
only after this central-angle coupled program completes.
