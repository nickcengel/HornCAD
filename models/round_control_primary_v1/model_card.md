# Round Control Primary v1

Portable quadratic response model for axisymmetric, round-mouth,
zero-extension OS-SE horns over 250–450 mm mouth diameters and 30–50 degree
coverage.

This is retained as the API-compatible legacy round reference estimator. A
later twelve-case full-grid challenge rejected all tested globally weighted
quadratic replacements, and a frozen nonlinear follow-up was worse on that
challenge. It is not a validated global interpolation surrogate. Future
geometry studies must use nearby measured round parents.

The six preregistered radiation diagnostics retain their original surface-score
definition. `throat_impedance_score` is an experimental seventh prediction for
future extension/throat-angle work and is not included in surface score,
benchmark ranking, or primary/augmented model choice.

The impedance response stored in this v1 model was fitted to the legacy
throat-impedance diagnostic. It is not comparable to the current diagnostic
v2.0.0 values shown in regenerated BEM reports and must not be used for current
impedance decisions. Rebuilding this model response is deferred; the radiation
responses are unaffected.

Off-grid mouth/coverage values use bilinear coefficient interpolation. Those
predictions remain uncertainty-labeled until a future real design confirms them.
Non-round, asymmetric, extended, squared, sagged, or non-6-degree-throat designs
are unsupported by this release.

Validation counts: 50 locked;
667 historical challenge.
