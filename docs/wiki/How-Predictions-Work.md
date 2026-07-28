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

The model first creates its independent probability estimate. When valid market odds are present, Matchday removes the bookmaker margin and applies a bounded market blend. The market does not replace the model, and a missing market does not prevent a prediction.

## Confidence and projected margin

Displayed confidence is the selected outcome's probability, not a promise that the outcome will happen. Projected margin is derived from the same win probabilities and should be read as a matchup estimate, not a separately trained score forecast.

## Evaluation

Finished predictions are graded against real results. Matchday's research protocol calls for probability-focused evaluation—including Brier score, log loss, calibration, confidence intervals, and out-of-sample testing—rather than judging a model only by its raw win rate.

See the repository's [MFTI research protocol](https://github.com/timurd01-alt/Matchday/blob/main/MFTI_RESEARCH_PROTOCOL.md) for the experimental forecast-trust framework. MFTI is a shadow research metric and does not alter the selected side or outcome probability.
