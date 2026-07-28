# How Predictions Work

Matchday produces a probability distribution for each supported matchup, then selects the outcome with the highest probability. For sports that allow draws, the distribution includes home win, draw, and away win. Knockout advancement probabilities are kept separate from regulation-time probabilities.

## Signals used

Depending on the sport and available data, the prediction engine can use:

- Team strength ratings
- Self-updating, sport-scoped Elo ratings
- Simple Rating System (SRS) derived from results and scoring margins
- Current record, form, scoring differential, and home advantage
- Head-to-head history, with limited weight until the sample grows
- Rest, availability, and lineup information when licensed data exists
- Recruiting or roster-talent information for preseason college matchups
- Market probabilities when real odds are available

Signals are coverage-aware. A new team, stale season record, or small head-to-head sample is not treated as fully reliable. Matchday becomes more willing to trust a signal as its sample grows.

## Model and market

The model first creates its independent probability estimate. When valid market odds are present, Matchday removes the bookmaker margin and applies a bounded market blend. The market does not replace the model, and a missing market does not prevent a prediction or verified lock.

Odds are fetched only for upcoming games close to kickoff and cached to conserve quota. If they arrive after the pick locks, Matchday can add market-comparison context without changing the locked outcome or confidence.

## Confidence and projected margin

Displayed confidence is the selected outcome's probability, not a promise that the outcome will happen. Projected margin is derived from the same win probabilities and should be read as a matchup estimate, not a separately trained exact-score forecast.

## Upsets and risk

Upset Radar identifies market underdogs that the model rates more competitively than the consensus price. A radar flag is not automatically an official upset pick. Selecting the underdog requires additional probability, volatility, and market-gap checks; when a current market is unavailable, the model normally remains conservative rather than forcing a risky call.

## Locking and evaluation

Predictions become eligible for a verified public lock inside 12 hours of kickoff. The selected side and confidence are immutable after that lock. Final results grade the saved record; in-progress games remain result pending.

Matchday emphasizes probability-focused evaluation—including Brier score, log loss, calibration, confidence intervals, and out-of-sample testing—rather than judging a model only by raw win rate. See [Prediction Lifecycle](Prediction-Lifecycle) for the persistence guarantees behind the public scorecard.
