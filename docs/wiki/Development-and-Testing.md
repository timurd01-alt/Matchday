# Development and Testing

Matchday is primarily a Python data pipeline and static web application, with small server components for optional online features.

## Repository map

- `fetch_data.py` builds normalized competition data: fixtures, scores, market odds, weather, news, standings and the game archive. It does not forecast.
- `trdlab_handoff.py` validates the engine's `trdlab_picks.json` and attaches each pick to its fixture; `build_cfb_snapshot.py` builds `matchday-cfb-snapshot.js` (picks, scorecard, ratings, results)
- `multi_fetch.py` schedules adaptive pregame and result-pending fetches
- `provider_adapters.py` translates provider responses into Matchday contracts
- `game_archive.py` / `archive_backfill.py` keep the raw record of every finished game
- `app-1-core.js` through `app-4-features.js` power the main interface
- `generate_posts.py` publishes pregame analysis and postgame recaps
- `index.html`, `qa.html`, and `styles.css` define the public product surfaces
- `api/` contains the Vercel API for community picks

## Local setup

Use [SETUP.md](https://github.com/timurd01-alt/Matchday/blob/main/docs/SETUP.md) for current local instructions. API credentials belong only in ignored local configuration or the deployment environment; never commit them.

## Tests

Run the same command CI runs:

```bash
python -m unittest discover -p "test_*.py"
```

Tests should accompany changes to provider normalization, the handoff, or the archive. A provider failure should degrade honestly -- usually to an empty, result-pending, or explicitly projected state -- rather than fabricate data.

## Security

Read [SECURITY.md](https://github.com/timurd01-alt/Matchday/blob/main/docs/SECURITY.md) before publishing or deploying changes. Never include API keys, private pick logs, raw credential-bearing errors, or local configuration in an issue or pull request.
