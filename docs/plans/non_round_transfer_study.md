# Non-round H/V and square-mouth transfer study

Status: preregistered implementation; BEM not yet launched

## Purpose

Validate the minimum measured rules needed to initialize the horn optimizer:

- whether round evidence transfers independently to horizontal and vertical
  K/N seeds;
- whether a width/height-weighted or S-balanced common OS-SE length is the
  stronger flat-mouth construction;
- whether square corners require a different starting branch;
- which regions require wider first-round exploration.

No sag is included. Every new candidate uses zero extension, zero sag, a 6°
throat angle, fixed intended and OS-SE H/V coverage, surface score v2.3, and
throat-impedance diagnostic v2.3.0.

Here `elliptical` means `mouth_squareness = 0` with unequal H/V dimensions.
`square` means `mouth_squareness = 1`; unequal dimensions therefore produce a
rectangular aperture with fully squared corners.

## Registered allocation

The initial allocation is 48 simulations:

- eight equal-H/V square transformations;
- seven unequal-H/V development intents × two mouth shapes × two common-length
  constructions = 28;
- six locked unequal-H/V intents × two mouth shapes using the development
  winner = 12.

At most four failed locked intents receive four closure candidates each, for an
absolute maximum of 64 simulations. Geometry rejections do not authorize a
replacement outside the frozen coordinate construction.

## Equal-H/V square transformations

The exact round surface-v2.3 winner is the reused parent. Only the matched
square transform is new BEM work.

| ID | Mouth H/V (mm) | Coverage H/V |
|---|---:|---:|
| Q1 | 250 / 250 | 30° / 30° |
| Q2 | 250 / 250 | 50° / 50° |
| Q3 | 450 / 450 | 30° / 30° |
| Q4 | 450 / 450 | 50° / 50° |
| Q5 | 300 / 300 | 35° / 35° |
| Q6 | 350 / 350 | 40° / 40° |
| Q7 | 400 / 400 | 45° / 45° |
| Q8 | 450 / 450 | 40° / 40° |

## Unequal-H/V development intents

| ID | Mouth W×H (mm) | Coverage H×V | Purpose |
|---|---:|---:|---|
| D1 | 400×280 | 50°×35° | primary anchor |
| D2 | 360×252 | 50°×35° | smaller scale |
| D3 | 450×315 | 50°×35° | larger scale |
| D4 | 450×250 | 45°×35° | high aspect ratio |
| D5 | 400×320 | 45°×35° | moderate aspect ratio |
| D6 | 400×280 | 40°×40° | equal-coverage anisotropy |
| D7 | 350×300 | 35°×45° | reversed unequal coverage |

For each axis, use the independent measured round seed for that axis's mouth
dimension and coverage. Never average H/V K or N.

The weighted common length is:

```text
Lw = (W Lh + H Lv) / (W + H)
```

The S-balanced length preserves the independent-axis S values in weighted
log space:

```text
W log(Sh(L) / Sh(Lh)) + H log(Sv(L) / Sv(Lv)) = 0
```

The root is solved between the two independent axis lengths. This definition
is deterministic and uses S only as a derived coupling guide.

The preferred rule is frozen after development using all 14 matched
shape/intention pairs. If the median surface-v2.3 difference between
S-balanced and weighted is within ±0.5 point, weighted wins the tie. Otherwise
the rule with the higher median paired surface score is selected.

## Locked intents

| ID | Mouth W×H (mm) | Coverage H×V | Purpose |
|---|---:|---:|---|
| L1 | 350×250 | 50°×35° | near-anchor scale/aspect |
| L2 | 450×350 | 50°×35° | large unequal aperture |
| L3 | 400×250 | 45°×30° | high aspect, lower V coverage |
| L4 | 450×300 | 40°×40° | equal-coverage anisotropy |
| L5 | 400×350 | 35°×45° | reversed coverage |
| L6 | 300×400 | 35°×50° | portrait orientation |

The independent-axis reference score is the same width/height-weighted average
of the two source-cell surface-v2.3 scores. A locked intent fails transfer when
the better of its measured elliptical and square preferred-rule candidates is
more than 3.0 surface points below that reference. Select at most the four
largest deficits.

Each selected closure receives exactly:

1. elliptical mouth at the alternate common-length construction;
2. square mouth at the alternate construction;
3. square mouth at 0.9× the preferred common length;
4. square mouth at 1.1× the preferred common length.

## Execution and promotion

Every coordinate is a one-candidate `bem_candidate_search` evaluated through
the stage-aware scheduler with eight orchestration workers and the shared
20-process NumCalc limit. Manifests freeze coordinates, input hashes, and
phase caps before BEM. The live index is ledger-backed.

Promotion is limited to measured initialization rules and support warnings.
The study does not fit or release a portable score surrogate. Development
selects the common-length rule; locked results determine whether it transfers;
equal-H/V contrasts measure the square-corner delta; closure only widens
first-round optimizer exploration in failed regions.
