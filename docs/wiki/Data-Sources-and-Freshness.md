# Data Sources and Freshness

Matchday uses provider APIs and licensed or permissively licensed datasets. Coverage differs by sport and account tier.

Current provider families include:

- football-data.org for supported soccer competition data
- The Odds API for available market information
- BALLDONTLIE for supported US sports feeds
- CollegeFootballData and CollegeBasketballData for NCAA data
- Sportmonks for optional soccer detail such as lineups and injuries
- nflverse-data for supported NFL player-stat categories
- API-FOOTBALL for specific supported soccer detail and historical windows

Matchday does not use ESPN as a data source.

## Freshness

Refresh timing depends on the competition, whether matches are live, provider quotas, and the type of data. Live periods can refresh more frequently; slower-moving college and historical feeds use longer caches. Starting lineups may not exist until shortly before kickoff.

A displayed update time describes the generated Matchday dataset, not necessarily the publication time of every upstream field. Provider outages, quota limits, postponed events, and correction delays can temporarily affect freshness.

## Missing information

An empty lineup, injury list, table, or leaderboard does not mean Matchday verified that nothing exists. It can mean the provider or subscription tier does not supply that field. Matchday intentionally avoids inventing missing data.

The canonical provider checklist and attribution notes live in [PROVIDER_COMPLIANCE.md](https://github.com/timurd01-alt/Matchday/blob/main/PROVIDER_COMPLIANCE.md). That document is an engineering checklist, not legal advice.
