# Data Sources and Freshness

Matchday uses provider APIs and licensed or permissively licensed datasets. Coverage differs by sport and account tier.

The sources behind the college model:

- CollegeFootballData for NCAA football schedules, records, rankings, and roster-talent composites
- CollegeBasketballData for NCAA men's basketball schedules, team information, recruiting ratings, and box scores
- The Odds API for available pregame market information
- Open-Meteo for venue weather forecasts

Still fetched for the remaining competitions, and attributed for as long as they are:

- football-data.org for supported soccer competition data
- UEFA's published Technical Observer Team of the Season for the attributed completed-season Champions League XI
- BALLDONTLIE for supported NFL, NBA, and MLB feeds
- Sportmonks and API-FOOTBALL for optional supported soccer detail
- nflverse-data for supported NFL player-stat categories

Matchday does not use ESPN as a data source.

## Refresh model

Production runs an hourly pregame/postgame fetch. Result-pending and near-kickoff competitions are checked hourly; distant fixtures and dormant seasons may use longer provider caches. This cadence is intended to lock predictions and collect final results, not provide minute-by-minute scores.

The Odds API is queried only for upcoming fixtures close to kickoff—currently within three hours—and its response is cached for three hours. The independent model can still publish and lock when market data is unavailable.

Starting lineups, injuries, and other licensed details may not exist until close to kickoff and may be unavailable on a provider's current tier.

For a completed competition, Matchday may show an organizer's published Team of the Season when it can be linked and attributed directly. That editorial selection is labeled as official-source content, not model output. If neither a complete attributed selection nor enough real lineup data exists, Matchday shows the measured attacking leaders and does not call the partial list an XI.

## News freshness

Public news items must have a usable publication date and be no more than seven days old when the dataset is built. Undated or stale feed entries are rejected rather than presented as current coverage.

## Reading timestamps

A displayed update time describes the generated Matchday dataset, not necessarily the publication time of every upstream field. Provider outages, quota limits, postponed events, and correction delays can temporarily affect freshness. Reloading the browser only reads the latest published dataset; it cannot force an upstream provider to update.

## Missing information

An empty lineup, injury list, table, leaderboard, or market does not mean Matchday verified that nothing exists. It can mean the provider or subscription tier does not supply that field. Matchday intentionally avoids inventing missing data.

The canonical provider checklist and attribution notes live in [PROVIDER_COMPLIANCE.md](https://github.com/timurd01-alt/Matchday/blob/main/PROVIDER_COMPLIANCE.md). That document is an engineering checklist, not legal advice.
