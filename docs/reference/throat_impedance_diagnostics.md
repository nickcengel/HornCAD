# Experimental throat-impedance diagnostic

This experimental diagnostic is reported by BEM candidate, search, and study
reports, but remains isolated from the radiation surface score and candidate
ranking.

Version 2.1.0 uses the complete retained impedance sweep. A constant magnitude
is ideal, but the diagnostic accepts a smooth high-pass-like rise. It does not
prescribe a filter order or slope.

## Provisional measurements

The shelf reference is the 10% trimmed geometric mean over the upper half of
the crossover-to-high-sweep span on a logarithmic frequency axis. For a
500 Hz–8 kHz diagnostic band, that means 2–8 kHz. This is harder for a single
peak or trough to distort than either a maximum or an ordinary arithmetic mean,
while representing substantially more of the working passband than the final
octave alone.

The dominant crossover-loading component is scale-independent. It peak
normalizes the magnitude over the retained sweep and averages two measurements:

- magnitude at the registered crossover frequency;
- mean magnitude on a logarithmic frequency grid from the measured lower bound
  through one octave above crossover.

Each contributes half of the crossover-loading component. The component is
linear through 75% of the retained sweep peak and saturates there. Therefore,
75% or more earns full credit for the relevant point or band measurement and
there is no scoring benefit above it. The historical crossover-to-shelf ratio
and its 50% pass flag remain visible as supporting measurements, not as the
score transfer function.

Smoothness is measured after fitting the best non-decreasing curve in dB on a
fixed 48-point-per-octave grid. This removes an arbitrary smooth high-pass trend
without choosing its slope. Residual RMS and 95th-percentile error measure
ripple. Excess total variation and reversal count identify repeated peaks and
troughs. The final shelf also records RMS deviation and remaining dB/octave
slope so a curve that never settles cannot look ideal merely because it rises
smoothly.

The version 2 combined score weights crossover loading 80%, ripple 10%, excess
variation 7%, and shelf stability 3%. Shape terms can refine close cases but
cannot overwhelm crossover adequacy. These weights remain calibration
hypotheses; the diagnostic is still excluded from optimization and total score.

The implementation lives in `app/tools/throat_impedance_diagnostics.py`. The
round-control release pipeline now fits its overall percentage as an independent
experimental response for future extension/throat-angle work. It remains absent
from live search, candidate ranking, the radiation surface score, and
primary/augmented model choice.
