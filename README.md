# Matchday

Transparent sports forecasting and intelligence.

## Philosophy

Probability, not certainty. Matchday isn't a sportsbook, a tipster, or an "AI that knows
the future" — it's a forecasting desk that publishes a probability before a game and
grades itself against the real result afterward.

## Transparency

- Every prediction is locked before kickoff and published pregame — never after.
- Locked predictions are never rewritten, never silently rescored, and never quietly
  deleted. See a graded pick, and you're seeing exactly what was published beforehand.
- Postgame grading is automatic, from the model's own recorded pick.
- The public [Scorecard](https://matchdayterminal.com/?view=score) reports accuracy,
  Brier score, log loss, and calibration computed from the complete verified pick
  history — never a cherry-picked subset.

## What it does

- Pregame match forecasts and probability breakdowns, with the real factors behind
  each pick (points, form, ratings, injuries, and more)
- Model vs. market comparison — where the forecast agrees or disagrees with the market,
  and whether that's actually meant anything historically
- A verified prediction history with postgame grading, never edited after the fact
- Advanced model views: outcome exploration, a neutral-venue "what if" toggle backed
  by a real second model run (not a fake slider), and a public Model Scorecard
- Coverage across soccer (World Cup, Champions League, and major domestic leagues),
  NFL, college football, NBA, college basketball, and MLB

## Current status

Early access, and openly under construction. The model runs on free-tier and licensed
data sources today; upgrades happen when a real, measured improvement justifies the
cost — see [docs/experiments.json](docs/experiments.json) and
[docs/PREDICTION_RESEARCH_ROADMAP.md](docs/PREDICTION_RESEARCH_ROADMAP.md) for the
actual experiment record: what's been tested, what got kept, and what got rejected.

## Research

Matchday publishes its own research on itself — model calibration, experiment results,
and what actually moved performance — in the in-app **Insights** tab, generated
straight from the real pick history rather than hand-written claims. See
[build_research_posts.py](build_research_posts.py).

## Live product

[matchdayterminal.com](https://matchdayterminal.com/)

## Local development

See [SETUP.md](SETUP.md) for running the interface locally and adding provider
credentials. Data-provider terms, licensing, and attribution requirements are tracked
in [PROVIDER_COMPLIANCE.md](PROVIDER_COMPLIANCE.md).

## License

Source is publicly viewable for transparency, not open source — see [LICENSE](LICENSE).
