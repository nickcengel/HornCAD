# Bounded nonlinear round-surrogate decision

This is a simulation-free final test of whether the existing round evidence can
support useful interpolation. It does not attempt to rescue the ten-term
quadratic by adding more BEM.

Development evidence comprises the 1,234 unique compatible coordinates already
available across all 25 cells. The twelve round-control-v2 challenge responses
remain excluded while the candidate family, selection rule, and winning
hyperparameters are recorded.

Candidates are deliberately modest and portable:

- the unchanged ten-term quadratic under the same folds;
- nearest measured response;
- inverse-distance interpolation with 4, 8, or 12 neighbors;
- locally weighted affine interpolation with 12 or 20 neighbors;
- a ten-term quadratic plus a Gaussian radial-basis residual field at six
  fixed bandwidth/regularization settings.

Selection uses deterministic five-fold coordinate-grouped cross-validation.
A spatial checkerboard holdout is included at one-quarter weight to discourage
a method that succeeds only through extremely close neighbors. The six
radiation diagnostics are normalized and weighted equally. Experimental throat
impedance is predicted and reported but cannot affect selection, release, or
surface score.

After development selection is frozen, the winner is evaluated once against the
twelve existing challenge responses. It is released as the sole round baseline
only if all of these are true:

- surface-score MAE improves by at least 20% over the frozen quadratic;
- surface-score p90 absolute error improves by at least 20%;
- equal-diagnostic normalized MAE improves by at least 20%;
- no radiation diagnostic p90 error worsens by more than 10%.

The original v2 limits are also reported, but the material-improvement rule is
the release decision because this test asks whether nonlinear interpolation is
meaningfully better than the failed quadratic.

If the rule fails, no nonlinear model is released and global round-surrogate
work stops. Later geometry studies must use measured-parent comparisons rather
than spend more BEM trying to repair this baseline.
