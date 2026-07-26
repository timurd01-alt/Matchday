# Matchday provider compliance notes

Reviewed: 2026-07-25 (Polymarket evaluated as a possible internal-only calibration reference for
`audit_model_vs_market.py` and rejected -- Section 4.2's automated-access/scraping ban and
Section 1's Restricted-Territory Content-vs-Technology-Features split, both quoted below, block it
regardless of the narrow internal-only/non-displayed use case; API-FOOTBALL box scores/lineups wired into `build()` and a new injuries
feed added on the same key, both detailed below; NCAAF/NCAAM season player-stat leaders added
via CFBD/CBBD's `/stats/player/season`, on the same keys already used for
schedules/standings/talent/recruiting; MLB tier turned on in the sport picker; BALLDONTLIE
disclosure on `legal.html` updated to name MLB alongside NBA/NFL; NFL season player-stat leaders
added from nflverse-data's `stats_player` release under CC BY 4.0, with nflverse-data's separate
`espn_data` release explicitly excluded, detailed below; six fabricated/unverified The Odds API
outright-market sport_keys for UCL and the five domestic leagues removed after live verification
against the provider's own sports catalog, detailed below). This is an engineering checklist, not
legal advice.

## Launch rules

- Keep every API key in `config_keys.py` or server environment variables. Never
  expose a key in browser JavaScript, generated JSON, screenshots, or Git.
- **STANDING RULE: Matchday may not use ESPN as a data source, in any form,
  at any time, under any code path -- full stop -- unless and until ESPN's
  own terms of service / a signed licensing agreement explicitly permits the
  specific use.** This is not a preference to be re-litigated per feature; it
  applies to every future addition (scores, stats, rankings, standings,
  leaders, lineups, injuries, news, images, video, anything) regardless of
  how it's sourced (direct API, RSS/Google News carryover, a third-party
  aggregator that re-serves ESPN content, scraping, etc.). If a future task
  would pull ESPN-originated content through any path, stop and flag it
  instead of implementing -- do not assume an exception applies. Today's
  status: ESPN's site-JSON endpoints (scoreboard/summary/rankings/standings/
  leaders) have been removed from the codebase, not just disabled, because
  Matchday has no licensed ESPN developer feed. ESPN is also excluded as a
  News tab source: any item attributed to ESPN is rejected both on fresh
  intake and when merging in a previous run's cached headlines for
  feed-diversity carryover (`_is_espn()` in `fetch_data.py`, a whole-word
  case-insensitive match against source/feed/label -- not just an exact
  `"ESPN"` string, since an exact match was found on 2026-07-25 to let
  ESPN-branded variants like "ESPN.com" slip through both checks; see the
  Changelog below). Use only documented provider API endpoints in general.
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
  Outright/futures markets are a small, fixed catalog, not "every sport_key
  plus `_winner`" -- confirmed live against the account's own `/v4/sports/
  ?all=true` (2026-07-25; this endpoint is documented as free of usage-credit
  cost, so it was safe to call even with the monthly quota exhausted). The
  catalog held exactly 12 `has_outrights: true` sport_keys account-wide: the
  six US majors/college (`americanfootball_nfl_super_bowl_winner`,
  `basketball_nba_championship_winner`, `baseball_mlb_world_series_winner`,
  `icehockey_nhl_championship_winner`, `americanfootball_ncaaf_championship_winner`,
  `basketball_ncaab_championship_winner`), four golf majors, the US
  presidential election, and exactly one soccer entry --
  `soccer_fifa_world_cup_winner` (WC's own, currently `active: false` between
  cycles). `COMPETITIONS` in `fetch_data.py` had five domestic-league keys and
  one UCL key (`soccer_epl_winner`, `soccer_spain_la_liga_winner`,
  `soccer_italy_serie_a_winner`, `soccer_germany_bundesliga_winner`,
  `soccer_france_ligue_one_winner`, `soccer_uefa_champs_league_winner`) that do
  not exist in this catalog -- present since the initial commit, apparently
  guessed by analogy with the real American-sports keys rather than verified.
  Removed (set to `None`) on 2026-07-25; do not reintroduce any of them
  without re-checking the live catalog first, since this provider can add
  outright markets over time and the check is free to repeat.
- **BALLDONTLIE:** use the official API only; do not scrape, share the key,
  present data as official league data, or retain/redistribute it beyond
  reasonable application needs. Covers NBA, NFL, and MLB fixtures/scores on
  the free launch key -- MLB was fetched and cached since launch but only
  exposed in the sport picker starting 2026-07-25. Confirm the free-tier
  request/monthly-call quota still comfortably covers three sports' worth of
  polling before increasing refresh frequency for any of them.
- **API-Sports / SportsDataIO / Sportmonks:** use only products and endpoints
  included in the active subscription. Never resell the provider's raw data.
  API-FOOTBALL's `/fixtures/lineups` and box-score stats
  (`fetch_api_football_box_scores()` in `fetch_data.py`) were implemented but
  never called from `build()` or `main()` -- confirmed dead code since the
  initial commit by a 2026-07-25 audit. As of the same day this is now wired
  in: `build()` calls `fetch_api_football_box_scores(matches)` for soccer
  competitions right after the existing Sportmonks enrichment call, live-
  verified against a real in-progress fixture (Eliteserien, API-FOOTBALL
  fixture 1494712) to actually populate `m['stats_extra']` and `m['lineups']`
  on that run -- `box_score_edge` inside `_upset_adjustment()` (also
  previously dead, since it reads `stats_extra`) now computes a real nonzero
  value from real data too. A new `fetch_api_football_injuries()` (same file,
  called right after box scores/lineups) adds a first real injuries feed for
  soccer, via `/injuries?fixture={id}` -- feeding `predict()`'s existing
  injury-weighting nudge, which previously had no real soccer data to work
  with since every soccer adapter path left `m['injuries']` at its empty
  default. All three (lineups, box stats, injuries) share one API-FOOTBALL
  key and its 100/day free-plan quota, so injuries gets the smallest of the
  three caps (`API_FOOTBALL_MAX_INJURIES = 8`) and only targets LIVE and
  pre-kickoff UPCOMING fixtures (forward-looking team news has no value once
  a match is FINISHED, unlike stats/lineups which double as a post-match
  record) -- and reuses box scores' own `/fixtures`-by-date cache from the
  same run instead of paying for a second lookup. Confirmed live on
  2026-07-25 that API-FOOTBALL's `/injuries` response itself repeats every
  row verbatim (a provider-side duplicate, not a fetch bug); `_parse_af_injuries()`
  dedupes by player id before writing `m['injuries']`. Confirm current plan
  coverage against the actual dashboard before relying on any of this in
  production, same caution as CFBD/CBBD below.
- **CollegeFootballData / CollegeBasketballData:** the free key is suitable for
  testing and has a limited monthly allowance. Confirm the active tier permits
  the intended public-app traffic before production launch; do not assume that
  a technically accessible endpoint is included in the free plan. As of
  2026-07-25 this also covers `/stats/player/season` (season leaders,
  `CollegeFootballDataAdapter.leaders()` / `CollegeBasketballDataAdapter.leaders()`
  in `provider_adapters.py`): each pulls the whole league in one request rather
  than looping per team, so it stays call-count-cheap, but CFBD's full-league
  response alone is tens of megabytes -- it's cached for 24h
  (`COLLEGE_LEADERS_CACHE_MIN` in `fetch_data.py`), separately from the 8-hour
  schedule-bundle cache, specifically so it doesn't refetch every run. Only
  the top-3-per-category leaderboard is written to the public JSON payload;
  full per-player stat objects stay in-process, consistent with the
  no-bulk-download rule above.
- **nflverse-data:** public, unauthenticated GitHub release, no API key. The
  repository is CC BY 4.0 (SPDX `CC-BY-4.0`, confirmed against the actual
  LICENSE file via the GitHub API, not a summary page) -- attribution is
  required and is on `legal.html` next to the BALLDONTLIE NFL credit.
  Matchday only reads the `stats_player` release (`NflverseAdapter` in
  `provider_adapters.py`, "Player Summary Stats", built with R's
  `nflfastR::calculate_stats()` from play-by-play data). nflverse-data
  separately publishes an `espn_data` release ("ESPN Stats" -- ESPN Total
  QBR, `qbr_season_level.csv` / `qbr_week_level.csv`); per the ESPN standing
  rule above, that release is never fetched, and `stats_player`'s own
  columns were checked live and contain no ESPN-attributed field or value.
  Re-verify this separation if nflverse ever restructures `stats_player` to
  blend in another provider's columns. Only the top-3-per-category
  leaderboard is written to `data_nfl.json`, matching the CFBD/CBBD
  no-bulk-download precedent.
- **Open-Meteo:** the free API is non-commercial, rate-limited, and CC BY 4.0.
  Keep the visible Open-Meteo link next to weather. Upgrade or disable weather
  before adding ads, subscriptions, or another commercial use.
- **News RSS:** display only short headline metadata and link to the publisher.
  Do not copy article bodies or bypass publisher access controls.

## Recheck before release

Provider terms and tiers can change. Revisit the linked provider pages in
`legal.html`, confirm the dashboard's current providers against this list, and
record the review date here before each public release.

## Changelog

- **2026-07-25:** Evaluated Polymarket (the prediction market) as a possible *internal-only*
  second calibration reference for `audit_model_vs_market.py` -- alongside cached Odds API
  snapshots and AP polls, purely to sanity-check whether Matchday's own model probabilities are in
  a reasonable range for NFL/MLB/domestic soccer leagues/NCAAF, where cached odds coverage is
  currently thin. Never intended to be displayed on the live site or used as a betting feature.
  **Rejected.** Read Polymarket's actual Terms of Use directly (the July 17, 2026 version linked
  live from `polymarket.com/tos`, via the Google Doc it embeds -- not a third-party summary):
  - Section 4.2 (Prohibited Conduct) bars, with no purpose carve-out: "Use any data mining tools,
    robots, crawlers, or similar data gathering and extraction tools to scrape or otherwise remove
    data from the Site, any other Interface, or Features" and "Use any manual process to monitor
    or copy any of the material on the Site... for any other unauthorized purpose without our
    prior written consent." A scheduled script pulling the Gamma/CLOB API for internal comparison
    is exactly this kind of automated data-gathering tool -- the clause has no exception for
    non-displayed, non-commercial, or research/calibration use, so "internal only, never shown"
    does not cure it.
  - Section 1 lists the United States as a Restricted Territory and limits Restricted-Territory
    persons to "Content Features" (news/info) only, explicitly barring "Technology Features,
    including and in particular the Platform." This plausibly covers the CLOB/order-book API
    Matchday would need, and is broader than the narrower order-placement-only geoblock described
    in Polymarket's own API docs (`docs.polymarket.com/api-reference/geoblock`, confirmed live to
    geoblock new orders/trading, not GET requests -- read-only market data endpoints are not
    mentioned as geoblocked there). Whether "Platform"/"Technology Features" in Section 1 reaches
    read-only Gamma/CLOB data calls is a real ambiguity this review does not resolve -- flagging
    for an actual lawyer, not deciding it as an engineering judgment call.
  - Attribution is not required (Section 5.1's license grant has no attribution clause), and
    Polymarket does have real per-game markets for every sport in scope -- confirmed live
    (`polymarket.com/sports/nfl/games`, `/mlb/games`, `/epl/games`, `/bkcl/games` for Champions
    League) -- so neither of those was the blocker; the automated-access ban and the jurisdictional
    Technology-Features restriction are.
  - Confirmed the 2022 CFTC settlement/geoblock history (Restricted-Territory trading ban, VPN
    circumvention barred by Section 2.1.4) applies to the `polymarket.com` entity reviewed here. A
    separate CFTC-approved "Polymarket US" entity (`polymarket.us`, operated by QCX LLC) opened to
    US users in 2026 under its own Terms of Service (`polymarket.us/tos`) -- not reviewed here since
    it wasn't the entity in question and would need its own separate ToS check before any use.
  - **Not integrated.** No code was written for this; `audit_model_vs_market.py` is unchanged.
  - The actual root cause of "thin" reference-odds coverage for NFL/MLB/domestic-soccer/NCAAF is
    not a missing market -- `fetch_data.py`'s existing `ODDS_URL`
    (`/v4/sports/{sport}/odds/?regions=eu&markets=h2h,totals`) already covers all of these sports
    via the already-reviewed The Odds API; the account's match-level-odds quota is simply exhausted
    right now (confirmed live: HTTP 401 `OUT_OF_USAGE_CREDITS`, per `audit_model_vs_market.py`'s
    own docstring). Restoring or upgrading that quota, not adding a new provider, is the
    straightforward fix. No other odds/prediction-market aggregator was live-verified as part of
    this review, so none is being recommended as a replacement -- any future candidate needs the
    same live-verification rigor before use, not a search-result summary.
  - This is an engineering read of Polymarket's own posted terms, not legal advice. The
    Restricted-Territory / Technology-Features ambiguity above specifically should go to an actual
    lawyer before this is ever reconsidered.

- **2026-07-25:** Investigated a reported "strong domestic-soccer teams undervalued"
  prediction symptom, traced to hand-curated `ratings_<league>.json` files only covering a
  handful of teams per league (e.g. 8 of 18 for Bundesliga/Ligue1) -- every other team fell back
  to `rating_boost()`/`rating_parts()`'s flat neutral defaults, and soccer's `predict()` branch
  (unlike the American-sports branch) applied those defaults unconditionally instead of gating
  on whether a real rating existed, so two uncurated teams looked numerically identical to the
  model. The proposed fix mirrored the American branch's real mechanism: derive per-team
  strength from The Odds API's own championship-winner futures market
  (`apply_market_strength()`), extending it from NFL/NBA/MLB/NHL/NCAAF/NCAAM to domestic soccer
  via the `outright` keys already sitting in `COMPETITIONS`. Live-checked those keys against The
  Odds API's own `/v4/sports/?all=true` (free of usage-credit cost per the provider's docs, so
  safe to call with the monthly quota exhausted) before writing any of that code -- none of the
  five domestic-league keys, nor UCL's, exist in the provider's real catalog; only
  `soccer_fifa_world_cup_winner` (WC's) is real. This mechanism is therefore not available for
  domestic leagues or UCL at all -- The Odds API simply does not sell those futures markets right
  now. Implemented instead: (1) removed the six fabricated `outright` keys (see the-Odds-API
  entry above) so `fetch_outrights()` stops making a guaranteed-failing request every build cycle
  for those competitions; (2) gated soccer's `fifa`/`value`/`star` factors in `predict()` on
  `_ratings_lookup()` finding a real entry, same treatment the American branch's `class` factor
  already had, so an uncurated team now contributes zero rather than an identical phantom
  default (`fetch_data.py`, `parts()` inside `predict()`). The underlying ratings-coverage gap
  itself (most of a domestic table, and roughly 15 of UCL's 36 clubs, having no curated entry at
  all) remains open -- closing it needs either a real per-team squad-value data source (none of
  the currently-integrated providers offer one for domestic soccer) or expanding the hand-curated
  files, neither of which this change attempts. Regression coverage:
  `SoccerKnownRatingGateTests` and `OutrightMarketKeyVerificationTests` in
  `test_model_inputs.py`.
- **2026-07-25:** Added defensive/advanced-metric leader categories for NFL (nflverse:
  `def_sacks`, `def_interceptions`, `def_tackles_solo`, `def_tackles_for_loss`, `def_qb_hits` --
  same `stats_player` CSV already in use, confirmed live to carry these columns, no new release
  touched), NCAAF (CFBD: `defensive` category rows -- confirmed live that the existing unfiltered
  `/stats/player/season` call already returns them alongside the offensive categories, no second
  request), NCAAM (CBBD: `steals`/`turnovers`, flat fields on the same `/stats/player/season`
  row already pulled), and NHL (SportsDataIO: `PlusMinus`/`Hits`/`Takeaways`/`ShotsOnGoal`, same
  `PlayerSeasonStats` call). None of this adds a new provider, endpoint, or request -- every
  field already existed on a call this build was already making, confirmed against each
  provider's real response before writing the category definitions. Checked whether NBA/MLB
  (BALLDONTLIE) could get the same treatment: a live call against BALLDONTLIE's `season_averages`
  (NBA) and `season_stats` (MLB) endpoints with the current key returned 401 Unauthorized on
  both, confirming `BallDontLieAdapter`'s own docstring that the free plan excludes stats
  endpoints entirely. NBA/MLB advanced metrics stay blocked until either that plan is upgraded or
  a different provider is chosen for those two sports specifically.
- **2026-07-25:** Wired API-FOOTBALL box scores/lineups into `build()`
  (`fetch_api_football_box_scores()` in `fetch_data.py`, confirmed dead code
  since the initial commit by an earlier audit the same day) and added a new
  injuries feed (`fetch_api_football_injuries()` / `_parse_af_injuries()`,
  same file) -- soccer's first real injury data, feeding `predict()`'s
  existing injury-weighting nudge for the first time. Both calls sit in
  `build()` right after the existing `fetch_sportmonks_enrichment(matches)`
  call, for soccer competitions only. Verified live against real
  API-FOOTBALL fixtures (not the full `build()` pipeline -- Matchday's
  configured competitions have no live/near-kickoff fixtures right now,
  European domestic leagues being off-season until late August): confirmed
  `m['stats_extra']`, `m['lineups']`, and `m['injuries']` all populate
  correctly, that `box_score_edge` inside `_upset_adjustment()` computes a
  real nonzero value (0.493 against a real away-team-dominant fixture) and
  clears the `strong_box_override` threshold, and that `predict()`'s `why`
  breakdown picks up a real `injuries` entry end to end. Also found and
  fixed a real duplicate-records bug in the process: API-FOOTBALL's
  `/injuries` endpoint repeats every row verbatim (confirmed live -- 14 rows
  for 7 distinct players on one fixture, identical player id and fixture id
  each time), which would have silently doubled the injury-nudge weight per
  player; `_parse_af_injuries()` dedupes by player id. Only API-FOOTBALL's
  own "Missing Fixture" `player.type` is treated as a confirmed absence
  ("Questionable" is a doubt, not counted), matching the injury nudge's
  existing "hard out only" convention. Injuries get the smallest of the
  three shared-quota caps (`API_FOOTBALL_MAX_INJURIES = 8`) and only target
  LIVE/pre-kickoff-UPCOMING fixtures, reusing box scores' `/fixtures`-by-date
  cache from the same run rather than paying for a second lookup. 11 new
  regression tests added in `test_model_inputs.py` (injuries parsing/dedupe,
  predict() integration confirming only confirmed-out counts, box_score_edge
  against a real API-FOOTBALL stats shape, and quota-safety guards).
  `python -m unittest test_model_inputs test_provider_adapters
  test_generate_posts` stays green (66 tests). Model weighting/thresholds
  (e.g. `strong_box_override`'s 0.35/75 cutoffs, the per-sport injury
  weight) were not touched -- this is a data-wiring change, not a model
  change; that distinction stays with `predictions`/the site owner.

- **2026-07-25:** Added NCAAF/NCAAM season player-stat leaders
  (`CollegeFootballDataAdapter.leaders()` / `CollegeBasketballDataAdapter.leaders()`
  in `provider_adapters.py`, wired via the new `fetch_college_leaders()` cache
  helper in `fetch_data.py`). Uses the existing CFBD/CBBD keys and their
  `/stats/player/season` endpoint -- `team` is optional on both, so each pull
  covers the whole league in a single request instead of looping per team,
  matching `talent()`/`recruiting()`'s existing per-run request budget.
  Neither endpoint's own classification filter actually restricts the
  results (confirmed live: `/stats/player/season?classification=fbs` returns
  the same 289-team, all-division payload as no filter at all), so both
  adapters cross-check every player's team against a real FBS/D-I team list
  fetched separately (`/records?classification=fbs` filtered by each row's
  own `classification` field for CFBD; `/teams` for CBBD) before ranking --
  otherwise a small-school stat leader against weak competition could
  out-rank the real national leaders. CFBD's full-league response is tens of
  megabytes, so this data gets its own 24-hour cache
  (`COLLEGE_LEADERS_CACHE_MIN`), independent of the 8-hour schedule-bundle
  cache, rather than riding along with a shorter TTL. Only the derived
  top-3-per-category leaderboard is written into `data_ncaaf.json` /
  `data_ncaam.json`; the full per-player reshape stays in-process. Display
  only -- player stats are not read anywhere in `predict()` or any other
  model input; that remains a separate decision for the site owner.
  `python -m unittest test_model_inputs test_provider_adapters
  test_generate_posts` stays green (55 tests, 3 added for this change).

- **2026-07-25:** Live `"source":"ESPN"` / `"feed":"ESPN"` items (dated
  2026-07-17, pre-dating the ESPN news exclusion added in `a96c50e` on
  2026-07-24) were found sitting in the checked-out `data_bundesliga.json`,
  `data_ligue1.json`, `data_mlb.json`, `data_ncaam.json`, `data_nhl.json`,
  and `data_ucl.json` news arrays, with one rendering live in the MLB news
  feed. Root-caused to two things in `fetch_data.py`:
  1. Those specific competitions simply hadn't been re-fetched since the
     carryover-path fix in `318fbc8` (2026-07-25 00:32) landed, so the
     already-tightened filter hadn't had a chance to scrub them yet -- a
     timing gap, not a logic gap, for those exact stale rows.
  2. A real, still-live logic gap: both ESPN checks (`add_item()` on fresh
     RSS/Google-News intake and `_balanced_news()` on cached-headline
     carryover) rejected only an *exact* `label == "ESPN"` match. Google
     News' `<source>` tag can attribute ESPN-syndicated/regional content
     under other strings ("ESPN.com", "ESPN NFL Nation", "ESPN Deportes",
     "ESPN India", lowercase "espn", etc.) that `_source_label()` does not
     normalize to canonical "ESPN" (it only special-cases "espn fc"), so
     those variants passed both checks uncaught.
  Fixed by adding `_is_espn()` in `fetch_data.py` -- a case-insensitive,
  whole-word `espn` match against the raw `source`/`feed` fields and the
  normalized label -- and using it at both rejection points instead of the
  exact-string check. Existing cached files were already hand-cleaned by an
  engineer before this review; this closes the code path so future fetch
  runs can't reintroduce ESPN items through either intake or carryover.
  `python -m unittest test_model_inputs test_provider_adapters
  test_generate_posts` stays green (52 tests). No provider-terms
  interpretation changed here; this is an engineering checklist note, not
  legal advice.
