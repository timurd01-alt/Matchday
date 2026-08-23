# How Predictions Work

Matchday produces a probability distribution for each supported matchup, then selects the outcome with the highest probability. For sports that allow draws, the distribution includes home win, draw, and away win. Knockout advancement probabilities are kept separate from regulation-time probabilities.

## Signals used

Depending on the sport and available data, the prediction engine can use:

- Sport-specific squad, roster-talent, or recruiting priors when a verified source exists
- Self-updating, sport-scoped Elo ratings
- Simple Rating System (SRS) derived from results and scoring margins
- Current record, form, scoring differential, and home advantage
- Head-to-head history, with limited weight until the sample grows
- Rest, availability, and lineup information when licensed data exists
- Market probabilities when real game odds are available
- Championship-futures market power, labeled separately from roster talent

Signals are coverage-aware. A new team, stale season record, or small head-to-head sample is not treated as fully reliable. Matchday becomes more willing to trust a signal as its sample grows.

## What “class” means by sport

“Class” is not a generic prestige score. The matchup interface uses a sport-specific label and only shows an edge when the underlying input actually measures player or roster quality:

| Sport | Displayed signal | Current method |
| --- | --- | --- |
| College football | **Roster talent edge** | Multi-year blend of 247Sports Team Talent Composite roster snapshots supplied by CollegeFootballData. Successful enrichment is persisted to the tracked ratings file so a later provider rate limit cannot turn the signal into zero. |
| Men's college basketball | **Recruiting edge** | CollegeBasketballData team recruiting ratings. This is explicitly a recruiting prior, not a claim to measure the entire current roster or transfer portal. |
| Soccer | **Squad edge** | Curated squad value, star-player value, and ranking data for covered clubs or national teams. Uncovered teams receive no fabricated squad edge. |
| MLB | **Personnel edge** | Not published with the current feed. A legitimate version needs probable starting pitchers, projected or confirmed batting orders, and bullpen availability. |
| NFL | **Roster edge** | Not published with the current feed. It requires complete current depth charts plus player quality and availability. |
| NBA | **Star / rotation edge** | Not published with the current feed. It requires active rotations, player quality, minutes expectations, and availability. |
| NHL | **Roster / goalie edge** | Not published until current lines, starting goalie, and availability are covered. |

Championship futures remain useful as a long-term team-strength prior, but the model records them as **championship market power**, never as talent or class. For college matchups that already have a real talent or recruiting signal, futures receive reduced weight because the two inputs are correlated.

## Model and market

The model first creates its independent probability estimate. When valid market odds are present, Matchday removes the bookmaker margin and applies a bounded market blend. The market does not replace the model, and a missing market does not prevent a prediction or verified lock.

The public pick and headline scorecard grade that published, market-informed forecast. A comparison with the same market is therefore a same-time hybrid-versus-market benchmark, not evidence that a statistically independent model beat its own input. The independent pre-blend probabilities are preserved separately in the forecast ledger for research evaluation.

Odds are fetched only for upcoming games close to kickoff and cached to conserve quota. If they arrive after the pick locks, Matchday can add market-comparison context without changing the locked outcome or confidence.

## Confidence and projected margin

Displayed confidence is the selected outcome's probability, not a promise that the outcome will happen. Projected margin is derived from the same win probabilities and should be read as a matchup estimate, not a separately trained exact-score forecast.

## Upsets and risk

Upset Radar identifies market underdogs that the model rates more competitively than the consensus price. A radar flag is not automatically an official upset pick. Selecting the underdog requires additional probability, volatility, and market-gap checks; when a current market is unavailable, the model normally remains conservative rather than forcing a risky call.

## Locking and evaluation

Predictions become eligible for a verified public lock on the first successful refresh inside the sport-aware pregame window: two hours for professional sports and soccer, and three hours for college sports. The selected side and confidence are immutable after that lock. Final results grade the saved record; in-progress games remain result pending.

Matchday emphasizes probability-focused evaluation—including Brier score, log loss, calibration, confidence intervals, and out-of-sample testing—rather than judging a model only by raw win rate. See [Prediction Lifecycle](Prediction-Lifecycle) for the persistence guarantees behind the public scorecard.
