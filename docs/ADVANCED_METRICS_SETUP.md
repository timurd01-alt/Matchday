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
