# HornCAD Local Workspace Plan

## Goal

Turn the existing HornCAD browser designer and FEM command-line tools into a
coherent local workspace for one user on the current Apple Silicon machine.
The workspace should make it pleasant to design a horn, run an analysis, review
interactive results, and compare designs without typing Python commands or full
filesystem paths.

This is an intermediate product, not a portable desktop application. It may use
a small Python service running locally and the existing browser UI.

## User experience

HornCAD becomes one locally served application with internal pages:

1. **Design** — acoustic-surface geometry controls and interactive acoustic
   surface preview.
2. **Manufacture** — printable-body parameters, mounting features, and body
   export preview derived from the acoustic surface.
3. **Simulation** — FEM settings, estimated job size, run/resume/cancel controls,
   and progress.
4. **Results** — interactive coverage and impedance plots for the selected run,
   accompanied by the horn preview and identifying design information.
5. **Compare** — select several saved designs/runs and overlay their response
   curves with consistent colors, names, and horn thumbnails or previews.
6. **Project** — project identity, notes, file locations, saved runs, and basic
   maintenance actions.

The boundary between the first two pages is intentional:

- **Design defines the acoustic surface:** throat, OS-SE basis profiles, mouth
  dimensions and sag, section shape, and acoustic profile modifiers.
- **Manufacture defines the physical body around that surface:** wall thickness,
  rear offsets, flange and mount geometry, fillets, screw holes, printable-body
  sampling, and body STL export.

Manufacturing parameters must not alter the acoustic surface. Acoustic analyses
use the Design geometry and remain independent of whether a printable body has
been configured or exported.

The app should remember a local project library. Normal use should involve
selecting projects and runs by name rather than entering paths.

## Plot requirements

Replace static review PNGs as the primary interface with interactive plots.
Plotly is the initial preferred plotting library because it directly supports
the required heatmaps and curves.

- Frequency is logarithmic everywhere, like a Bode plot.
- Coverage heatmaps place angle on the vertical axis and frequency on the
  horizontal axis.
- Human-readable angle ticks use 0, 15, 30, 45, 60, 75, and 90 degrees.
- Show a -6 dB contour or curve whenever applicable.
- Throat impedance is magnitude only by default; do not plot reactance.
- Provide zoom, pan, hover/cursor values, trace visibility, and useful scale
  controls.
- Preserve downloadable static figures as optional reports, not the main way
  results are explored.

The Results and Compare pages must keep geometry and response identity visually
connected. Each plotted design should have a clear name, matching color, key
dimensions, and an accessible 3D preview or thumbnail.

## Project model

The exported YAML evolves into a project file rather than only a geometry
transfer file. Geometry remains the source of truth, while optional sections add
human-facing metadata and analysis defaults. Existing geometry-only YAML files
must continue to load.

Illustrative additions:

```yaml
horncad_config:
  type: HornCAD
  version: 3
  project:
    id: osse-400x280-k30-k18
    name: OS-SE 400 x 280 K30-K18
    notes: Initial directivity study
  analysis:
    fem:
      start_hz: 500
      stop_hz: 5000
      points_per_octave: 12
      elements_per_wavelength: 8
      quadrant_symmetry: true
```

Do not embed meshes, field arrays, or response arrays in YAML. A run manifest
links immutable inputs, numerical settings, status, and generated artifacts.
The existing YAML fingerprint and solver fingerprint remain part of run
compatibility checks.

## Files and names

Use stable, readable project and run directories instead of loose files in
`analysis/`:

```text
projects/
  osse-400x280-k30-k18/
    project.yaml
    geometry/
      acoustic-surface.stl
    runs/
      fem-500-5k-8epw/
        run.json
        mesh/
        fields/
        results/
          responses.npz
          metrics.csv
          figures/
```

- A project slug identifies the design; display names may be changed freely.
- A run name summarizes the method and important numerical range.
- `run.json` records complete settings and status so a run is reproducible.
- Large generated meshes and raw fields remain local/ignored unless there is a
  deliberate reason to version them.
- Migration should register existing studies without destroying or silently
  relocating their source data.

## Local architecture

Keep the current HTML/JavaScript geometry implementation and add a small local
Python service. The service launches from a short project command or clickable
launcher and opens a loopback address such as `http://localhost:8765`.

The service is responsible for:

- indexing and opening projects;
- reading and safely updating project YAML;
- creating named run directories and manifests;
- invoking `run_fem_suite.py` with bounded M1 Ultra defaults;
- reporting progress and completed frequencies;
- resuming and cancelling jobs safely;
- serving compact response data to interactive plots;
- invoking existing STL export and comparison/report tools when requested.

