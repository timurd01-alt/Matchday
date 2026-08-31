# Matchday Wiki

Matchday is a college football and college basketball prediction and analytics product built around a simple public record: analyze the matchup before it starts, lock the model's pick, then grade that exact pick after the official final result.

It combines attributed sports data with Matchday's ratings and probability models to produce matchup forecasts, projected margins, rankings, tournament views, and performance tracking. Model outputs are estimates that anyone can use, not official league information or guarantees.

Matchday is deliberately not an ESPN-style live-score service. In-progress games remain **Result pending** until a provider supplies a final result suitable for grading.

## Start here

- [Prediction Lifecycle](Prediction-Lifecycle)
- [How Predictions Work](How-Predictions-Work)
- [Rankings and Projections](Rankings-and-Projections)
- [Data Sources and Freshness](Data-Sources-and-Freshness)
- [Development and Testing](Development-and-Testing)
- [FAQ and Limitations](FAQ-and-Limitations)

## Current public coverage

Matchday's focus is **NCAA football** and **NCAA men's basketball** — that is where the model, the research, and the published record are aimed.

The pipeline still fetches several other competitions (World Cup, Champions League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, NFL, NBA, and MLB), and their provider attributions remain in force for as long as it does, but they are not the product's focus. NHL is excluded while provider access remains unresolved. Availability still varies by provider, season, and subscription tier; unavailable fields remain blank rather than being fabricated.

## Official data and Matchday outputs

Official scores, schedules, standings, polls, odds, and player data come from attributed providers. Elo ratings, SRS, predictions, projected rankings, title estimates, upset indicators, and related explanations are Matchday-derived outputs.

For the code and issue tracker, visit the [Matchday repository](https://github.com/timurd01-alt/Matchday).
