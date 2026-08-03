# Matchday Wiki

Matchday is a multi-sport prediction and analytics product built around a simple public record: analyze the matchup before it starts, lock the model's pick, then grade that exact pick after the official final result.

It combines attributed sports data with Matchday's ratings and probability models to produce matchup forecasts, projected margins, rankings, tournament views, performance tracking, and an Outcome Tree for exploring exact multi-game scenarios. Model outputs are estimates that anyone can use, not official league information or guarantees.

Matchday is deliberately not an ESPN-style live-score service. In-progress games remain **Result pending** until a provider supplies a final result suitable for grading.

## Start here

- [Prediction Lifecycle](Prediction-Lifecycle)
- [How Predictions Work](How-Predictions-Work)
- [Rankings and Projections](Rankings-and-Projections)
- [Data Sources and Freshness](Data-Sources-and-Freshness)
- [Development and Testing](Development-and-Testing)
- [FAQ and Limitations](FAQ-and-Limitations)

## Current public coverage

The public pipeline covers the World Cup, Champions League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, NFL, NCAA football, NBA, NCAA men's basketball, and MLB. NHL is excluded while provider access remains unresolved. Availability still varies by provider, season, and subscription tier; unavailable fields remain blank rather than being fabricated.

## Official data and Matchday outputs

Official scores, schedules, standings, polls, odds, and player data come from attributed providers. Elo ratings, SRS, predictions, projected rankings, title estimates, upset indicators, and related explanations are Matchday-derived outputs.

For the code and issue tracker, visit the [Matchday repository](https://github.com/timurd01-alt/Matchday).
