# Round Control Augmented v1

Portable quadratic response model for axisymmetric, round-mouth,
zero-extension OS-SE horns over 250–450 mm mouth diameters and 30–50 degree
coverage.

This artifact is retained for research comparison and reproducibility. It is
not a production baseline. `round_control_primary_v1` remains available only as
the API-compatible legacy reference estimator; later geometry studies use
measured round parents.

The six preregistered radiation diagnostics retain their original surface-score
definition. `throat_impedance_score` is an experimental seventh prediction for
future extension/throat-angle work and is not included in surface score,
benchmark ranking, or primary/augmented model choice.

Off-grid mouth/coverage values use bilinear coefficient interpolation. Those
predictions remain uncertainty-labeled until a future real design confirms them.
Non-round, asymmetric, extended, squared, sagged, or non-6-degree-throat designs
are unsupported by this release.

Validation counts: 50 locked;
0 historical challenge.
