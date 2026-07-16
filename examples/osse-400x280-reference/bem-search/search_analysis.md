# BEM candidate search analysis

## Scope and status

This report analyzes the completed 500–5000 Hz, 6 EPW, 12 PPO free-air BEM
search recorded in `search_state.json`. The search produced 16 completed
candidates and two mesh failures. All 16 completed candidates passed the
sampling-stability check; the largest diagnostic change under factor-two
frequency decimation was 0.86 percentage point against the 2-point limit.

No completed candidate satisfies the crossover-loading constraint. The required
minimum normalized throat-impedance magnitude is 0.7 over the
crossover-centered window. The best result was candidate 017 at 0.519. There is
therefore no loading-feasible Pareto set and no justified final winner from this
round. Coverage results remain useful for learning geometry trends.

## Headline results

| Result | Candidate | Value | Important qualification |
|---|---:|---:|---|
| Best Pattern Fit | 015 | 70.4% | Minimum normalized impedance only 0.174 |
| Best Pattern Stability | 009 | 89.4% | HF Retention 29.8%; impedance 0.435 |
| Best HF Retention | 001 | 49.1% | Impedance 0.313 |
| Best crossover loading | 017 | 0.519 | Only 74.2% of the required 0.7 threshold |
| Best loading among compact adaptive candidates | 013 | 0.473 | Pattern Fit 59.6%; total axial depth 270.0 mm |
| Best balanced H/V pattern result | 015 | H/V Fit 71.4/69.5% | H/V Retention 60.9/35.8%; loading fails badly |

The seed, candidate 000, produced Pattern Fit 57.1%, Pattern Stability 82.9%,
HF Retention 42.7%, and minimum normalized impedance 0.389.

## Matched N-family evidence

The initial families hold length, extension, coverage, and K fixed while varying
N. This is the cleanest causal evidence in the search.

| Length | N | S H/V | Pattern Fit | Pattern Stability | HF Retention | Min. normalized impedance |
|---:|---:|---:|---:|---:|---:|---:|
| 255 | 2 | 0.01 / 0.01 | 61.3% | 81.2% | 49.1% | 0.313 |
| 255 | 10 | 0.05 / 0.05 | 61.2% | 81.4% | 49.1% | 0.314 |
| 255 | 25 | 0.15 / 0.14 | 61.2% | 81.4% | 49.0% | 0.314 |
| 285 | 2 | 0.09 / 0.09 | 59.2% | 82.6% | 44.4% | 0.372 |
| 285 | 10 | 0.30 / 0.30 | — | — | — | mesh failure |
| 285 | 25 | 0.95 / 0.95 | — | — | — | mesh failure |
| 315 | 2 | 0.23 / 0.23 | 55.7% | 83.7% | 38.6% | 0.403 |
| 315 | 10 | 0.80 / 0.80 | 53.1% | 88.4% | 31.3% | 0.470 |
| 315 | 25 | 2.54 / 2.54 | 51.2% | 89.4% | 29.8% | 0.435 |
| 345 | 2 | 0.27 / 0.26 | 58.7% | 86.3% | 39.4% | 0.366 |
| 345 | 10 | 0.94 / 0.89 | 68.3% | 84.2% | 29.4% | 0.243 |
| 345 | 25 | 2.99 / 2.83 | 56.9% | 84.8% | 23.2% | 0.246 |

### Trend 1: N is nearly inactive at very low S

The complete 255 mm triplet is essentially unchanged from N=2 through N=25.
N changes the derived S and local curvature, but the acoustic diagnostics and
impedance barely move. This supports the user's observation that N sensitivity
is weak near S=0. Spending BEM evaluations on dense N sweeps in this region is
unlikely to be useful.

### Trend 2: N becomes influential at moderate and high S

At 315 mm, increasing N raises Pattern Stability by about 5.7 points, but lowers
Pattern Fit by about 4.5 points and HF Retention by about 8.8 points. The N=10
member improves loading relative to N=2, but N=25 gives some of that improvement
back. This is evidence of a non-monotonic loading response and a clear
smoothness-versus-narrowing tradeoff.

The 345 mm family shows a stronger interaction. N=10 improves Pattern Fit, but
HF Retention and loading collapse; N=25 then loses most of the fit improvement
while narrowing further. Large curvature radius is therefore not an
unconditional improvement. It may suppress ripple while increasing frequency-
dependent beam contraction.

### Trend 3: length effects are not isolated by the first-round families

