# External model review: what it got right and what is realistic (2026-11-23)

**Status:** review only, nothing on the site or in the engine changed.
**Question:** an outside "MatchdayTerminal Model Audit" recommended player
availability, projected minutes, matchup terms, a market benchmark and a
challenger framework. Which of those are realistic, and which already exist?

## Sources
| Source | What it gave |
|---|---|
| The review (pasted by the owner) | Claims and recommendations |
| matchdayterminal.com `roadmap.html`, `qa.html` | Live copy, fetched 2026-11-23 |
| `origin/main` @ `42d680b`, `trdlab_picks.json` scorecard | Graded record: 672 priced football picks, 294 priced basketball picks |
| TRDLab @ `5773fc9` | `trdlab/hoops/*`, `scripts/`, `docs/research/2026-10-18-*` |

## Claims checked
| Review says | Finding |
|---|---|
| Roadmap says basketball uses results only; Q&A says predictions are paused | **Out of date.** Live roadmap (updated Oct 21) says the model reads play-by-play efficiency and points per possession; live Q&A (updated Nov 20) has no pause wording. The reviewer read older copies. Nothing to fix. |
| 653 picks, 71.7% vs 72.3% expected; disagreements 19-33 | Matches the record at the time. Now 725 picks, 72.0% vs 72.3%; disagreements 20-34 (37.0% vs 58.6% expected). |
| 44.3% "beat the price" | Now 42.9% of 1,342 priced selections (CI 40.3-45.6). The model's own expected beat rate, computed from its probabilities, is 50.2%, so the 50% reference on the page is fair. |
| Backend features unknown | True from the outside. They exist but the site does not list them (see below). |

## Already built (the review could not see it)
- Pick lock 60 minutes out with the market price at lock, never rewritten; CLV report; market snapshot ledger; pre-registration with sealed terms.
- Shadow challengers with no automatic promotion (`qb_injury_challenger.py`, `tier_offset_experiment.py`, `ncaam_early_season_experiment.py`).
- Basketball: lineup-based player impact (ridge adjusted plus-minus shrunk toward a box-score prior, `hoops/impact.py`), lineups, projected rosters, and a cumulative feature ablation scored against the market on the same games (`hoops/ablation.py`). Box, shot and lineup data cover 2025-26 only, so these are walk-forward inside one season.
- Football: preseason prior from talent composite, recruiting, returning and transfer production and QB (shipped `dee5dc3`); opponent-adjusted EPA.
- Calibration: football model-only probabilities track outcomes in every band (2026-10-18 note); widening sigma was inside noise.

## Where the model loses to the market
Model picks of the market underdog, graded, at lock:

| Month | Football | Basketball |
|---|---|---|
| Sep | 7-18 (64% expected) | — |
| Oct | 7-8 (54%) | — |
| Nov | 4-8 (53%) | 8-12 (59%) |

Mean Brier, priced picks: football 0.187 model vs 0.178 market (Sep 0.148 vs 0.128, Oct 0.207 vs 0.205, Nov 0.200 vs 0.191); basketball 0.148 vs 0.131 (early season, known home-edge gap under `ncaam-early-season-calibration-v1`). Consistent with the 2026-11-10 finding: from October the disagreements carry no information the price lacks.

## Realistic changes, in order
1. **Expected absences (engine, shadow first).** The one piece of the review that targets what the market knows. Engine research already measured it (`2026-10-18-expected-absences.md`): streak-based expected missing regulars, −1.1 pts per expected missing regular, margin MAE 12.371 → 12.335, but the slope was fitted on the test years. Next step as that note says: fit on 2024, test on 2025-26 with a game-week block bootstrap, weight by role (QB about 5 pts). Ship only if the CI excludes zero; otherwise a sealed shadow experiment. Bowl season (opt-outs) is where this matters most and is weeks away.
2. **Basketball player-impact adjustment (engine, shadow).** The ablation and RAPM code exist; production still runs `hoops-efficiency-v1`. Re-run the ablation as 2026-27 lineups accumulate and register a shadow challenger if the impact block beats efficiency alone on the held-out window.
3. **Conference availability reports (sourcing).** Already identified as the open injury source (Big Ten, SEC, ACC, Big 12, Mountain West publish them). Needs a terms check in `PROVIDER_COMPLIANCE.md` before any scraper.

## Not recommended
- **SportsDataIO.** Commercial pricing is quoted; its Discovery Lab licence is personal and non-commercial, so it cannot back a public site.
- **More market weight or a market-aware model to gain accuracy.** Ruled out by the owner (2026-10-18): the goal is to beat the price, not copy it.
- **A new general stats feed.** CFBD and CBBD already cover player data for modelling.

## Owner's call, not verified here
The review lists CFBD paid tiers from $1/month for 5,000 calls and says football and basketball share one allowance. Not checked against the providers' own pages. If accurate, a low tier would remove the monthly quota outages (CFBD went dark for three weeks in August), but the site is built on free tiers by choice.
