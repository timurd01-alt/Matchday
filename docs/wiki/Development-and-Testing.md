# Development and Testing

Matchday is primarily a Python data pipeline and static web application, with small server components for optional online features.

## Repository map

- `fetch_data.py` builds normalized competition data and model outputs
- `provider_adapters.py` translates provider responses into Matchday contracts
- `app-1-core.js` through `app-4-features.js` power the main interface
- `index.html` and `styles.css` define the primary dashboard shell and styling
- `api/` contains serverless endpoints
- `server/` contains alternative server components and deployment notes
- `test_model_inputs.py` tests model construction and prediction behavior
- `test_provider_adapters.py` tests provider normalization and fallback behavior
- `test_generate_posts.py` tests generated social content

## Local setup

Use [SETUP.md](https://github.com/timurd01-alt/Matchday/blob/main/SETUP.md) for the current local instructions. API credentials belong only in the ignored local configuration or deployment environment; never commit them.

## Required regression suite

For prediction, provider, or college-ranking changes, run:

```bash
python -m unittest test_model_inputs test_provider_adapters test_generate_posts
```

Tests should accompany changes to ranking logic, provider normalization, grading, or confidence behavior. A provider failure should degrade honestly—usually to an empty or explicitly projected result—rather than fabricate data.

## Security

Read [SECURITY.md](https://github.com/timurd01-alt/Matchday/blob/main/SECURITY.md) before publishing or deploying changes. Never include API keys, private pick logs, raw credential-bearing errors, or local configuration in an issue or pull request.
