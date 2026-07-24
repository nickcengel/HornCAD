# Surface score v2.2 calibration

V2.2 was fitted to the 25 completed per-cell comparisons between the measured
v1 and v2.1 round-control winners. All six cells with identical winners were
marked tie. Of the 19 different-winner cells, 13 had a decisive preference and
six were ties.

The constrained candidate family blends v1 target adherence with
contour-forward v2 using a smooth coverage-dependent fraction:

`0.20 + (maximum - 0.20) * clip((coverage - 25) / 25, 0, 1) ** exponent`

The calibration tested five exponents and six maximum fractions. Selection
first maximized agreement with the decisive cell-winner preferences, then
agreement with the earlier 236 saved comparisons, then chose the simplest and
smallest surviving parameters. The selected exponent is 2 and the maximum v2
fraction is 0.65.

This fits all 13 decisive winner choices. It is calibration on those choices,
not independent validation. Agreement with the earlier comparisons is also
reported rather than hidden.

Rebuild without BEM:

```bash
.venv/bin/python -m app.tools.calibrate_surface_score_v2_2
```
