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

The deploy workflow now runs `refresh_nfl_advanced_metrics.py` before its adaptive sports refresh.
It tries the active NFL season once games exist, falls back to the last completed season when the
active file lacks broad team coverage, and preserves a last-good profile on download failure. Only
derived team profiles are embedded into fixture JSON; nflverse play-by-play files stay in the private
build cache. Coverage labels explicitly distinguish a current profile from a prior-completed-season
prior, and the probability weight remains zero.

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

### Chronological three-way soccer challenger

For learned research, clone or download the official `hudl/open-data` tree and choose one explicitly
published competition/season. The builder reads its match metadata and corresponding event files:

```powershell
python build_soccer_challenger.py --root C:\data\open-data `
  --competition-id 43 --season-id 106 `
  --rows-output soccer_challenger_rows.jsonl `
  --report-output soccer_challenger_report.json
```

The importer reconstructs the home/draw/away regulation result from periods 1-2 and excludes extra
time and shootouts. Missing event files, incomplete team pairs, or ordinary-match score mismatches
are rejected and counted rather than replaced with neutral values. Each match-date block is sealed
before any result or event can update later features.

Candidate families are opponent-adjusted xG strength, non-penalty shot quality, possession/field
tilt/pass completion, pressure, set-piece xG share, prior-match starting-XI continuity, and rest/
history context. Target-match lineups are never used retrospectively. Coverage indicators distinguish
real zeros from missing shot, territory, or lineup history. A regularized multinomial residual is
compared on identical matches with goal-rate Poisson and three-way Elo, and every family receives a
match-date-block ablation interval. The gate requires 500 out-of-sample matches, lower log loss than
both baselines, and an interval wholly below zero versus Poisson. It cannot self-promote, has zero
production weight, and remains `attach_live=false`.

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

### Validated run-strength challenger

The MLB challenger joins official Retrosheet event files to official game logs by Retrosheet game
ID. It seals every date block before updating team history, resets seasonal history, regresses Elo
between seasons, and never reads the target game's starter or lineup. Build it from locally
downloaded official archives with:

```powershell
python build_mlb_challenger.py --events-root C:\data\retrosheet\events `
  --gamelogs-root C:\data\retrosheet\gamelogs
```

The 2020–2025 validation parsed 13,046 complete games and produced 9,090 strictly out-of-sample
forecasts across 683 sealed date blocks. The full residual model improved log loss over
chronological Elo from `0.686457` to `0.682717`; its paired date-block difference was `-0.003739`
with a 95% interval of `[-0.005808, -0.001729]`. Of the tested families, only run strength showed
a stable incremental benefit. Bullpen workload, context, plate discipline, power/contact, and the
available run-prevention proxy did not clear their ablation intervals and receive no live weight.

A smaller live-reconstructible model therefore uses only prior team runs scored/allowed and games
played to derive Pythagorean strength and run differential per game. On the same out-of-sample
games it scored `0.682207` log loss and `0.244584` Brier versus Elo's `0.686457` and `0.246335`;
the paired log-loss interval was `[-0.007292, -0.001244]`. Current BALLDONTLIE standings totals can
reconstruct those exact two features, so eligible current MLB fixtures receive an
`mlb_challenger_shadow` receipt in the expanded view.

This clears only the historical gate. The artifact is frozen through `2025-09-28`, remains
research-only with production weight zero, and must collect prospective evidence before it can
affect an official probability. Confirmed starting pitchers, target lineups, and timestamped bullpen
availability remain explicitly missing until an authorized pregame source is configured.

Required Retrosheet notice:

> The information used here was obtained free of charge from and is copyrighted by Retrosheet.
> Interested parties may contact Retrosheet at "www.retrosheet.org".

## Basketball — licensed normalized team-game boxes

The current BALLDONTLIE free adapter does not expose the box fields needed for four factors.
Do not fabricate them. When an authorized active provider/tier supplies team-game boxes, normalize
each row to:

`game_id, game_date, team, opponent, is_home, points, fgm, fga, three_pm, fta, orb, drb, tov`

Two rows per game are required. `three_pa` is optional for the three-point attempt profile. JSON may
be a list or `{ "rows": [...] }`; CSV uses the same headers. The profile builder rejects incomplete
pairs, duplicate team rows, negative statistics, made-field-goal counts above attempts, and made
three-pointers above total field goals instead of silently zero-filling bad boxes.

```powershell
python build_advanced_metrics.py basketball --input authorized_boxes.json `
  --sport NBA --source "Licensed provider name" --license "Exact plan/use grant" `
  --output advanced_metrics_nba.json
```

Output: possessions/tempo, raw and opponent-adjusted offensive/defensive/net ratings, eFG%,
turnover rate, offensive rebound rate, free-throw rate, three-point attempt rate when covered,
schedule strength, unique-opponent coverage, and the latest observed game date.

