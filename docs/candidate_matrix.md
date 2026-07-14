# HornCAD Candidate Matrix Plan

## Purpose

HornCAD needs a repeatable way to compare valid horn geometries before connecting them to an acoustic simulator or optimizer. The first objective is a controlled candidate matrix that separates geometric effects and produces consistent measurements.

The study will hold authored mouth width, mouth height, total physical length, and coverage constant. It will explore OS-SE parameters, conical throat extensions, and cross-section morph schedules while deriving the termination amplitude required to reach the mouth.

## Terminology

`K` is not a direct conic-to-exponential selector. In HornCAD's current OS-SE basis equation, `K = 0` produces the conical base profile. Increasing `K` changes expansion near the throat. The termination term then bends that base profile to reach the fixed mouth.

An exponential horn should eventually be implemented as a separate reference profile, not represented by labeling a high-`K` OS-SE profile as exponential.

## Authored, Explored, and Derived Values

### Authored and held constant

- mouth width `W`;
- mouth height `H`;
- total physical length `L_total`;
- horizontal and vertical coverage;
- throat diameter and angle.

Coverage is an authorial constraint. Candidate fitting must not silently change it to make a profile feasible.

### Exploration variables

- horizontal and vertical `K`;
- horizontal and vertical `N`;
- conic-extension fraction and exit angle;
- squareness-morph start and easing.

### Derived values

- conic-extension length;
- remaining OS-SE profile length;
- effective throat radius after the extension;
- horizontal and vertical `S`;
- complete acoustic surface.

The intended length relationship is:

```text
L_profile = L_total - L_conic
```

The current app does not yet treat its length control this way consistently. Until corrected, the experiment runner must normalize total and profile length explicitly.

## Candidate Generation Policy

For each candidate:

1. Hold `W`, `H`, `L_total`, throat geometry, and H/V coverage fixed.
2. Apply the requested conic extension.
3. Calculate the effective throat radius and remaining OS-SE length.
4. Apply candidate values for `K_H`, `K_V`, `N_H`, and `N_V`.
5. Derive `S_H` and `S_V` so the profiles reach the fixed mouth dimensions.
6. Reject invalid basis profiles.
7. Generate and validate the three-dimensional acoustic surface.
8. Pass only valid candidates to acoustic simulation.
9. Record results without changing authored constraints.

The fitting priority is:

1. preserve coverage;
2. preserve `W`, `H`, and `L_total`;
3. explore `K`;
4. derive `S` for every candidate;
5. use `N` to control where termination curvature occurs;
6. reject infeasible candidates;
7. rank valid candidates geometrically and acoustically.

`S` is not an independent axis in the initial matrix. It is an outcome of the fixed endpoint and the candidate's `K`, `N`, length, and coverage. The study should nevertheless report the transition from `S = 0` through moderate positive values to impractically large values.

## Validity Gates

Candidates must pass inexpensive profile checks before mesh generation and mesh checks before acoustic simulation.

### Basis-profile checks

- positive remaining OS-SE length;
- finite, positive radii;
- monotonically expanding H/V profiles;
- no local profile reversal;
- mouth endpoint error within tolerance;
- bounded `S`, slope, and curvature;
- slope continuity at the conic-to-OS-SE junction;
- no severe curvature spike at that junction.

The initial study should require `S >= 0`. A later study may deliberately investigate negative `S`, but it should not enter the baseline matrix accidentally.

### Surface and mesh checks

- no self-intersections;
- consistent section ordering;
- finite vertices and faces;
- consistent normals and winding;
- one connected acoustic surface where expected;
- watertightness for printable bodies;
- correct throat and mouth boundary dimensions.

Endpoint fit is a hard constraint. Valid candidates can then be ranked geometrically:

```text
geometric_score =
    monotonicity_penalty
  + curvature_spike_penalty
  + slope_discontinuity_penalty
  + extreme_s_penalty
  + mesh_quality_penalty
```

Acoustic results should remain separate initially. Combining scores too early would hide why a candidate succeeded or failed.

## Initial Parameter Levels

| Variable | Initial levels |
| --- | --- |
| `K_H`, `K_V` | `0, 0.5, 1, 2, 5, 10` |
| `N_H`, `N_V` | `2, 3, 4, 6, 10` |
| Conic fraction | `0%, 10%, 25%, 40%` of `L_total` |
| Conic exit angle | `0.5x, 1x, 2x` throat half-angle |
| Morph start | `0%, 25%, 50%, 75%` of `L_total` |
| Morph character | fast, neutral, slow |

Exit angles must be capped at a physically sensible maximum. The first pass should use symmetric parameters (`K_H = K_V` and `N_H = N_V`). H/V values should be decoupled only after viable symmetric regions are known.

## Staged Experiment Matrix

### Phase A: Basis-profile map

