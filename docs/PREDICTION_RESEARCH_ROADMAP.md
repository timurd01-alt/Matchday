# Matchday prediction research roadmap

Status: active research contract

Date: 2026-07-29

Objective: produce the most accurate, calibrated, transparent sports forecasts Matchday can
support with lawfully acquired data, while making no promise that forecasts will beat a market
or prevent financial loss.

## Product claim

Matchday estimates event probabilities and explains their evidence. It does not know the future,
guarantee profit, provide personalized financial advice, or make a wager safe. "Beat the market"
is a research hypothesis that must remain unclaimed unless a frozen prospective evaluation shows
sustained out-of-sample skill after fees and uncertainty.

The safest public wording is:

> Matchday provides probabilistic sports analysis, uncertainty, and an auditable record. If you
> choose to wager, you can lose the entire amount. No forecast makes gambling safe.

## Current-state finding

`fetch_data.py::predict()` is a documented heuristic baseline. It hand-weights record, margin,
form, class/talent, rank, SRS, Elo, rest, injuries, H2H, weather, and anomalies. When odds are
available it normally blends roughly 30-60% consensus market probability into the displayed
forecast. This is useful as a conservative production baseline, but it creates two distinct models
that must never be conflated:

- **Independent Matchday:** call the predictor without markets; eligible to test whether Matchday
  adds information beyond a market.
- **Market-informed Matchday:** blend model and consensus; potentially better calibrated, but not
  evidence that Matchday independently beat public opinion.

The existing MFTI protocol, immutable pick locks, Brier/log-loss tooling, and market audit are the
right foundations. The next step is a point-in-time training corpus and a separate learned challenger.

## Forecast data contract

For every event, append an immutable forecast receipt before lock containing:

- canonical event, competition, season, participants, venue, start time, and outcome definition;
- `observed_at`, `forecast_at`, `lock_at`, provider timestamps, and feature freshness;
- raw authorized input references or hashes plus the exact derived feature vector;
- source/license identifiers, missingness flags, and data-quality status;
- independent probability, market-informed probability, and model/version identifiers;
- opening and latest-prelock no-vig market snapshots when licensed, never a post-lock substitute;
- predicted outcomes, uncertainty interval, scenario probabilities, and explanation contributions;
- final result and grading rule, appended later without rewriting the forecast.

No training row may use a value first known after `forecast_at`. Historical backfills must reproduce
what was knowable then; otherwise the field is marked unavailable rather than filled from hindsight.

## Baselines every model must face

Evaluate all baselines on exactly the same eligible events:

1. League/base-rate plus home advantage.
2. Elo-only, trained chronologically.
3. Current independent Matchday heuristic.
4. Opening no-vig consensus.
5. Latest licensed prelock no-vig consensus.
6. Current market-informed Matchday heuristic.
7. Learned Matchday challenger, independent and market-informed variants reported separately.

The closing/prelock consensus is the primary forecasting benchmark. Accuracy alone is not enough:
a model that says 99% too often can pick more winners while being dangerously worse.

## Evaluation protocol

- Split chronologically by season/week. Never random-shuffle games across time.
- Use rolling-origin training: train on the past, predict the next untouched block, then advance.
- Tune features/hyperparameters only inside each training window. Keep a final confirmatory period
  untouched until the design is frozen.
- Evaluate sports and competitions separately before considering any pooled model. Outcome and
  scoring processes differ too much for one unexplained universal weighting system.
- Report multiclass Brier score, log loss, ranked probability score for ordered outcomes where
  appropriate, calibration intercept/slope, reliability plots, sharpness, and interval coverage.
- Report favorite accuracy only as a descriptive metric. Report ROI only as a fragile downstream
  simulation including timestamped executable price, vig/fees, liquidity, limits, voids, and slippage.
- Use paired block bootstrap confidence intervals by event/date and report sample sizes. Do not
  promote a feature because one season or competition was favorable.
- Segment results by sport, competition, horizon, probability band, season phase, favorite/underdog,
  data quality, and lineup/availability certainty.
- Check drift and recalibrate prospectively. Calibration fitted on the evaluation period is leakage.

## Feature research loop

For each candidate family in `OPEN_METRICS_SOURCE_REGISTRY.md`:

1. Write the hypothesis and expected direction before looking at final test results.
2. Verify license, provenance, historical depth, timestamp integrity, and live availability.
3. Implement the simplest reproducible formulation and a missingness indicator.
4. Compare univariate stability and redundancy only within training data.
5. Add it to a regularized logistic/multinomial baseline before trying a more flexible model.
6. Run rolling ablation: learned model with and without the family on identical events.
7. Inspect calibration, permutation importance on held-out folds, and failure segments.
8. Retain it only if improvement is stable, explainable, and available before lock.

Start with regularized generalized linear models and well-constrained gradient-boosted trees. Avoid
neural networks until the corpus is large enough to justify their variance and reduced transparency.
The model must support probability calibration and feature-attribution receipts.

## Promotion gate

A challenger is not user-facing until a versioned research specification is frozen and it:

