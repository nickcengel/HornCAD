# Horn design application API

## Purpose

This is the stable application boundary around the current control-decoupling
study and later extension, mouth-shape, H/V, sag, and throat-angle models. Raw
NPZ evidence feeds model fitting; application callers consume predictions,
diagnoses, recommendations, and proposed confirmation experiments.

The Python implementation lives in `app.design_api`. It validates public inputs
and outputs and loads the released primary or augmented round-control
`model.json`. Prediction is implemented; diagnosis, improvement, automated
design, and experiment selection remain deliberately deferred.

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

app = DesignApplication.load("models/round_control_v1")
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
print(prediction.model_predictions)  # primary and augmented side by side
```

`profile_length_mm` always means OS-SE profile length. Extension and sag are
separate inputs. S and total length are solved geometry outputs.

Diagnose why a candidate behaves poorly:

```python
diagnosis = app.diagnose(candidate)

for issue in diagnosis.issues:
    print(issue)
for control, effects in diagnosis.control_sensitivities.items():
    print(control, effects)
```

Find related candidates predicted to improve specific diagnostics:

```python
from app.design_api import DesignConstraints, Objective

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

for option in options:
    print(option.prediction.design, option.expected_deltas, option.rationale)
```

Generate designs from only mouth and coverage intent:

```python
from app.design_api import DesignIntent

leaders = app.design(
    DesignIntent.round(mouth_mm=350, coverage_deg=45),
    constraints=DesignConstraints(profile_length_mm=(120, 220)),
    limit=5,
)
```

Choose the next BEM simulations for information rather than marginal score:

```python
experiments = app.select_experiments(
    intents=(
        DesignIntent.round(300, 40),
        DesignIntent.round(350, 45),
    ),
    constraints=DesignConstraints(k=(2, 6), n=(3, 16)),
    budget=12,
)
```

Every predicted recommendation remains unconfirmed until BEM evaluates it.
Support status, uncertainty, and nearest evidence must stay visible to callers.
The experimental throat-impedance score remains independent and is not included
in the radiation surface score or normal-model selection.

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

- `Study` identifies authoritative evidence and eventually assembles rescored
  datasets by declared role.
- `DesignApplication.predict()` evaluates a specified design.
- `diagnose()` explains the predicted diagnostic state and local sensitivities.
- `improve()` stays near a supplied design and exposes tradeoffs.
- `design()` searches the supported domain for a mouth/coverage request.
- `select_experiments()` proposes simulations that reduce uncertainty or test
  competing control explanations.
- The backend owns model evaluation, uncertainty, geometry gating, and layered
  correction models. Python and browser backends must produce equivalent
  outputs.

The fitting/export process remains governed by the control study's
`model_pipeline.md`. This API is its consumer contract, not an alternate fitting
specification.
