# Matchday analysis — local setup

Matchday is a static multi-sport analysis app backed by a Python data pipeline. It publishes pregame predictions, locks them before kickoff, and grades them after official final results. It is not designed to be a live-score service.

## Run the interface without provider keys

From the repository folder:

```powershell
python -m http.server 8000
```

Open <http://localhost:8000>. The checked-in data files let you inspect the current interface without making provider requests.

## Provider credentials

Create an ignored `config_keys.py` beside `fetch_data.py` and add only the providers you use:

```python
FOOTBALL_DATA_KEY = "your_key"
ODDS_API_KEY = "your_key"
BALLDONTLIE_KEY = "your_key"
CFBD_KEY = "your_college_football_key"
CBBD_KEY = "your_college_basketball_key"
API_FOOTBALL_KEY = "your_api_sports_key"  # optional soccer detail
SPORTMONKS_KEY = "your_token"             # optional soccer detail
```

Never commit `config_keys.py`. The production workflow writes credentials from GitHub Actions secrets and removes the file before assembling the public site.

## Current public coverage

- Soccer: World Cup, Champions League, Premier League, La Liga, Serie A, Bundesliga, and Ligue 1
- American football: NFL and NCAA football
- Basketball: NBA and NCAA men's basketball
- Baseball: MLB

NHL is intentionally excluded while its provider access remains unresolved. Coverage within a supported sport still varies by provider, season, and account tier. Missing fields stay unavailable instead of being invented.

## Fetch data

Run one competition directly:

```powershell
python fetch_data.py --mlb
python fetch_data.py --epl
```

Run one adaptive round for every public competition:

```powershell
python multi_fetch.py --once
```

Run the local adaptive scheduler:

```powershell
python multi_fetch.py
```

The production workflow runs hourly. The scheduler may use longer caches for distant fixtures or dormant seasons, but checks result-pending and near-kickoff competitions hourly. Browser reloads cannot make an upstream provider publish a result sooner.

## Prediction lifecycle

1. Upcoming fixtures receive a model probability and selected outcome.
2. Inside 12 hours of kickoff, the pick is written to the competition's `picks_log*.json` ledger as a verified pregame lock.
3. The selected side and confidence are not rewritten. If odds arrive later, market-comparison fields may be added without changing the locked pick.
4. In-progress games are shown as result pending, not as a live scoreboard.
5. After the provider marks a game final, the locked record is graded and persisted. A failed persistence check fails the fetch instead of silently publishing an ungraded result.

The Odds API is queried only for upcoming fixtures close to kickoff and the response is cached to protect quota. A missing market does not prevent the model from locking its independent prediction.

## News and articles

The news feed accepts dated articles no more than seven days old. Undated or stale entries are rejected. Generated matchup previews are pregame-only; recaps require a verified locked pick and a final result.

## Test the integrity path

```powershell
python -m unittest test_analysis_mode test_news_freshness test_score_refresh test_multi_fetch test_pick_lock_persistence test_recovered_mlb_picks test_model_inputs test_provider_adapters test_security test_generate_posts test_backfill_history
```

See the [Wiki](https://github.com/timurd01-alt/Matchday/wiki) for product behavior and [PROVIDER_COMPLIANCE.md](PROVIDER_COMPLIANCE.md) for provider-specific notes.

## NFL cold-start research

The checked-in `nfl_challenger_model.json` is a derived, research-only artifact built from the authorized nflverse play-by-play releases under CC BY 4.0; ESPN-origin releases remain excluded. It lets every clean CI build reproduce the same frozen raw-Elo, calibrated-Elo, and learned-residual shadows without downloading multi-season play-by-play during deployment.

Chronological out-of-sample testing found that calibrated Elo improved on raw Elo (844 games; log loss 0.640552 versus 0.652560, paired 95% interval for the improvement -0.023072 to -0.000895). The learned EPA/success/explosive/QB residual did not improve on calibrated Elo and remains at zero production weight. A separate early-season audit also found no reliable improvement from carrying those prior-season advanced features into weeks 1-4 or 1-8, so Matchday does not turn them into an official probability merely to fill sparse samples.

`forecast_ledger_*.jsonl` and `nfl_prospective_scorecard.json` persist in the private Actions cache. The expanded NFL view reports the calibrated-Elo prospective counter against a frozen minimum of 256 graded games across 16 kickoff weeks. While that evidence accumulates, the owner-approved historical pilot uses only 10% of the calibrated-Elo difference, caps movement at three probability points, and cannot flip the official pick. Reaching the prospective minimum permits manual review; it never automatically increases that weight.
