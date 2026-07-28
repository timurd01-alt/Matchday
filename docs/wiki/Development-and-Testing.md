# Development and Testing

Matchday is primarily a Python data pipeline and static web application, with small server components for optional online features.

## Repository map

- `fetch_data.py` builds normalized competition data, model outputs, durable locks, and grades
- `multi_fetch.py` schedules adaptive pregame and result-pending fetches
- `provider_adapters.py` translates provider responses into Matchday contracts
- `app-1-core.js` through `app-4-features.js` power the main interface
- `content.js` and `generate_posts.py` publish pregame analysis and verified postgame recaps
- `index.html`, `content.html`, `qa.html`, and `styles.css` define the public product surfaces
- `api/` and `server/` contain optional online components

## Local setup

Use [SETUP.md](https://github.com/timurd01-alt/Matchday/blob/main/SETUP.md) for current local instructions. API credentials belong only in ignored local configuration or the deployment environment; never commit them.

## Prediction integrity invariant

For each eligible upcoming fixture, the fetch must persist a verified pregame lock. For each provider-confirmed final fixture with a verified lock, it must persist the official result and a Boolean hit/miss grade. The selected outcome and confidence cannot change after lock. A failed persistence postcondition must fail the fetch rather than publish partial accountability data.

## Required regression suite

For prediction, provider, scheduling, article, or grading changes, run:

```bash
python -m unittest test_analysis_mode test_news_freshness test_score_refresh test_multi_fetch test_pick_lock_persistence test_recovered_mlb_picks test_model_inputs test_provider_adapters test_security test_generate_posts test_backfill_history
```

This suite covers the pregame/postgame presentation, seven-day news cutoff, hourly result-fetch policy, lock persistence, recovered picks, final-result grading, provider contracts, generated-content accountability, and historical backfill behavior.

Tests should accompany changes to ranking logic, provider normalization, grading, locking, or confidence behavior. A provider failure should degrade honestly—usually to an empty, result-pending, or explicitly projected state—rather than fabricate data.

## Security

Read [SECURITY.md](https://github.com/timurd01-alt/Matchday/blob/main/SECURITY.md) before publishing or deploying changes. Never include API keys, private pick logs, raw credential-bearing errors, or local configuration in an issue or pull request.
