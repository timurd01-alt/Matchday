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

Odds are fetched only for upcoming games close to kickoff and cached to conserve quota. If they arrive after the pick locks, Matchday can add market-comparison context without changing the locked outcome or confidence.

## Confidence and projected margin

Displayed confidence is the selected outcome's probability, not a promise that the outcome will happen. Projected margin is derived from the same win probabilities and should be read as a matchup estimate, not a separately trained exact-score forecast.

## Outcome Tree

Outcome Tree combines up to five exact published outcomes from different games into one model scenario. A compact two-step menu selects the game and exact outcome, avoiding a long fixture list. If selected event probabilities are `p1`, `p2`, and `p3`, the displayed joint probability is `p1 x p2 x p3`. The fair decimal and American odds are alternate representations of that same model probability, not sportsbook prices.

The tree diagram uses neutral notation: `X` means the exact outcome selected in the menu and `Y` means any other result. The multiplication assumes the selected games are independent. Real sports events can be correlated through shared teams, injuries, scheduling, tournament incentives, or common information, so the combined estimate can be too high or too low. Matchday warns when selected events share a team, but it does not currently estimate those correlations. Only one exact result can be selected per game; in sports with draws, "Team wins" and "Draw" are separate outcomes, so a team-loss selection does not silently include a draw.

Outcome Tree uses locked prediction snapshots when they exist and otherwise uses the current published probability. It does not improve the underlying prediction: missing talent, pitcher, injury, lineup, or market inputs carry into the combined estimate. It is a scenario-analysis tool, not a betting recommendation or staking calculator.

## Upsets and risk

Upset Radar identifies market underdogs that the model rates more competitively than the consensus price. A radar flag is not automatically an official upset pick. Selecting the underdog requires additional probability, volatility, and market-gap checks; when a current market is unavailable, the model normally remains conservative rather than forcing a risky call.

## Locking and evaluation

Predictions become eligible for a verified public lock inside 12 hours of kickoff. The selected side and confidence are immutable after that lock. Final results grade the saved record; in-progress games remain result pending.

Matchday emphasizes probability-focused evaluation—including Brier score, log loss, calibration, confidence intervals, and out-of-sample testing—rather than judging a model only by raw win rate. See [Prediction Lifecycle](Prediction-Lifecycle) for the persistence guarantees behind the public scorecard.
