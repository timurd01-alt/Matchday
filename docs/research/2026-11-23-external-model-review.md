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
1. **Expected absences from box scores: tested 2026-11-23, rejected.** This is the one piece of the review that targets what the market knows. The −1.1 pts per missing regular in `2026-10-18-expected-absences.md` was in-sample, and a later 2026-10-18 note already found it did not hold out of sample. Re-run with the split asked for here (persistence fitted 2021-23, effect fitted on 2024, scored once on 750 games of 2025-26, week-block bootstrap; engine `docs/research/2026-11-23-absences-walk-forward.md`): count version MAE 12.243 → 12.215, 95% CI [−0.124, +0.063]; role-weighted version −0.016, CI [−0.039, +0.003]. Neither interval excludes zero, and the QB term came out near zero. Box scores only show who missed earlier games; the costly absence is the first game a starter misses, which only pregame news reveals. **What's left for availability:** the conferences' free pregame availability reports feeding the existing QB-injury shadow challenger, after a terms check in `docs/PROVIDER_COMPLIANCE.md`.
2. **Basketball player-impact adjustment (engine, shadow).** The ablation and RAPM code exist; production still runs `hoops-efficiency-v1`. Re-run the ablation as 2026-27 lineups accumulate and register a shadow challenger if the impact block beats efficiency alone on the held-out window.
3. **Conference availability reports (sourcing): terms checked 2026-11-23.** `qb_availability.py` already collects SEC, Big Ten, ACC and Big 12 QB statuses hourly (display only, since 2026-10-25; 528 report rows). Terms read live: SEC (Disney terms) explicitly bans automated extraction for building data sets; Big Ten bans any public use of its information without written approval; ACC and Big 12 (SIDEARM terms) bar storing "Content" beyond personal use, and it is unclear whether facts count. HD Intelligence, the vendor endpoint, publishes no terms. **Owner's decision: we can't use them.** Build 1123D removed the collector and the stored facts; no conference report is collected, stored, shown or used as a model input. With box-score absences also rejected, the model has no availability signal and none is in reach at zero cost. Details in `docs/PROVIDER_COMPLIANCE.md`, 2026-11-23 entry.

## Not recommended
- **SportsDataIO.** Commercial pricing is quoted; its Discovery Lab licence is personal and non-commercial, so it cannot back a public site.
- **More market weight or a market-aware model to gain accuracy.** Ruled out by the owner (2026-10-18): the goal is to beat the price, not copy it.
- **A new general stats feed.** CFBD and CBBD already cover player data for modelling.
- **Any paid tier or paid feed.** The owner's budget is zero (2026-11-23). The review's CFBD paid tiers ($1/month and up) and every other paid source are out; work stays on free tiers, free public facts and the local engine database.
