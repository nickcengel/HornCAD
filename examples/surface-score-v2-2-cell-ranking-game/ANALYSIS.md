# Completed per-cell ranking analysis

## Main result

Surface score v2.2 is substantially closer to the completed human order than
surface score v1 across the same ten candidates in every cell.

| Metric | V1 | V2.2 |
| --- | ---: | ---: |
| Mean within-cell Spearman | 0.165 | 0.546 |
| Mean pairwise agreement | 55.6% | 70.8% |
| Exact human winner | 10 / 25 | 8 / 25 |
| Mean rank assigned to human winner | 4.04 | 3.24 |

V2.2 has the higher cell-level Spearman correlation in 20 of 25 cells; v1 is
higher in four and one is tied. Twenty of the 25 human winners came from the
five candidates contributed by the v2.2 ranking.

Exact-winner count and overall ordering measure different things. V1 happens to
place the same candidate first in two more cells while ordering the rest of
each set much less successfully.

## Wider-coverage observation

The user's qualitative observation was: wider coverage was consistently worse
performing and harder to rank.

The measured score behavior supports the first part. Mean v2.2 score of the
human-selected winner declines from 84.51 at 40 degrees to 83.34 at 45 degrees
and 79.64 at 50 degrees. V1 largely conceals this degradation: its corresponding
winner means remain 87.92, 87.60, and 86.18.

The 50-degree cells are also the weakest diagnostic region:

| Coverage | V1 mean rho | V2.2 mean rho | V2.2 exact winner |
| --- | ---: | ---: | ---: |
| 30 degrees | 0.464 | 0.680 | 2 / 5 |
| 35 degrees | 0.253 | 0.593 | 3 / 5 |
| 40 degrees | 0.287 | 0.566 | 2 / 5 |
| 45 degrees | -0.113 | 0.571 | 1 / 5 |
| 50 degrees | -0.069 | 0.319 | 0 / 5 |

Ranking difficulty itself was not timed or scored, and the forced ordering
could not record ties. It therefore remains qualitative evidence. The lower
50-degree agreement is consistent with it, but does not independently measure
it.

## Component-weight experiment

Three nonnegative, sum-to-one families were fitted using pairwise logistic loss:

1. the five v1 components;
2. the five v2 contour components; and
3. all six distinct components together.

Every evaluation held out an entire mouth/coverage cell. The combined family
performed best:

| Fit | Held-out Spearman | Held-out pairs | Exact winner |
| --- | ---: | ---: | ---: |
| Reweighted v1 components | 0.473 | 67.8% | 8 / 25 |
| Reweighted v2 components | 0.636 | 74.9% | 9 / 25 |
| Combined six components | **0.653** | **76.1%** | **10 / 25** |

The full-evidence combined weights are:

| Component | Weight |
| --- | ---: |
| In-window profile RMS | 40.9% |
| Slice-energy stability | 29.4% |
| Three-contour beamwidth quality | 19.0% |
| Full-band -6 dB target accuracy | 10.7% |
| Mean containment | 0% |
| Outward-rise violation | 0% |

Zero fitted weight does not prove containment or outward rise are generally
useless. It means they add no ordering information in this deliberately
high-scoring candidate pool after the other four terms are present.

### Broad-range follow-up

The zero-weight result was tested out of sample against the earlier blinded
rankings. Rounds 1–10 each span the full v1 score distribution, with one
candidate drawn from every decile. The zero-containment/zero-rise weight
candidate is materially weaker there than the existing v2.2 score:

| Score | Broad mean rho | Broad pair agreement | Exact winner |
| --- | ---: | ---: | ---: |
| V1 | 0.818 | 84.2% | 5 / 10 |
| V2.2 | **0.902** | **89.1%** | 6 / 10 |
| High-score-pool fitted candidate | 0.835 | 85.6% | 5 / 10 |

Refitting all six components to the broad rounds assigns 13.4% to mean
containment and 17.0% to outward-rise control. Both remain nonzero in every
leave-one-round-out fold: containment ranges from 6.6% to 16.6%, and
outward-rise control from 13.5% to 19.7%. This confirms that the 0% values are
specific to the high-scoring per-cell pool and must not be promoted as general
weights.

A controlled ablation gives a more nuanced result. Starting with the fixed v2
formula, removing containment alone changes broad mean rho from 0.884 to 0.888;
removing outward-rise control lowers it to 0.873; removing both lowers it to
0.881. The effects are small because these diagnostics are correlated with
profile, contour, and energy-quality terms. A freely refitted four-component
model also matches the held-out broad ordering about as well as the
six-component fit, but matches fewer exact winners.

The practical conclusion is to retain containment and outward-rise control as
guardrails. The current v2.2 implementation already does: after its v1/v2
coverage blend, their effective weights are approximately 10–17% and 9–13%,
respectively, across the 30–50 degree study grid. The proposed 0% exploratory
fit is not a replacement score.

The complete recomputed evidence, per-round metrics, fitted weights, and
ablations are in
[`broad_range_weight_test.json`](../surface-diagnostic-ranking-experiment/broad_range_weight_test.json).

Coverage-specific fitting did not help. Its held-out Spearman was 0.607 versus
0.653 for one global weight set, despite having far more freedom. The available
evidence therefore supports one global candidate formula rather than five
coverage-specific formulas.

At 50 degrees, the combined held-out score improves mean Spearman from 0.319 to
0.501 and pairwise agreement from 61.8% to 68.4%, but still selects none of the
five exact human winners. Weight adjustment improves the broad order but does
not solve the wide-coverage winner problem. That remaining failure may require
a missing diagnostic term, explicit tie/confidence data, or both.

## Release interpretation

The combined weights are a promising v2.3 candidate, not a validated release.
The rankings were used to fit them, the candidate pool was selected using v1
and v2.2, and the game forced arbitrary distinctions where the user may have
perceived ties. Whole-cell cross-validation reduces leakage but cannot provide
independent validation.

Machine-readable details are in `analysis.json` and `weight_fit.json`.
