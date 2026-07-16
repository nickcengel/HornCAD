# OS-SE 400 × 280 reference

This is HornCAD's maintained reference project.

- `project.yaml` — source project.
- `bem-search.yaml` — example quick candidate-search configuration.
- `acoustic-surface.stl` — open acoustic surface exported from the project.
- `fem/` — interior FEM result: 500–5000 Hz, 12 points per octave, 6 elements
  per wavelength. It retains `responses.npz`, `metrics.csv`, and
  `mesh_report.json`.
- `bem/` — free-air NumCalc BEM result generated 2026-07-15: 500–5000 Hz, 10
  points per octave, 6 elements per wavelength, 35 frequencies, 91 observation
  angles, and 7,897 quadrant panels. NumCalc applies two hard mirror
  symmetries. The all-inclusive mesh-to-report wall time was 58.625 seconds on
  the 20-core reference Mac. It retains `responses.npz` and `metrics.csv`.
- `bem-fem-comparison/interactive_report.html` — interactive overlay of the
  retained FEM and BEM −6 dB H/V coverage and normalized throat impedance.

Open either `interactive_report.html` for cursor-enabled coverage and
normalized magnitude-only throat impedance. The compact numerical files support
report regeneration and comparison; bulky meshes and per-frequency working
directories are deliberately excluded.

Each report is accompanied by `coverage_diagnostics.json`, containing the
automatic evaluated passband plus horizontal, vertical, and combined coverage
match, smoothness, and non-narrowing values. The FEM/BEM comparison recomputes
both runs over their shared 839–5000 Hz band rather than comparing scores from
different automatic passbands.