The low-N rows suggest that longer horns generally become smoother but retain
less high-frequency beamwidth. Loading improves from 255 to 315 mm and then
falls at 345 mm. However, each length family uses a different coupled coverage/K
pair, so this is not a clean length-only experiment. It should guide the next
candidate construction, not be treated as a universal length law.

### Trend 4: vertical behavior limits the combined score

Across much of the search, horizontal Pattern Fit is approximately 70–81%, while
vertical Pattern Fit is often only 38–52%. Candidate 015 is the clearest
exception, with H/V Pattern Fit of 71.4/69.5% and Stability of 90.0/88.0%.
Its vertical HF Retention is still only 35.8%, and its impedance is the worst of
the completed set at 0.174. Candidate 014 is similar but retains less horizontal
beamwidth. These candidates identify a useful pattern-shaping neighborhood, not
a viable horn.

### Trend 5: pattern optimization and loading currently pull apart

The optimizer found candidate 015 with the best combined pattern diagnostics,
but its loading is extremely poor. Candidate 017 gives the best loading but
only middling pattern results, and still misses the constraint substantially.
Future selection must treat loading as a hard gate before ranking pattern
quality. Surrogate training should model normalized impedance directly and
avoid spending most of a round refining acoustically attractive but clearly
loading-infeasible neighborhoods.

## Implications for future candidate groups

### Group A: loading-recovery experiment

Run this group first. Hold one promising H/V pattern construction fixed and
vary axial geometry deliberately until the 0.7 loading boundary is crossed.

- Use candidate 015 as the pattern reference and candidate 017 as the loading
  reference.
- Evaluate explicit total axial depths across the available envelope.
- When extension is varied, trade it against horn length and report
  `length + extension`; do not let both independently increase depth.
- Couple K to length as needed to retain nonnegative S, but target matched S or
  matched realized curvature so the loading trend is interpretable.
- Terminate or redirect this group if the upper available depth still cannot
  approach 0.7. That outcome would indicate the 500 Hz crossover constraint is
  outside this fixed-mouth design space rather than merely poorly optimized.

### Group B: controlled moderate-S N study

Concentrate N evaluations where it demonstrated leverage.

- Target S around 0.3, 0.6, and 1.0 rather than repeating near-zero-S N sweeps.
- At each S regime, compare N=2, an intermediate value, and a high value.
- Include both a raw-control family (fixed coverage/K) and a realized-geometry
  family (K adjusted to hold S or curvature approximately fixed). The pair
  separates the direct N effect from the S change caused by N.
- Avoid S near 3 until moderate-S families show a reason to accept the severe
  HF Retention loss.

### Group C: balanced-pattern neighborhood

Explore around candidates 014 and 015 only after adding a loading-aware screen.

- Preserve their approximately balanced H/V Pattern Fit.
- Apply equivalent relative experiments in both axes, while allowing the
  different authored H/V coverage targets to produce different numeric values.
- Prioritize vertical HF Retention; it is the dominant weakness after fit is
  balanced.
- Reject predicted loading below a conservative floor before BEM. The floor
  should rise as the surrogate gains evidence, eventually approaching 0.7.

### Group D: compact loading candidate

Candidate 013 is informative because its total depth is only 270 mm, its
minimum normalized impedance is 0.473, and its horizontal result is strong.
Build a small matched group around it to determine whether vertical performance
can improve without losing loading. This is more useful than broadly rewarding
or penalizing departure from the 300 mm seed.

### Group E: meshing-feasibility boundary

Candidates 005 and 006 failed before acoustic results were available. Both are
285 mm members with increased N/S and larger roundover. Add a deterministic
self-intersection and mesh-validity preflight for candidate geometry before
solver scheduling. Then regenerate nearby, slightly less aggressive termination
geometries to determine whether the missing 285 mm results represent a narrow
geometry failure boundary rather than an unusable acoustic region.

## Recommended next-round order

1. Implement the post-search scoring change: loading is a hard constraint,
   acoustic scores remain raw, and compactness is a separate total-depth
   objective with no penalty for a shorter feasible horn.
2. Add the geometry/mesh preflight that would have rejected candidates 005 and
   006 without launching solver work.
3. Run Group A to establish whether the loading constraint is reachable.
4. If reachable, run Groups B and C within the loading-feasible region.
5. Retain Group D as the compact branch and compare it on the same evaluated
   band.

The next round should not use unconstrained independent variation of all eight
parameters. Each group should answer one named question with matched controls,
and the report should identify that question before any BEM sweep begins.
