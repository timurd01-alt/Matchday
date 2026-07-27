# Matchday Forecast Trust Index — Research Protocol 0.1

Status: frozen shadow specification  
Version: `MFTI-0.1.1-shadow`  
Purpose: prospective scientific validation only

## Correction log

**0.1 → 0.1.1 (2026-07-27) — stability normalizer.** The 0.1 implementation
normalized the weighted Jensen–Shannon divergence by `log(outcome count)`.
That divergence is bounded by *both* `log(outcome count)` and `H(weights)`,
and the binding constraint is whichever is smaller, so the original divisor
left a floor under the score whenever `H(weights)` was smaller: two equally
weighted, maximally opposed scenarios scored `0.000` in a two-way market but
could not go below `0.369` in a three-way one. Scenario stability and
independent-model stability therefore meant different things per sport, which
would bias the index across competitions rather than measure them. Both now
normalize by `min(log(outcome count), H(weights))`.

Degenerate comparisons — a single-outcome vector, or one scenario holding all
the weight — previously raised `ZeroDivisionError` out of `build_shadow_receipt`.
They now report the component missing, per rule 4: absence never earns a score.

No component weight, exponent, the negative power mean, or the withheld
Evidence pillar changed. The correction is recorded rather than applied
silently because receipts carry the version string, and a frozen specification
whose mathematics changed without a trace would make its own audit worthless.
It is safe to correct now under rule 8: no confirmatory evaluation has been
run and no scored receipt exists.

## Claim boundary

MFTI is Matchday's original scoring architecture built from established
statistical tools. Matchday does not claim authorship of proper scoring rules,
calibration, Kullback–Leibler divergence, Jensen–Shannon divergence, effective
sample size, geometric means, or related mathematical foundations.

## Non-negotiable rules

1. MFTI never changes the outcome probability or selected side.
2. Shadow results are not user-visible and are not used for ranking or betting.
3. Every receipt is captured with the official pregame lock and is immutable.
4. Missing components remain unavailable; absence never earns a perfect score.
5. A final MFTI score is withheld until both pillars are complete.
6. Forecast revisions create new timestamped observations rather than rewriting
   the original receipt.
7. Market comparisons require a capture timestamp no later than the forecast.
8. Development thresholds and calibration maps must be frozen before the first
   confirmatory evaluation.

## Frozen 0.1 architecture

Historical Evidence:

`H_raw = S^0.45 × C^0.30 × R^0.25`

`H = 0.5 + M(H_raw - 0.5)`

Event Readiness uses a negative-power mean:

`Q = (.35G^-2 + .25V^-2 + .20F^-2 + .20D^-2)^(-1/2)`

Final index:

`MFTI = 100 × H^0.60 × Q^0.40`

`G`, `V`, `F`, and `D` represent scenario stability, availability certainty,
freshness/coverage, and independent-model stability. Component values use the
closed interval `[0, 1]`, with `0.05` as the numerical floor in the negative
power mean.

The 0.1 implementation records Historical Evidence diagnostics but deliberately
does not emit `H`. Normalization thresholds, block-bootstrap lower confidence
bounds, and the rolling-origin recalibration map have not yet been fitted on a
separate development corpus.

## Point-in-time input contract

An event may supply a private `mfti_inputs` object before lock:

```json
{
  "scenario_forecasts": [
    {"label": "starter_active", "probability": 0.7,
     "probabilities": {"h": 62, "a": 38}},
    {"label": "starter_inactive", "probability": 0.3,
     "probabilities": {"h": 51, "a": 49}}
  ],
  "availability": [
    {"name": "starting_player", "importance": 1.0, "certainty": 0.7}
  ],
  "freshness": [
    {"family": "lineup", "importance": 1.0, "coverage": 1.0,
     "age_hours": 1.0, "half_life_hours": 6.0}
  ],
  "independent_models": [
    {"family": "matchday", "independent": true, "weight": 1.0,
     "probabilities": {"h": 62, "a": 38}},
    {"family": "plain_elo", "independent": true, "weight": 1.0,
     "probabilities": {"h": 58, "a": 42}}
  ]
}
```

Importance weights must be determined prospectively. An `independent: true`
declaration is an auditable methodological assertion, not an automatic inference.

## Confirmatory success criterion

After development is frozen, MFTI must predict lower out-of-sample proper-score
loss after controlling for forecast probability, sport, competition, horizon,
and season phase. Report Brier score, log loss, calibration, bootstrap confidence
intervals, MFTI-band monotonicity, and component ablations. If it adds no stable
information beyond the probability itself, it must not be promoted.
