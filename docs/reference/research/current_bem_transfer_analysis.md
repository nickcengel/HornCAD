# BEM transferable-response audit

This audit uses 689 completed candidates in 25 retained mouth/coverage cells. Entire cells are held out during validation; dense local samples cannot leak into their own test set.

Three normalized radial-profile modes retain 99.915% of measured profile variance. K, N, and S are retained as steering labels but are not model coordinates: they only matter through the horn surface they create.

| Diagnostic | Held-cell MAE | RMSE | R² |
| --- | ---: | ---: | ---: |
| score | 1.428 | 2.081 | 0.903 |
| mean_containment | 0.140 | 0.177 | 0.998 |
| profile_rms_error_db | 0.070 | 0.096 | 0.930 |
| slice_energy_departure_db | 0.078 | 0.113 | 0.873 |
| outward_rise_violation_db | 0.128 | 0.192 | 0.918 |
| minus_six_rms_error_deg | 0.476 | 0.644 | 0.966 |
| high_frequency_coverage_error_deg | 0.864 | 1.173 | 0.831 |

## Largest transfer gaps

- **score:** 250 mm/30° (RMSE 7.94), 250 mm/50° (RMSE 3.61), 300 mm/30° (RMSE 3.21), 250 mm/35° (RMSE 2.72), 400 mm/35° (RMSE 2.68).
- **mean_containment:** 250 mm/30° (RMSE 0.47), 450 mm/50° (RMSE 0.33), 300 mm/30° (RMSE 0.27), 450 mm/35° (RMSE 0.25), 250 mm/50° (RMSE 0.24).
- **profile_rms_error_db:** 250 mm/30° (RMSE 0.31), 400 mm/35° (RMSE 0.17), 300 mm/30° (RMSE 0.15), 250 mm/50° (RMSE 0.14), 250 mm/40° (RMSE 0.12).
- **slice_energy_departure_db:** 250 mm/30° (RMSE 0.44), 250 mm/50° (RMSE 0.19), 250 mm/40° (RMSE 0.16), 250 mm/35° (RMSE 0.16), 300 mm/30° (RMSE 0.14).
- **outward_rise_violation_db:** 300 mm/30° (RMSE 0.48), 250 mm/30° (RMSE 0.37), 300 mm/35° (RMSE 0.33), 250 mm/50° (RMSE 0.28), 250 mm/35° (RMSE 0.27).
- **minus_six_rms_error_deg:** 250 mm/30° (RMSE 1.65), 250 mm/35° (RMSE 1.10), 250 mm/40° (RMSE 0.96), 300 mm/30° (RMSE 0.93), 450 mm/40° (RMSE 0.90).
- **high_frequency_coverage_error_deg:** 250 mm/30° (RMSE 3.38), 450 mm/50° (RMSE 2.55), 250 mm/50° (RMSE 1.76), 250 mm/35° (RMSE 1.50), 450 mm/45° (RMSE 1.45).

These gaps, combined with physical novelty and a matched existing contrast, determine the next measured batch. Matrix rank alone does not.