- improves proper-score loss over the current independent baseline on prospective data;
- does not materially worsen calibration or any major competition/data-quality segment;
- survives feature ablation and plausible timestamp/leakage audits;
- has confidence intervals and a sample size defined prospectively by power analysis;
- continues to operate honestly when lineups, injuries, weather, or market data are missing;
- is reviewed for source compliance, grading correctness, and reproducibility.

Beating the licensed prelock consensus is a higher, separately reported bar. Failure to beat it is
not hidden. A market-informed model may be promoted for accuracy while being explicitly labeled as
market-informed.

## Transparency shown with every prediction

- exact event and outcome definition;
- independent versus market-informed label;
- probability distribution, not only a pick;
- calibration band such as "historically, forecasts in this band occurred X% of the time," with N;
- uncertainty/scenario range and the most important missing information;
- data freshness, sample depth, model version, and lock time;
- top evidence for and against the selected outcome;
- market disagreement without terms like "lock," "safe bet," or "guaranteed edge";
- permanent post-event grade and accessible historical scorecard.

MFTI should remain a forecast-trust/readiness measure unless prospective validation proves that it
adds information. It must not be presented as another probability or quietly alter a pick.

## Responsible-use section

Prefer **Risk & Market Context** or **Responsible Play** over "Sports Money." The section should
educate without creating an impression that Matchday can protect a person from loss.

Ship only after product/legal review, with these principles:

- The default action is **no wager**; abstention is a valid outcome when uncertainty swallows an edge.
- Explain implied probability, vig, fees, variance, liquidity, and why a good forecast can still lose.
- Do not provide personalized stake sizes, credit, deposits, bet execution, affiliate urgency, loss-
  chasing prompts, streak celebrations, or promises of income.
- If offering a voluntary planning tool, let the user set a hard entertainment-loss limit and time
  limit before viewing market context. Keep it local/private where possible; never raise the limit
  in response to losses.
- Include pause/cooling-off and self-exclusion guidance; never encourage borrowing or chasing.
- Prominently link US users to the National Problem Gambling Helpline, currently call/text
  **1-800-MY-RESET**, with 24/7 resources: https://www.ncpgambling.org/help-treatment/about-the-national-problem-gambling-helpline/
- State that only money remaining after living expenses and savings needs is risk capital. The CFTC
  gives the same core warning for event contracts: https://www.cftc.gov/LearnandProtect/PredictionMarkets
- Treat age, jurisdiction, accessibility, privacy, and vulnerable-user review as release blockers.

## Delivery order

### Phase 0 — integrity first

Build the append-only point-in-time feature/forecast schema, stable event identities, grading rules,
source metadata, and missingness/freshness tracking. Freeze the evaluation protocol.

### Phase 1 — honest baseline scorecard

Run league prior, Elo, current independent heuristic, current hybrid, and licensed no-vig market on
identical locked events. Publish coverage and calibration before headline accuracy.

### Phase 2 — learned challengers by sport

Begin with NFL because nflverse supplies deep, explicitly licensed play-by-play; then use licensed
box-score-derived basketball features; college feeds; soccer with coverage-aware event features;
and MLB historical validation plus licensed live inputs. NHL is explicitly outside the current
expansion scope. Each included sport gets its own feature contract and model card.

### Phase 3 — transparent shadow deployment

Generate learned predictions invisibly alongside production for a full prospective window. Capture
every forecast and revision. Do not cherry-pick examples into the public UI.

The first NFL challenger entered this phase on 2026-07-29 after a 2021–2025 expanding-window test.
It did not clear the promotion gate: its small log-loss difference from Elo was statistically
indistinguishable from zero and its Brier score was worse. It remains zero-weight shadow research;
this negative result is part of the permanent model record rather than a result to tune away.

A prior-only quarterback extension was evaluated next. It used the most recent observed primary
passer and only that player's earlier games, never the target game's actual starter. Its paired
ablation interval also included no improvement, so it remains an uncertainty/provenance receipt
rather than an accepted production feature. A future availability feed must provide timestamped
pregame status before actual starter changes can be tested honestly.

Chronological Elo calibration was the first component to clear a research gate: it improved both
proper scores over raw Elo across 844 out-of-sample forecasts, and the paired week-block interval
for log-loss improvement excluded zero. It is eligible only for a prospective shadow window. The
advanced-feature residual model did not beat calibrated Elo and remains rejected for production.

The prospective protocol is now frozen before the 2026 evidence window. It evaluates only unique,
verified pregame locks from the tamper-evident ledger, uses the latest appended correction for a
settled result, excludes ties, and compares all three NFL probabilities on identical fixtures.
Formal review requires at least 256 eligible games across 16 kickoff-week blocks. The evaluator
reports exclusions and paired week-block intervals and cannot change production weights.

### Phase 4 — controlled promotion

Promote only the frozen winner, preserve the replaced model in the scorecard, and add drift alerts,
rollback, and scheduled recalibration. Add Responsible Play content separately from prediction
promotion so safety messaging is not contingent on model performance.
