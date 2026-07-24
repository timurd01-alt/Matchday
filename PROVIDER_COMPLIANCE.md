# Matchday provider compliance notes

Reviewed: 2026-07-23. This is an engineering checklist, not legal advice.

## Launch rules

- Keep every API key in `config_keys.py` or server environment variables. Never
  expose a key in browser JavaScript, generated JSON, screenshots, or Git.
- Use only documented provider API endpoints. ESPN's site-JSON endpoints
  (scoreboard/summary/rankings/standings/leaders) have been removed from the
  codebase, not just disabled, because Matchday has no licensed ESPN developer
  feed. ESPN remains only as a labeled source in the News tab's RSS-style
  headline links, which is a link-out, not a data feed.
- Show provider data inside Matchday's user-facing analytics experience. Do not
  offer raw feeds, bulk downloads, a proxy API, or a standalone data product.
- Keep the analytics/not-betting-advice language and independent-provider
  notices on `legal.html`. Do not describe third-party data as official league
  data or imply endorsement.
- Keep refresh windows and caches bounded. Respect the configured plan's rate,
  monthly-call, endpoint, application, and domain limits.
- Elo, SRS, probabilities, bracketology, and upset flags are Matchday-derived
  outputs. Preserve that distinction in the UI and legal notice.

## Provider-specific checks

- **football-data.org:** retain the visible required attribution, keep the key
  private, use one application/domain per subscription, and stay within the
  plan's request rate and competition coverage.
- **The Odds API:** user-facing analytics are permitted, but never redistribute
  the market data as a raw feed. Keep odds informational and verify plan quota.
- **BALLDONTLIE:** use the official API only; do not scrape, share the key,
  present data as official league data, or retain/redistribute it beyond
  reasonable application needs.
- **API-Sports / SportsDataIO / Sportmonks:** use only products and endpoints
  included in the active subscription. Never resell the provider's raw data.
- **CollegeFootballData / CollegeBasketballData:** the free key is suitable for
  testing and has a limited monthly allowance. Confirm the active tier permits
  the intended public-app traffic before production launch; do not assume that
  a technically accessible endpoint is included in the free plan.
- **Open-Meteo:** the free API is non-commercial, rate-limited, and CC BY 4.0.
  Keep the visible Open-Meteo link next to weather. Upgrade or disable weather
  before adding ads, subscriptions, or another commercial use.
- **News RSS:** display only short headline metadata and link to the publisher.
  Do not copy article bodies or bypass publisher access controls.

## Recheck before release

Provider terms and tiers can change. Revisit the linked provider pages in
`legal.html`, confirm the dashboard's current providers against this list, and
record the review date here before each public release.