The numerical implementations remain separate from the UI. The service wraps
the currently validated tools rather than duplicating solver logic:

- `export_horncad.py` for STL generation;
- `run_fem_suite.py` for the reduced 3D FEM pipeline;
- `generate_fem_review.py` for report artifacts;
- `compare_fem_reviews.py` for existing comparison output.

The current validated FEM ceiling remains 5 kHz at the accepted resolution
until the distributed pressure backend described in
`docs/fem_parallel_pressure_backend.md` is implemented and validated.

## Implementation plan

### Phase 1 — Organize the existing app

- Add internal Design, Manufacture, Simulation, Results, Compare, and Project
  navigation.
- Move acoustic-surface controls into Design and printable-body controls into
  Manufacture without changing geometry math.
- Give Manufacture its own body preview mode while retaining the acoustic
  surface as the immutable design reference.
- Keep the 3D preview responsive and avoid recomputing export geometry while a
  parameter is dragged.
- Add empty but clearly labeled shells for the later pages.

**Complete when:** existing design/edit/export behavior is preserved; acoustic
and manufacturing parameters are clearly separated; each page is usable at
normal window sizes; and navigation does not reset either parameter set.

### Phase 2 — Define projects and runs

- Add backward-compatible `project` and `analysis` YAML sections.
- Define and validate `run.json`.
- Implement readable project/run naming and the proposed directory layout.
- Add migration/registration support for an existing YAML and FEM review folder.

**Complete when:** a geometry-only YAML can be opened, saved as a project, and
reopened with analysis defaults intact; existing test studies can be registered
without rerunning FEM.

### Phase 3 — Add the local service

- Serve the application and project index on loopback only.
- Provide project, run, status, cancel, response-data, and STL-export operations.
- Launch solver processes with explicit resource limits and capture their logs.
- Ensure interrupted runs remain resumable through existing atomic outputs.

**Complete when:** the user can launch HornCAD with one short action, choose a
project, and inspect its known runs without entering a filesystem path.

### Phase 4 — Run FEM from the Simulation page

- Expose the useful settings: frequency range, points per octave, elements per
  wavelength, symmetry, worker count, and mesh threads.
- Start or resume `run_fem_suite.py` and display mesh/sweep progress.
- Warn clearly about settings above the validated 5 kHz backend limit.
- Show errors and logs in a useful form without presenting Python internals as
  the normal interface.

**Complete when:** a standard 500 Hz–5 kHz study can be configured, run,
interrupted, and resumed entirely from the app.

### Phase 5 — Interactive Results

- Convert `responses.npz` and `metrics.csv` into browser-consumable compact data.
- Implement interactive H/V coverage heatmaps, -6 dB coverage curves, and
  magnitude-only throat impedance.
- Add plot controls, cursor readings, geometry metadata, and 3D preview linkage.
- Retain generation of the current standard PNG reports.

**Complete when:** a saved run can be understood and inspected interactively
without opening a PNG or running a plotting script.

### Phase 6 — Interactive Compare

- Select two or more registered runs.
- Overlay H/V -6 dB coverage and impedance magnitude with stable colors.
- Show the corresponding design names, dimensions, and previews/thumbnails.
- Handle different frequency samples by interpolation only for display, while
  retaining the original numerical data and labeling the common range.

**Complete when:** the existing `test`, `test2`, `test3`, and `test4` studies can
be selected and compared from the app with unambiguous design identity.

### Phase 7 — Consolidate and migrate

- Register valuable existing `analysis/` studies in the project library.
- Improve names where the mapping to source YAML is known.
- Document backup, relocation, and cleanup behavior.
- Remove obsolete duplicate entry points only after the replacement workflow is
  proven.

**Complete when:** routine design and FEM review no longer require terminal
commands or manually managed full paths.

## Constraints and decisions

- Optimize for this user and M1 Ultra; broad packaging and cross-platform
  distribution are not current goals.
- Keep solver processes outside the browser so crashes do not lose the design or
  project state.
- Preserve reproducibility: every result must identify its exact geometry,
  settings, solver, and status.
- Preserve quadrant symmetry and bounded parallel frequency solves as the normal
  efficient 500 Hz–5 kHz workflow.
- Do not combine the parallel-pressure-backend research with the workspace UI
  work. The UI may expose future capability once that backend is validated.
- Implement in vertical slices and keep the current CLI usable throughout.

## Recommended next action

Begin Phase 1 only: introduce internal page navigation and reorganize the
existing HornCAD interface without changing geometry, YAML, or FEM behavior.
This provides immediate usability improvement and a stable visual structure for
the project and results capabilities that follow.