Purpose: identify the viable `K` and `N` region without extension or morph interactions.

Use no conic extension and neutral cross-section treatment:

```text
6 K levels x 5 N levels = 30 candidates
```

Record derived `S_H` and `S_V`, endpoint error, slope range, curvature peaks and locations, monotonicity, validity, and rejection reason. This establishes where the design produces near-zero, moderate, and extreme termination amplitudes.

### Phase B: Conic-extension study

Purpose: observe how a conical segment and shortened OS-SE segment change required `K`, derived `S`, and junction behavior.

Select three representative valid Phase A results:

- a nearly conical base near `K = 0`;
- a middle case near `K = 1`;
- a higher-`K` case with slower initial expansion.

Test each against:

```text
conic fraction: 0%, 10%, 25%, 40%
exit angle:     0.5x, 1x, 2x throat half-angle
```

This gives 36 raw candidates, including no-extension cases that can be deduplicated. Record effective throat radius, remaining profile length, derived `S`, best viable `K`, junction slope mismatch, nearby curvature, and eventually acoustic response.

A mesh may be topologically valid while retaining a sharp acoustic discontinuity, so slope and curvature continuity are essential measurements.

### Phase C: Squareness-morph study

Purpose: separate basis-profile behavior from area-expansion effects of the circular-to-rectangular transition.

| Schedule | Description |
| --- | --- |
| Immediate | Begins at the throat and is mostly complete early |
| Linear | Begins at the throat and progresses uniformly |
| Gentle | Begins at the throat and progresses slowly over the full length |
| Delayed | Begins halfway along the total length |
| Late | Begins near 75% and changes rapidly near the mouth |

Morph start and easing are independent. A morph can begin early but remain nearly circular until late, or begin late and change rapidly.

Record section area versus axial position, first and second area differences, local shape change, mesh quality, and acoustic response. Visual smoothness is insufficient: two smooth-looking morphs can have substantially different area derivatives.

### Phase D: H/V decoupling

Purpose: explore rectangular behavior after viable scalar regions are established.

Perturb the best symmetric candidates with:

```text
K_H / K_V: 0.5, 1, 2
N_H / N_V: 0.5, 1, 2
```

Keep H/V coverage fixed. Select a sparse set around the best symmetric cases rather than running the full cross-product immediately.

## Recommended First Campaign

- 30 no-extension `K x N` basis cases;
- 12 to 18 deduplicated extension cases around three good bases;
- 15 morph cases around three good extended or unextended profiles;
- 12 H/V-decoupled cases.

This is roughly 70 candidates before automatic rejection: enough to expose broad trends while remaining understandable and inexpensive to inspect.

## Candidate Record

Every run should emit a machine-readable record containing:

```text
candidate ID and base design ID
authored W, H, and L_total
throat diameter and angle
horizontal and vertical coverage
K_H, K_V, N_H, and N_V
derived S_H and S_V
conic length, fraction, and exit angle
morph schedule and control points
profile validity results
slope and curvature metrics
area-versus-position samples
surface and mesh validity results
rejection reason, if any
mesh path
acoustic solver and version
acoustic metrics
geometric and acoustic scores
```

Generation must be deterministic. The candidate ID should derive from the normalized configuration or be paired with a content hash so results can be reproduced.

## Acoustic Modeling Interface

The browser should remain the interactive design interface. A separate Python experiment runner should:

1. load a base HornCAD YAML file;
2. normalize length and other authored constraints;
3. apply one candidate permutation;
4. derive `S` and validate the profiles;
5. generate and validate the acoustic surface;
6. invoke the selected acoustic solver;
7. store configuration, metrics, and artifacts.

The first integration should preserve raw solver outputs and version information. Optimization should wait until repeated runs are reproducible and the acoustic objective is demonstrably meaningful.

## Path to Optimization

```text
fixed dimensions and coverage
        -> K and N exploration
        -> derive S and reject invalid profiles
        -> conic-extension interaction
        -> squareness-morph interaction
        -> H/V decoupling
        -> acoustic comparison
        -> objective definition
        -> automated optimization
```

An optimizer must not make an invalid design appear successful by quietly changing coverage, mouth dimensions, or total length. Those remain hard constraints unless a later experiment explicitly promotes one to an optimization variable.

## Immediate Implementation Tasks

1. Correct and formalize `L_total`, `L_conic`, and `L_profile` in the app and exporter.
2. Extract deterministic profile and surface generation into callable Python functions.
3. Implement profile metrics and structured rejection reasons.
4. Define normalized candidate-configuration and result schemas.
5. Implement Phase A without acoustic simulation.
6. Review plots and metrics to set defensible `S`, slope, and curvature bounds.
7. Add Phase B and Phase C studies.
8. Select and integrate an acoustic modeling library.
9. Establish acoustic comparison metrics before implementing an optimizer.
