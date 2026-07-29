# Advanced metrics shadow pipeline

Status: implemented 2026-07-29

Scope: NFL, soccer research, MLB research, NBA/NCAAM normalized boxes, and NCAAF

Excluded: NHL

Advanced profiles are **shadow-only**. They are captured in point-in-time research receipts when
`attach_live` is true, but they do not alter `predict()` or any public pick. A learned challenger
must pass `PREDICTION_RESEARCH_ROADMAP.md` before any weight is promoted.

Generated profile and ledger files are intentionally gitignored.

## NFL — nflverse

The builder downloads only the `pbp` release, never `espn_data`, ESPN depth charts, or another
ESPN-origin release.

```powershell
python build_advanced_metrics.py nfl --season 2025 --output advanced_metrics_nfl.json
```

Output: EPA/play, success rate, CPOE, explosive-play rate, early-down share, seconds/play,
EPA/drive, drive score rate, and defensive rates. The 2025 profile was built successfully for all
32 teams and maps to the current Matchday NFL identity set.

## Soccer — StatsBomb Open Data

StatsBomb coverage is selective. The downloader consumes official raw GitHub files for one
explicit competition/season. It does not scrape statsbomb.com.

```powershell
python build_advanced_metrics.py statsbomb --root C:\data\statsbomb-wc2022 --download `
  --competition-id 43 --season-id 106 --min-matches 3 `
  --output advanced_metrics_soccer.json
```

Output: xG for/against/difference, non-penalty xG, xG/shot, pressure rate, pass completion,
final-third event share, and possession-sequence share. StatsBomb outputs set `attach_live=false`:
historical/selective coverage is for feature research and training only, never a silent current-
season input. Published analysis must follow StatsBomb's agreement, credit, and logo requirements.

## MLB — Retrosheet

Download official event files from https://www.retrosheet.org/game.htm, extract them locally, then:

```powershell
python build_advanced_metrics.py retrosheet --root C:\data\retrosheet\events `
  --output advanced_metrics_mlb.json
```

Output: strikeout, free-pass, hit, home-run, and contact rates from stable event-code prefixes.
The parser deliberately does not pretend to reconstruct Statcast batted-ball quality. Retrosheet
outputs set `attach_live=false` and remain historical research only. Before publishing or
transferring any Retrosheet-based data or derived product, reproduce the prominent attribution
statement required on Retrosheet's current notice page exactly as supplied there.

## Basketball — licensed normalized team-game boxes

The current BALLDONTLIE free adapter does not expose the box fields needed for four factors.
Do not fabricate them. When an authorized active provider/tier supplies team-game boxes, normalize
each row to:

`game_id, team, opponent, points, fgm, fga, three_pm, fta, orb, drb, tov`

Two rows per game are required. JSON may be a list or `{ "rows": [...] }`; CSV uses the same headers.

```powershell
python build_advanced_metrics.py basketball --input authorized_boxes.json `
  --sport NBA --source "Licensed provider name" --license "Exact plan/use grant" `
  --output advanced_metrics_nba.json
```

Output: possessions/tempo, raw and opponent-adjusted offensive/defensive/net ratings, eFG%,
turnover rate, offensive rebound rate, and free-throw rate.

## NCAAF — CollegeFootballData

The NCAAF build requests the documented league-wide `/stats/season/advanced` endpoint at most once
per 24 hours, normalizes PPA, success, explosiveness, line-yards, power success, stuff rate, and
defensive counterparts, and stores `advanced_metrics_ncaaf.json`. A missing, quota-limited, or
failed request leaves the feature unavailable; it never invents a neutral value. The first live
refresh attempt on 2026-07-29 returned HTTP 429, so no NCAAF profile was falsely published.

An already authorized JSON export of the endpoint can also be normalized offline:

```powershell
python build_advanced_metrics.py cfbd --input cfbd_advanced.json `
  --output advanced_metrics_ncaaf.json
```

## Point-in-time ledger

Every verified scorecard lock is reconciled into `forecast_ledger_<competition>.jsonl` as a
deterministic `forecast_locked` event. A settled result appends `forecast_graded`; a material score
correction appends another grade instead of rewriting history. Records are SHA-256 chained and
validated after every append. Replays are idempotent.

## NFL learned challenger

`build_nfl_challenger.py` turns approved nflverse play-by-play releases into a week-boundary
point-in-time corpus. A target game never sees plays or results from its own week. The research
model is an L2-regularized logistic residual layered on a fixed chronological Elo baseline. It
evaluates EPA, success, explosiveness, passing/CPOE/sacks, rushing, situational,
pace/special-teams, and rest/history families through expanding-window ablations.

```powershell
python build_nfl_challenger.py --input nflverse_pbp_2021.csv.gz `
  nflverse_pbp_2022.csv.gz nflverse_pbp_2023.csv.gz `
  nflverse_pbp_2024.csv.gz nflverse_pbp_2025.csv.gz `
  --min-train 512 --test-size 256
```

The 2021–2025 run produced 1,356 eligible training rows and 844 strictly out-of-sample forecasts.
The challenger log loss was `0.652474` versus Elo's `0.652560`, while challenger Brier score was
worse (`0.228454` versus `0.227370`). The paired week-block bootstrap interval for the log-loss
difference was `[-0.008881, 0.008852]`, so the apparent difference is indistinguishable from no
improvement. The automatic promotion gate therefore failed.

`nfl_challenger_model.json`, its training rows, and its backtest report are gitignored. When the
artifact is present, future NFL fixtures receive `nfl_challenger_shadow` with zero production
weight, the Elo baseline, residual probability, feature contributions, provenance, and offseason
uncertainty. The loader rejects any artifact that is not explicitly research-only or assigns a
nonzero production weight.

### Quarterback shadow extension

Version `nfl-challenger-0.2.0-qb-shadow` adds only forecast-reconstructible quarterback signals:
the primary passer from the latest completed prior game, that passer's earlier EPA/CPOE sample,
dropback experience, four-game continuity, and split-QB/sample uncertainty. It never reads the
target game's actual starter from play-by-play. Runtime receipts state that availability is
unconfirmed, record assumption freshness, and force elevated effective uncertainty across the
offseason.

Across the same 844 out-of-sample forecasts, the QB challenger logged `0.652730` versus Elo's
`0.652560`. Removing the quarterback family produced `0.652474`; the paired week-block interval
for full-minus-without-QB was `[-0.009805, 0.011115]`. The quarterback family therefore has no
demonstrated incremental log-loss value and remains research-only. It moved Brier close to Elo
(`0.227376` versus `0.227370`), but that difference is also not a promotion case.
