# Experimental throat-impedance diagnostic

This diagnostic is deliberately isolated from live BEM search, ranking, and
reports. It is a prototype for the later conical-extension study.

The input is normalized throat-impedance magnitude from crossover through the
high sweep frequency. A constant magnitude is ideal, but the diagnostic accepts
any smooth high-pass-like rise. It does not prescribe a filter order or slope.

## Provisional measurements

The shelf reference is the 10% trimmed geometric mean over the final octave of
the sweep, or the final half of the available logarithmic band when less than
two octaves are available. This is harder for a single peak or trough to distort
than either a maximum or an ordinary arithmetic mean.

The crossover magnitude should be at least 50% of that shelf reference. The
crossover component saturates at 100% once this threshold is reached; excess
loading is not rewarded. Below the threshold, the component falls with the
square of the achieved fraction so materially underloaded crossovers do not
retain an undeservedly high score.

Smoothness is measured after fitting the best non-decreasing curve in dB on a
fixed 48-point-per-octave grid. This removes an arbitrary smooth high-pass trend
without choosing its slope. Residual RMS and 95th-percentile error measure
ripple. Excess total variation and reversal count identify repeated peaks and
troughs. The final shelf also records RMS deviation and remaining dB/octave
slope so a curve that never settles cannot look ideal merely because it rises
smoothly.

The experimental combined score weights crossover loading 40%, ripple 30%,
excess variation 20%, and shelf stability 10%. These weights and error reference
values are calibration hypotheses, not settled design criteria. Before using
the score in an extension search, compare its separate components against known
good and bad measured curves and adjust the references—not just the weights.

The prototype lives in `app/tools/throat_impedance_diagnostics.py` and has no
call site in production search or reporting code.
