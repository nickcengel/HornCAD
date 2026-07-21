# Archived 200 mm BEM study summary

The 200 x 200 mm square-mouth studies were removed from the active example set
on 2026-07-21 when the supported mouth range was formalized as 250 through
500 mm. Full reports, STL files, search ledgers, and candidates remain
recoverable from Git history through commit `e25e9a832` and its ancestors.
These results are not used for active ranking, interpolation, or scheduling.

| Coverage | Study | Completed candidates | Best surface score | Length mm | S | K | N |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 25° | original | 5 | 66.861 | 143.000 | 1.048 | 4 | 10 |
| 25° | S grid | 9 | 66.945 | 145.435 | 1.000 | 4 | 10 |
| 35° | original | 5 | 74.831 | 111.000 | 1.155 | 4 | 10 |
| 35° | S grid | 7 | 74.798 | 115.722 | 1.000 | 4 | 10 |

The optimized 200 mm scores were approximately four points below 250 mm at
25° and five points below 250 mm at 35°. Both S sweeps placed their best point
near S=1 rather than at the high-S boundary. This is sufficient lower-mouth
boundary evidence for the current acoustic band; the unstarted 30°/200 mm case
was therefore removed rather than simulated.
