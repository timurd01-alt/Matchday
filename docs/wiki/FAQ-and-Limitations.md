# FAQ and Limitations

## Is Matchday a live-score app?

No. Matchday publishes pregame model analysis and postgame accountability. In-progress games are labeled **Result pending** until a provider-confirmed final result arrives; the product does not promise live clocks, score alerts, or minute-by-minute updates.

## When does a pick lock?

A prediction becomes eligible for a verified public lock inside a sport-aware pregame window — three hours before kickoff for college football and college basketball, two hours for the other competitions still fetched. The selected side and confidence do not change after that lock. Market-comparison fields can be filled later if odds arrive, but they cannot rewrite the pick.

## Why is a game still result pending after it ended?

The hourly fetch may not have run yet, or the provider may not have published a final status. Suspensions, postponements, event-identity mismatches, and provider corrections can also delay grading. Matchday waits for a verifiable final result rather than grading from an unofficial score.

## How do I know a pick was really graded?

The scorecard counts only records that were verified as locked before kickoff and persisted with a final result and hit/miss field. The fetch fails if an expected lock or grade is missing after the ledger write. Generated recaps use the same verified record.

## Is Matchday an official league product?

No. Matchday is an independent analytics project and does not imply endorsement by a league, team, poll, sportsbook, or data provider.

## How can predictions be used?

However works for you. Predictions are public probabilistic estimates, and a 70% forecast still assigns a meaningful chance to the other outcome.

## Why did a favorite lose?

Probabilities describe uncertainty; they do not guarantee individual results. Upsets are expected over a sufficiently large set of games. Calibration over many forecasts is more informative than one result.

## Why does Matchday disagree with a poll or sportsbook?

Matchday combines its own team-strength signals and may weight information differently. Market data is bounded rather than copied directly, and projected rankings are not intended to reproduce voter ballots.

## Why is a team in the way-too-early Top 25?

Before a real preseason poll exists, college projections blend 55% prior-season final-poll performance with 45% roster talent or recruiting strength. This lets recent achievement and upcoming roster quality both matter.

## Why is information missing?

Coverage varies by sport, provider, subscription, time of season, and proximity to kickoff. Missing data is left unavailable rather than guessed.

## Can historical results change?

Providers can correct scores, statuses, player statistics, or event identities after publication. Matchday caches data for reliability and quota control, so corrections may not appear instantly. A correction can update official result facts but does not rewrite the original locked pick.

## What are the main model limitations?

- Early-season and newly tracked teams have smaller samples.
- Injuries, transfers, and lineups are only incorporated when reliable licensed data is available.
- Elo and head-to-head signals need time to earn full weight.
- A recruiting rating cannot fully measure development, coaching, or transfer impact.
- Outside college football and college basketball, the other competitions still fetched do not display a roster/personnel edge until their configured feeds provide the required player, depth-chart, lineup, or starter coverage. Championship futures are labeled separately as market power rather than being passed off as talent.
- College-football roster talent refreshes through CollegeFootballData. Matchday performs a quota-light talent refresh before the broader data build and persists successful enrichment to tracked ratings, so later rate limits use the last licensed snapshot rather than publishing a fabricated zero edge. During the July 2026 quota outage, already verified 2025 spot checks provide a transparent 15-team bridge (including Michigan State and Toledo) until the full-field refresh succeeds.
- Market availability is uneven across competitions and dates.
- Projected margin is inferred from outcome probabilities, not a dedicated exact-score model.

For bugs or documentation corrections, open an issue in the [Matchday repository](https://github.com/timurd01-alt/Matchday/issues).
