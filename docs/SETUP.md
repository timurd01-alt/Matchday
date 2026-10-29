# Matchday analysis — local setup

Matchday is a static college football and men's college basketball analysis app backed by a Python data pipeline. It publishes pregame predictions, locks them before kickoff, and grades them after official final results. It is not designed to be a live-score service.

## Run the interface without provider keys

From the repository folder:

```powershell
python -m http.server 8000
```

Open <http://localhost:8000>. The checked-in data files let you inspect the current interface without making provider requests.

## Provider credentials

Create an ignored `config_keys.py` beside `fetch_data.py` and add only the providers you use:

```python
ODDS_API_KEY = "your_key"
CFBD_KEY = "your_college_football_key"
CBBD_KEY = "your_college_basketball_key"
SPORTSGAMEODDS_KEY = "your_key"           # optional fallback market context
SPORTSDATAIO_KEY = "your_key"             # optional college injury overlay
SPORTSDATAIO_PREGAME_ENABLED = True         # only after rights + live quota headers are verified
```

Never commit `config_keys.py`. The production workflow writes credentials from GitHub Actions secrets and removes the file before assembling the public site.

## Current public coverage

- College football (NCAAF)
- Men's college basketball (NCAAM)

These are the only sports. Coverage within a sport still varies by provider, season, and account tier. Missing fields stay unavailable instead of being invented.

## Fetch data

Run one competition directly:

```powershell
python fetch_data.py --ncaaf
python fetch_data.py --ncaam
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

1. The engine writes `trdlab_picks.json` (picks, results, scorecard, ratings). `trdlab_handoff.py` validates it and attaches each pick to its fixture; `build_cfb_snapshot.py` builds `matchday-cfb-snapshot.js` for the browser.
2. Each pick locks before kickoff. The Scorecard page states the lock lead.
3. After the game is final the engine grades the locked pick. The graded record is `trdlab_picks.json` → `scorecard.sports.<sport>.recent`. A locked pick is never rewritten.
4. In-progress games are shown as result pending, not as a live scoreboard.

The Odds API is queried only for upcoming fixtures close to kickoff and the response is cached to protect quota. A missing market does not prevent the model from locking its independent prediction.


The expanded match view shows market, injury, lineup, starter/key-player, weather, and venue readiness using sport-native labels. Empty provider containers count as missing data. SportsDataIO can overlay injuries on the college feeds without replacing their schedules; endpoint availability still depends on the configured SportsDataIO product and account tier. Keep `SPORTSDATAIO_PREGAME_ENABLED` off for free-trial, replay, or personal/research-only access. Before production activation, confirm that the agreement permits live public redistribution, inspect the contracted tier's live quota headers, add its verified quota-ledger rule, and explicitly wire the enable flag into CI. New personnel and venue fields are captured as prospective shadows with production weight zero until they pass the model-promotion protocol.

## News and articles

The news feed accepts dated articles no more than seven days old. Undated or stale entries are rejected. Generated matchup previews are pregame-only; recaps require a verified locked pick and a final result.

## Test the integrity path

```powershell
python -m unittest discover -p "test_*.py"
```

See the [Wiki](https://github.com/timurd01-alt/Matchday/wiki) for product behavior and [PROVIDER_COMPLIANCE.md](PROVIDER_COMPLIANCE.md) for provider-specific notes.
