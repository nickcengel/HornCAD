# Horn design application API

## Purpose

This is the stable application boundary around the current control-decoupling
study and later extension, mouth-shape, H/V, sag, and throat-angle models. Raw
NPZ evidence feeds model fitting. Version 1 callers consume predictions; the
types reserve room for later diagnoses, recommendations, and proposed
confirmation experiments.

The Python implementation lives in `app.design_api`. It validates public inputs
and outputs and can load either retained v1 artifact. Primary v1 is the
API-compatible legacy reference estimator; augmented v1 is a research
comparison. Neither passed validation as a dependable global interpolation
foundation. Prediction is implemented with an explicit measured-parent warning;
diagnosis, improvement, automated design, and experiment selection remain
deliberately deferred.

This portable interface is not the measured horn optimizer. Practical automated
design is implemented separately by `app.horn_optimizer`: it proposes one fixed
intent, runs/reuses BEM responses, ranks measured surface v2.3 and throat-
impedance v2.3.0 results, and emits a BEM-confirmed project/STL. It does not
claim that the v1 portable model predicts its winner.

All v1 predictions now report `LIMITED` support, even at nominally in-domain
coordinates. Out-of-range geometry continues to report `EXTRAPOLATED` or fail
validation as appropriate.

Measured seed generation is separate from score prediction:

```python
from app.design_api import DesignIntent, RoundControlHeuristics

rules = RoundControlHeuristics.load("models/round_control_heuristics_v1")
seed = rules.recommend(DesignIntent(400, 300, 50, 35))
```

This returns independent H/V measured-axis seeds, a flat weighted length, and a
geometric cylindrical-sag alternative. See
`docs/reference/round_control_heuristics.md`.

## Most common calls

Open the current evidence source:

```python
from app.design_api import Study

study = Study.open("examples/control-decoupling")
print(study.study_id)
```

Load a released model and predict one known design:

```python
from app.design_api import DesignApplication, DesignPoint

app = DesignApplication.load("models/round_control_primary_v1")
candidate = DesignPoint.round(
    mouth_mm=300,
    coverage_deg=40,
    profile_length_mm=145,
    k=4.0,
    n=8.0,
)
prediction = app.predict(candidate)

print(prediction.surface_score.mean)
print(prediction.diagnostics["slice_energy_rms_departure"])
print(prediction.derived_geometry["s_horizontal"])
print(prediction.support, prediction.nearest_evidence_ids)
print(prediction.diagnostics["throat_impedance_score"])
print(prediction.model_predictions)
```

`profile_length_mm` always means OS-SE profile length. Extension and sag are
separate inputs. S and other supported geometry summaries are outputs. In the
zero-extension, zero-sag v1 round model, `total_length_mm` equals
`profile_length_mm`.

Loading augmented v1 still exposes its historical cell-router behavior for
reproducibility, but new application work should load primary v1. The completed
unified-v2 challenge did not justify replacing it.

The round-control models were trained against the originally registered surface
score v1, so `prediction.surface_score` remains a v1 prediction. Current BEM
reports and optimizer ranking use measured surface v2.3. The API does not
silently reinterpret a v1 model output as v2.3; a future portable model release
must add an explicitly named response after rebuilding its training evidence.

## Deferred operations

The public types reserve diagnosis, improvement, automated design, and
experiment selection, but the v1 backend does not implement them. Calls such as
the following currently raise `ModelNotReadyError`:

```python
from app.design_api import DesignConstraints, Objective

diagnosis = app.diagnose(candidate)

options = app.improve(
    candidate,
    objectives=(
        Objective("slice_energy_rms_departure", "minimize", weight=2),
        Objective("surface_score", "maximize", weight=1),
    ),
    constraints=DesignConstraints(
        profile_length_mm=(120, 190),
        k=(2, 6),
        n=(3, 16),
        minimum_surface_score=80,
    ),
    limit=5,
)
```

Future model-only recommendations will remain unconfirmed until BEM evaluates
them. Support status, uncertainty, and nearest evidence must stay visible.
These deferred methods are not alternate implementations of
`horn_optimizer`. The measured optimizer can be used now without implementing
them. Throat impedance remains independent of radiation surface score; the
optimizer uses it only as its configurable measured shortlist tiebreak.

## General H/V and future geometry

The convenience constructors above describe symmetric round horns. The base
types already preserve independent axes and future controls:

```python
from app.design_api import DesignIntent, DesignPoint

rectangular = DesignPoint(
    intent=DesignIntent(
        mouth_width_mm=400,
        mouth_height_mm=250,
        horizontal_coverage_deg=50,
        vertical_coverage_deg=35,
    ),
    profile_length_mm=170,
    k_horizontal=4.5,
    n_horizontal=8,
    k_vertical=3.5,
    n_vertical=10,
    extension_mm=40,
    throat_angle_deg=8,
    mouth_squareness=1,
    sag_mm=20,
)
```

Later model releases may implement these coordinates as validated correction
layers over the round baseline. The call site does not need to change when the
backend changes from the round model to a layered model bundle.

## API separation

- `Study` identifies authoritative evidence. The release pipeline assembles
  rescored datasets by declared role.
- `DesignApplication.predict()` evaluates a specified design.
- `diagnose()`, `improve()`, `design()`, and `select_experiments()` are reserved
  model-only operations deferred in v1; they do not execute or replace the
  measured optimizer.
- `app.horn_optimizer` owns restartable candidate construction, BEM execution,
  exact-response reuse, measured ranking, simulation accounting, and winner
  artifacts.
- The backend owns model evaluation, uncertainty, geometry gating, and layered
  correction models. Python and browser backends must produce equivalent
  outputs.

The fitting/export process remains governed by the control study's
`model_pipeline.md`. This API is its consumer contract, not an alternate fitting
specification.