The chronological research challenger additionally requires `game_date` and an unambiguous
`is_home` value on both rows. It seals each date block before updating team history, so two games on
the same date cannot leak results into one another. Build its point-in-time rows and report with:

```powershell
python build_basketball_challenger.py --input authorized_boxes.json `
  --rows-output basketball_challenger_rows.jsonl `
  --report-output basketball_challenger_report.json
```

The challenger tests adjusted efficiency, shooting, possession/four-factor, tempo, and rest/history
families as residual corrections to chronological Elo. Every family receives a full-versus-removed
out-of-sample comparison with a game-date block interval. Missing three-point-attempt coverage is
league-mean imputed with an explicit coverage feature. The promotion gate requires at least 500
out-of-sample games, better log loss than Elo, and an interval wholly below zero. This is offline,
zero-weight research; there is no live attachment or production model promotion.

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

### Chronological NCAAF challenger

The learned research path uses authorized game-level exports, not a season-end aggregate. It expects:

- `games.json`: CFBD `/games` rows with `id`, `season`, `week`, teams, final points, completion,
  neutral-site status, and start date;
- `advanced_games.json`: two normalized `/stats/game/advanced` team rows per game containing
  `gameId`, `team`, and offense `plays`, `ppa`, `successRate`, and `explosiveness`;
- `talent.json`: `/talent` rows augmented with `season`/`year` and the week the snapshot was
  available (`available_week`, normally `0` for a verified preseason composite).

```powershell
python build_cfb_challenger.py --games games.json --advanced advanced_games.json `
  --talent talent.json --rows-output cfb_challenger_rows.jsonl `
  --report-output cfb_challenger_report.json
```

Incomplete advanced-game pairs are rejected. Each complete season-week is sealed before history,
opponent adjustments, or Elo update, so a Saturday result cannot enter another target in the same
week. In-season history resets at each season boundary; Elo regresses toward average, while talent
uses only a declared pre-target snapshot. The challenger tests raw PPA, success, explosiveness,
internally opponent-adjusted versions, talent priors, and context through expanding-window family
ablations. Its gate requires at least 500 out-of-sample games, better log loss than Elo, and a
season-week bootstrap interval wholly below zero. It cannot promote itself and has production
weight zero.

CFBD's own modeling guidance likewise warns that features must include only games played before the
prediction week. A season-end `/stats/season/advanced` response is valid for current descriptive
profiles but is not valid historical pregame evidence.

## Expanded-view research reasoning

`research-signals.js` renders any approved `advanced_metrics` profiles and the NFL or MLB learned shadow
already attached to a fixture. The panel shows both teams, source/license, season role, build date,
coverage, and an explicit production-weight-zero receipt. Missing approved coverage is displayed as
missing for NFL/NCAAF/basketball rather than silently converted to an average.

After the adaptive provider pass, `populate_research_signals.py` runs locally against cached fixture
JSON and embeds any approved profile already present in the build cache. This does not trigger an
extra provider refresh. The `research_signal_schema` receipt makes successful population auditable.
This improves visible reasoning and preserves the evidence in pick locks. It does not change
`predict()` weights. A challenger may affect official probabilities only after its frozen out-of-
sample and prospective promotion gates pass.

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

### Authorized NFL availability intake

`nfl_availability.py` defines the point-in-time contract for quarterback, offensive-line, and
other roster-status observations. It does not scrape or fetch a source. A batch can be ingested
only when it declares `licensed`, `open_license`, `first_party`, or
`user_supplied_with_permission`, includes a source reference, and is recorded before kickoff.
ESPN-origin batches, post-kickoff records, future-dated observations, unknown statuses, and
timezone-free timestamps are rejected.

Example authorized input:

```json
{
  "source": "Configured licensed provider",
  "authorization_basis": "licensed",
  "source_reference": "provider-contract:nfl-availability",
  "fetched_at": "2026-09-09T15:00:00Z",
  "observations": [{
    "fixture_id": "provider-game-id",
    "kickoff": "2026-09-10T00:20:00Z",
    "observed_at": "2026-09-09T14:55:00Z",
    "team_code": "SEA",
    "player_id": "provider-player-id",
    "player_name": "Player name",
    "position_group": "QB",
    "role": "STARTER",
    "status": "QUESTIONABLE",
    "confidence": 0.9
  }]
}
```

Ingest with `python ingest_nfl_availability.py --input batch.json`. The resulting
`nfl_availability_ledger.jsonl` is append-only, SHA-256 chained, and gitignored. Current status is
attached to the NFL shadow receipt and frozen by the forecast ledger. It does not adjust a
probability: `production_weight` and `availability_probability_adjustment` are both zero until a
licensed historical/prospective sample supports a separately tested effect.

### Chronological Elo calibration

