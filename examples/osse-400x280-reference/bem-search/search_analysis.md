# BEM candidate search analysis

## Scope and status

This report analyzes the completed 500–5000 Hz, 6 EPW, 12 PPO free-air BEM
search recorded in `search_state.json`. The search produced 16 completed
candidates and two mesh failures. All 16 completed candidates passed the
sampling-stability check; the largest diagnostic change under factor-two
frequency decimation was 0.86 percentage point against the 2-point limit.

Combined diagnostics were rescored after the run using mouth-dimension weights:
58.8% horizontal and 41.2% vertical for the 400 x 280 mm mouth. Throat impedance
is retained as information but is intentionally excluded from feasibility,
Pareto selection, surrogate acquisition, and sampling stability until the later
extension study. The rescored Pareto set is candidates 001, 002, 003, and 015.

## Headline results

| Result | Candidate | Value | Important qualification |
|---|---:|---:|---|
| Best Pattern Fit | 015 | 70.6% | Balanced H/V Fit of 71.4/69.5% |
| Best Pattern Stability | 009 | 89.8% | HF Retention 31.3% |
| Best HF Retention | 001 | 51.3% | Short 255 mm, N=2 member |
| Best balanced H/V pattern result | 015 | H/V Fit 71.4/69.5% | H/V Retention 60.9/35.8% |
| Compact Pareto family | 001/002/003 | Fit about 64%; Retention 51.3% | N has negligible effect at low S |

The seed, candidate 000, produced weighted Pattern Fit 59.5%, Pattern Stability
83.6%, and HF Retention 45.1%.

## Matched N-family evidence

The initial families hold length, extension, coverage, and K fixed while varying
N. This is the cleanest causal evidence in the search.

| Length | N | S H/V | Pattern Fit | Pattern Stability | HF Retention | Min. normalized impedance |
|---:|---:|---:|---:|---:|---:|---:|
| 255 | 2 | 0.01 / 0.01 | 64.0% | 82.1% | 51.3% | 0.313 |
| 255 | 10 | 0.05 / 0.05 | 63.9% | 82.2% | 51.3% | 0.314 |
| 255 | 25 | 0.15 / 0.14 | 63.8% | 82.2% | 51.3% | 0.314 |
| 285 | 2 | 0.09 / 0.09 | 61.7% | 83.4% | 47.0% | 0.372 |
| 285 | 10 | 0.30 / 0.30 | — | — | — | mesh failure |
| 285 | 25 | 0.95 / 0.95 | — | — | — | mesh failure |
| 315 | 2 | 0.23 / 0.23 | 58.1% | 84.4% | 40.7% | 0.403 |
| 315 | 10 | 0.80 / 0.80 | 55.7% | 88.9% | 32.7% | 0.470 |
| 315 | 25 | 2.54 / 2.54 | 53.9% | 89.8% | 31.3% | 0.435 |
| 345 | 2 | 0.27 / 0.26 | 60.2% | 86.9% | 41.4% | 0.366 |
| 345 | 10 | 0.94 / 0.89 | 68.9% | 84.9% | 29.2% | 0.243 |
| 345 | 25 | 2.99 / 2.83 | 58.8% | 85.4% | 22.8% | 0.246 |

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
Its vertical HF Retention is still only 35.8%. Candidate 014 is similar but
retains less horizontal beamwidth. These candidates identify the most useful
pattern-shaping neighborhood in this round.

### Deferred observation: impedance belongs with extension

The current impedance values are retained for later comparison, but they do not
affect coverage-stage ranking. Extension varied in the adaptive tail of this
completed experiment, which makes the loading observations too confounded for a
clean rule. Future coverage rounds keep extension fixed. A separate matched
extension study will determine how total axial depth and the L/E allocation
control impedance.

## Implications for future candidate groups

### Group A: deferred extension/impedance experiment

Do not mix this group into the next coverage round. Hold one promising H/V
pattern construction fixed and vary axial geometry deliberately.

- Use candidate 015 as the pattern reference and candidate 017 as the loading
  reference.
- Evaluate explicit total axial depths across the available envelope.
- When extension is varied, trade it against horn length and report
  `length + extension`; do not let both independently increase depth.
- Couple K to length as needed to retain nonnegative S, but target matched S or
  matched realized curvature so the loading trend is interpretable.
- Use the results to decide later whether a 0.7 constraint is meaningful and
  reachable for this fixed-mouth design space.

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

Explore around candidates 014 and 015 with extension fixed.

- Preserve their approximately balanced H/V Pattern Fit.
- Apply equivalent relative experiments in both axes, while allowing the
  different authored H/V coverage targets to produce different numeric values.
- Prioritize vertical HF Retention; it is the dominant weakness after fit is
  balanced.

### Group D: compact candidate

Candidate 013 is informative because its total depth is only 270 mm and its
horizontal result is strong. Build a small matched group around it to determine
whether vertical performance can improve while retaining compactness. This is
more useful than broadly rewarding or penalizing departure from the 300 mm seed.

### Group E: meshing-feasibility boundary

Candidates 005 and 006 failed before acoustic results were available. Both are
285 mm members with increased N/S and larger roundover. Add a deterministic
self-intersection and mesh-validity preflight for candidate geometry before
solver scheduling. Then regenerate nearby, slightly less aggressive termination
geometries to determine whether the missing 285 mm results represent a narrow
geometry failure boundary rather than an unusable acoustic region.

## Recommended next-round order

1. Use mouth-proportional combined scoring, keep impedance informational, fix
   extension, and give shorter total depth no departure cost. This is now
   implemented.
2. Add the geometry/mesh preflight that would have rejected candidates 005 and
   006 without launching solver work.
3. Run Groups B and C as the next coverage experiments.
4. Retain Group D as the compact branch and compare it on the same evaluated
   band.
5. Run Group A later as a separate extension/impedance experiment.

The next round should not use unconstrained independent variation of all eight
parameters. Each group should answer one named question with matched controls,
and the report should identify that question before any BEM sweep begins.

## Round-two candidate pool

The implemented round-two preflight is in `round-2/`. It contains the seed plus
12 new candidates in four controlled groups:

| Group | Candidates | Question |
|---|---:|---|
| Moderate-S N | 3 | How does N trade Pattern Stability against HF Retention around the best balanced-pattern neighborhood? |
| Matched-S length | 4 | What does length do when extension, construction coverage, N, and realized S are held approximately constant? |
| Matched-S construction coverage | 3 | Which OS-SE construction coverage best matches the authored coverage when realized S is held at 0.45? |
| Compact vertical branch | 2 | Can vertical fit/retention improve near the compact candidate-013 neighborhood without changing its horizontal construction? |

Extension is zero for every candidate. The matched-S groups hold both axes near
S=0.45; the 345 mm vertical member reaches S=0.391 because K is already at its
configured maximum of 60. The pool deliberately does not optimize only Pattern
Fit. Each group isolates a lever, while final selection retains Pattern Fit,
Pattern Stability, and HF Retention as separate Pareto objectives.
