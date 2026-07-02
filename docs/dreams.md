# HornCAD Dreams

This document captures intended future tools and workflows that would help
HornCAD move from single-project refinement toward design-space learning.

## Acoustic Evaluation Adapter

Add an external acoustic evaluation path for finished candidate horns.

Initial assumptions:

- model the horn in free air
- preserve the actual mouth geometry, including non-planar mouth exits
- use a simple flat wave / prescribed velocity condition at the throat
- do not model driver diaphragm, suspension, phase plug, cabinet, or baffle
- prioritize normalized directivity over absolute on-axis response
- stop around 15 kHz unless a specific design requires more bandwidth

Useful outputs:

- normalized horizontal and vertical directivity
- beamwidth vs frequency
- pressure at authored coverage angle vs frequency
- estimated frequency where target coverage reaches `-3 dB` or `-6 dB`
- narrowing rate after pattern control begins
- major directivity ripple or resonance warnings
- optional acoustic impedance plot

The acoustic results should be treated as comparative design evidence, not as a
promise of final measured loudspeaker response. The primary value is holding
assumptions constant while comparing candidate horn geometries.

Potential solver paths:

- `Bempp-cl`: Python-facing BEM library; likely best first API prototype.
- `Mesh2HRTF / NumCalc`: BEM pipeline with directional output concepts; may
  require adapting an HRTF-oriented workflow to horns.
- `openCFS`: serious FEM option for later validation, impedance, and resonance
  studies; likely heavier than the first prototype needs.
- `Gmsh`: likely meshing bridge for any external solver path.

HornCAD-side scaffolding:

- export clean acoustic boundary meshes
- define throat source boundary
- define rigid horn-wall boundaries
- define far-field receiver cuts or receiver sphere
- run sparse frequency sweeps first
- parse solver output into HornCAD plots and metrics

Full acoustic simulation should be an outer-loop evaluation for selected
candidate horns, not an inner-loop objective for every geometry candidate.

## Mouth And Coverage Atlas

Add a research mode that generates indicative horn families to study the
relationship between:

- horizontal coverage half-angle
- vertical coverage half-angle
- mouth width
- mouth height
- mouth aspect ratio
- horn length
- corner radius
- roundover contribution

The point is to discover useful design relationships before committing to a
specific project. The output does not need to be a polished report at first.

Example sweep axes:

| Axis | Example Values |
| --- | --- |
| H coverage half-angle | `40`, `50`, `60`, `70` deg |
| V coverage half-angle | `20`, `30`, `40`, `50` deg |
| mouth aspect ratio | wide, square-ish, tall |
| mouth area | fixed area or varying area |
| length | `100`, `150`, `200` mm |
| corner radius | small, medium, large |

Useful geometry outputs:

- principal H/V profile plots
- area expansion plots
- roundover contribution tables
- solved parameter tables
- invalid or infeasible case summaries

Useful acoustic outputs, once an acoustic adapter exists:

- pattern-control onset frequency
- beamwidth vs frequency
- normalized pressure at target coverage angle
- narrowing rate above control onset
- directivity smoothness or ripple metrics

The atlas should help answer questions like:

- what mouth width tends to support a target H coverage?
- what mouth height tends to support a target V coverage?
- how much does length change the acceptable design space?
- when does a requested coverage become geometrically possible but acoustically
  poor?
- which geometric metrics correlate with useful pattern-control behavior?

## OS-SE Family Mapper

Add a geometry research mode that maps the valid OS-SE curve family between
fixed endpoints.

Inputs:

- throat geometry
- mouth geometry
- fixed horn length
- fixed horizontal and vertical coverage half-angles
- profile parameter ranges
- roundover contribution targets or reporting thresholds

Behavior:

- sweep OS-SE parameter combinations
- solve only candidates that terminate on the mouth boundary
- reject curves that violate hard constraints
- classify the remaining valid curve family
- report how parameter choices affect visual shape and area behavior

Core questions:

- what does increasing `N` do when endpoints are fixed?
- when does `Q` behave like endpoint stretch?
- how much does `K` change profile shape and area fit?
- how much internal `S` is required to reach the mouth boundary?
- which parameter combinations create smooth credible profiles?
- which combinations hit the boundary but produce poor area expansion?
- which geometry metrics later correlate with better directivity?

Useful outputs:

- overlaid valid H profile family
- overlaid valid V profile family
- area expansion family plot
- parameter table for each valid candidate
- rejection summary for invalid candidates
- roundover contribution vs parameter plots
- mouth tangent / terminal slope diagnostics

This should make the optimizer more understandable. Instead of only returning a
single best candidate, HornCAD should be able to show the legal design space and
the tradeoffs inside it.

## Future Command Shapes

Possible command names:

```bash
python -m horncad.explore <project.yaml>
python -m horncad.atlas <project.yaml>
python -m horncad.acoustics <project.yaml>
```

Possible output folders:

```text
explore_review/
atlas_review/
acoustic_review/
```

These are placeholders, not current implemented interfaces.