Version `nfl-challenger-0.3.0-calibrated-elo-shadow` fits an intercept and slope for raw Elo inside
each historical training window, then applies that calibrator to the next untouched block. Advanced
and quarterback features are subsequently trained only as residual corrections to calibrated Elo.
The production heuristic remains unchanged.

Across 844 out-of-sample forecasts, calibrated Elo improved log loss from `0.652560` to `0.640552`
and Brier score from `0.227370` to `0.224223`. Its paired week-block log-loss delta versus raw Elo
was `-0.011611`, with a 95% interval of `[-0.023072, -0.000895]`. This clears the separate gate for
prospective shadow evaluation, not production promotion. The advanced-feature residual challenger
scored `0.642373`; its interval versus calibrated Elo was `[-0.010197, 0.014477]`, so it still has
no demonstrated advantage and remains zero-weight.

### Prospective NFL shadow scorecard

The evaluation protocol is frozen in `nfl_prospective_scorecard.py`. It reads the verified
append-only ledger rather than current fixture state, pairs each unique pregame lock with the
latest appended result correction, and compares raw Elo, calibrated Elo, and the advanced
challenger on the same games. Ties, post-kickoff locks, duplicate locks, incomplete probabilities,
and non-shadow records are excluded with explicit counts.

Run it after NFL locks begin settling:

```powershell
python build_nfl_prospective_scorecard.py `
  --ledger forecast_ledger_nfl.jsonl `
  --output nfl_prospective_scorecard.json
```

The primary metric is log loss, with Brier score and calibration bands as secondary diagnostics.
Paired uncertainty uses a deterministic kickoff-week block bootstrap. Review is disabled until at
least 256 eligible games across 16 kickoff-week blocks; reaching that threshold never promotes a
model automatically. The generated report is gitignored and every row retains its lock and grade
event IDs so the result can be audited against the hash chain.

### Timestamped market benchmark

`market_snapshots.py` accepts authorized decimal odds or explicit implied probabilities for
two-way moneyline and three-way 1X2 markets. It derives no-vig probabilities by normalizing the
implied outcome probabilities, preserves the raw overround, and appends every batch to a separate
SHA-256-chained ledger. Source/reference metadata is mandatory, ESPN-origin inputs are excluded,
and a snapshot must be both observed and recorded before kickoff.

An input batch has this shape:

```json
{
  "source": "Configured licensed odds provider",
  "authorization_basis": "licensed",
  "source_reference": "provider-contract:odds",
  "fetched_at": "2026-09-09T17:00:00Z",
  "snapshots": [{
    "fixture_id": "provider-game-id",
    "competition": "NFL",
    "kickoff": "2026-09-10T00:20:00Z",
    "observed_at": "2026-09-09T16:59:00Z",
    "market_type": "moneyline",
    "odds_format": "decimal",
    "outcomes": {"h": 1.8, "a": 2.1}
  }]
}
```

Ingest and evaluate with:

```powershell
python ingest_market_snapshots.py --input odds-batch.json
python build_market_benchmark.py `
  --forecast-ledger forecast_ledger_nfl.jsonl `
  --market-ledger market_snapshot_ledger.jsonl
```

`market_benchmark.py` compares Matchday's frozen independent forecast against the captured opening
proxy (the earliest snapshot actually recorded per source), lock-time consensus, and closing
consensus on identical graded fixtures. Consensus is the equal mean of the latest eligible no-vig
probability from each source. A snapshot counts at lock only if both its observation and ledger
recording timestamps precede the lock; retrospective timestamps cannot enter that comparison.
Three-way markets use the regulation market result when it differs from knockout advancement.
Reports show coverage, paired competition-week bootstrap intervals, movement from lock to close,
and source/event receipts. They never modify production predictions.

### Honest baseline tournament

`baseline_tournament.py` scores six frozen candidates: an expanding competition prior, raw Elo,
calibrated Elo, Matchday's independent forecast, Matchday's market-informed forecast, and the
no-vig lock market. The competition prior uses only results whose grade event was already recorded
by the target forecast's lock time, with symmetric Dirichlet(2) smoothing; later games and later
result corrections cannot leak backward.

Run the tournament over any verified forecast ledgers, optionally supplying the authorized market
ledger for multi-source lock consensus:

```powershell
python build_baseline_tournament.py `
  --forecast-ledger forecast_ledger_nfl.jsonl `
  --market-ledger market_snapshot_ledger.jsonl
```

When the separate market ledger has no eligible lock-time record, the evaluator can use the
normalized market snapshot already frozen inside the official forecast lock and labels that basis
explicitly. Two-way raw/calibrated Elo are omitted from incompatible three-way events. Overall
coverage is reported, but every head-to-head score and confidence interval is recalculated on the
exact same fixtures. All-model review requires 256 common games across 16 common competition-week
blocks and still cannot trigger automatic promotion. The generated report is gitignored.
