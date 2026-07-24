# Throat-impedance diagnostic

This diagnostic is reported by BEM candidate, search, and study reports. It
remains isolated from the radiation surface score and candidate ranking. A
secondary composite reports 75% surface v2.3 plus 25% throat impedance, but
that composite is not authoritative for ranking.

Version 2.3.0 uses the complete retained impedance sweep. A constant magnitude
is ideal, but the diagnostic accepts a smooth high-pass-like rise. It does not
prescribe a filter order or slope.

## Provisional measurements

The upper-band shelf reference is the 10% trimmed geometric mean over the upper half of
the crossover-to-high-sweep span on a logarithmic frequency axis. For a
500 Hz–8 kHz diagnostic band, that means 2–8 kHz. This is harder for a single
peak or trough to distort than either a maximum or an ordinary arithmetic mean,
while representing substantially more of the working passband than the final
octave alone. This component describes only the settled upper band. It does not
claim that crossover loading is broad or continuous.

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

Version 2.2 added a separate peak-prominence component so a narrow resonance
cannot inflate both loading measurements without consequence. Peak prominence
is the retained-sweep peak in dB above the upper-band shelf reference. The first
1.5 dB is allowed; excess prominence is scored against a 1.5 dB reference with
the same inverse-square transfer used by the other error terms. A broad,
well-loaded transition can therefore score well, while a high crossover point
created by an isolated peak is strongly penalized.

Version 2.3 closes a remaining loophole: a local peak can be close to the
distant upper-shelf level while still rising sharply above its immediate
shoulders. The diagnostic smooths the full retained sweep on the standard
48-point-per-octave logarithmic grid, finds interior local maxima, and measures
each against the higher of the minima reached within one octave on either
side. Peak control uses the worse of this local prominence and global
peak-to-upper-shelf prominence. Boundary maxima are left to crossover loading
and the global shelf comparison because they do not have two measured
shoulders.

Smoothness is measured after fitting the best non-decreasing curve in dB on a
fixed 48-point-per-octave grid. This removes an arbitrary smooth high-pass trend
without choosing its slope. Residual RMS and 95th-percentile error measure
ripple. Excess total variation and reversal count identify repeated peaks and
troughs. The final shelf also records RMS deviation and remaining dB/octave
slope so a curve that never settles cannot look ideal merely because it rises
smoothly.

The version 2.3 combined score weights crossover loading 60%, peak prominence
20%, ripple 10%, excess variation 7%, and upper-shelf stability 3%. Crossover
adequacy remains dominant, but no longer drowns out a conspicuous isolated
resonance. These weights remain calibration hypotheses. The diagnostic is
excluded from optimization and from the authoritative surface ranking.

The implementation lives in `app/tools/throat_impedance_diagnostics.py`. The
round-control release pipeline now fits its overall percentage as an independent
experimental response for future extension/throat-angle work. It remains absent
from live-search ranking, the radiation surface score, and primary/augmented
model choice. Its only combined use is the explicitly secondary composite
described in
[`composite_diagnostics.md`](composite_diagnostics.md).
