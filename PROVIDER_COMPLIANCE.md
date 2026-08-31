# Matchday provider compliance notes

Reviewed: 2026-08-30 (college standings presentation correction. The public
conference tables no longer expose Matchday's incomplete local power rating;
they show only the compact analytical rating already present in the imported
college snapshot, with uncovered teams explicitly unavailable. No raw payload,
provider-only field, new endpoint, article content, or ESPN data was added.)

Reviewed: 2026-08-30 (college transition correction only. The existing news
surface still displays short headline metadata with direct publisher links;
three current NCAA.com/AP links were included in the college snapshot to keep
the feed useful while the normal provider refresh is rate-limited. No article
body, restricted provider field, new endpoint, or ESPN content was added.)

Reviewed: 2026-08-23 (development-pause notice only. The notice accurately
describes unresolved data licensing and permission requirements without
asserting unlawful prior acquisition, changing a provider, endpoint, source,
retained payload, redistribution scope, or the operating state of existing
forecasts and feeds.)

Reviewed: 2026-08-18 (MLB recovery and personnel-semantics hardening only. No
provider, endpoint, key, contracted tier, retained raw payload, or
redistribution scope changed. SportsGameOdds pitcher and hitter prop identities
remain compact non-ESPN bookmaker-derived research context, but are now kept
only as `starter_candidates` / `market_listed_hitters`; they cannot populate a
canonical lineup, confirmed starter, or high-confidence readiness state.
SportsDataIO remains disabled pending the existing commercial redistribution,
endpoint-entitlement, and live quota-header review. Its dormant normalizer now
preserves exact game/time, opener, per-player confirmation, and source
timestamps and rejects ambiguous same-team/doubleheader joins. BALLDONTLIE and
Retrosheet uses remain unchanged. Private zero-weight MLB shadow receipts add
no provider fields to the public API or site.)

Reviewed: 2026-08-16 (prediction archive, scorecard, and market-benchmark
display corrections only. No provider, endpoint, source, retained payload, or
redistribution scope changed. Existing normalized fixture outcomes and market
snapshots are now filtered to verified locked predictions, settled according
to each competition's existing regulation-versus-advancement rules, and
aggregated across the actual eligible samples. Client rendering changes use
plain-text DOM construction and do not expose additional provider fields.)

Reviewed: 2026-08-14 (season-boundary and Champions League display correction.
No provider, endpoint, source, or redistribution scope changed. Existing
football-data.org match metadata is now filtered so only league-phase fixtures
contribute to the live league-phase table, and completed-season tables and
brackets are withheld from current-season views while match results remain
available under the provider's existing attribution requirements.)

Reviewed: 2026-08-14 (NFL roster display semantics only; no new source,
endpoint, download, or production signal. The already-reviewed nflverse
expected-depth-chart view may establish whether both teams have normalized
coverage, but it has no validated player-quality grades and remains
unconfirmed/zero-weight. The UI now distinguishes "Roster coverage" from
"Roster edge" and explicitly marks the latter not scored instead of implying
that a covered depth chart is a numerical talent comparison.)

Reviewed: 2026-08-12 (MLB pregame personnel fallback. SportsGameOdds' existing
Version 3 application-display permission and 2,500-object Amateur allowance
were re-checked against its current MLB documentation. Matchday now requests
pitcher-strikeout and batter-hit markets inside the same bounded event objects
already used for game odds; the provider documents that market count does not
change object cost. Only players backed by an available non-ESPN bookmaker are
retained. Pitchers are labelled market-listed candidates, hitters are labelled
likely active/unordered, both remain unconfirmed and zero-weight, and no raw
odds/player payload is redistributed. A separate bullpen-rest proxy uses only
Matchday's existing fixture history (games in the prior 72 hours and time since
the previous game); it explicitly does not claim individual reliever usage or
availability. Big Balls' advertised MLB lineup route was live-tested and still
returned `meta.available=false` with empty arrays; its MLB injury call timed
out and opaque upstream provenance remains unresolved, so it stays disabled.
SportsFBI was rejected because its Terms limit the license to personal,
non-commercial use and prohibit redistribution/derivative competing products;
ClearSports was rejected because its free credits are for testing and its
Terms prohibit redistribution without permission. MySportsFeeds' free offer
is likewise personal/private. MLB StatsAPI remains excluded under MLB's
automated-access terms. No scraping or direct ESPN access was introduced.)

Reviewed: 2026-08-11 (NFL pregame context through nflverse. The current 2026
`depth_charts` and `weekly_rosters` release assets were live-verified through
GitHub's release API and carry source timestamps from 2026-08-10. nflreadr's
1.5.0 release notes state that depth charts are ESPN-derived starting in 2025;
this provenance is disclosed in every fixture receipt and in the UI. Matchday
publishes only a compact, normalized expected-starter view inside its analytics
experience, not the raw bulk file, and labels it unconfirmed rather than a
gameday lineup. The daily private cache avoids repeated bulk downloads. The
dedicated nflverse 2026 injury asset does not exist yet, so 2025 rows are never
carried forward or represented as current. Repository data is offered under CC
BY 4.0 and attribution is retained, but nflverse also warns that underlying
football data remain subject to owner terms; this is a residual licensing risk,
not a claim of ESPN/NFL endorsement. Direct ESPN endpoint access and scraping
remain disabled.)

Reviewed: 2026-08-10 (pregame-context retention and quota priority add no new
provider or endpoint. Normalized injuries, lineups, starters, weather, venue
context, and provenance already acquired from cleared sources are retained in
a fixture-id/team/kickoff-bound private CI cache so a later empty/transient
fixture rebuild cannot erase them. A kickoff or team-identity change prevents
carryover. API-FOOTBALL's existing injury and lineup calls now run before
postgame statistics against the same enforced daily/minute quota; this changes
priority only and does not bypass reserves, terms, or source restrictions.)

Reviewed: 2026-08-10 (CFBD quota reconciliation uses the provider's documented
`/info` endpoint, which the official CFBD guidance states does not count against
monthly limits. It is called only when the persisted ledger would otherwise
block a request, records the returned `X-CallLimit-Remaining`/`remainingCalls`
balance, and shares the persisted six-hour free-probe cooldown. The production
force-rebuild switch changes cadence only; it does not bypass provider quota
checks, safety reserves, source restrictions, or validation.)

Reviewed: 2026-08-10 (The Odds API quota reconciliation uses only the provider's
documented `/v4/sports` endpoint, whose official v4 guide states that it costs
zero usage credits and returns the standard remaining/used/last-cost headers.
It is called only after the private ledger would otherwise block a paid market
request, and its persisted six-hour claim prevents unbounded polling.)

Reviewed: 2026-08-10 (zero-cost coverage hardening. Added a pinned offline
OpenFootball `football.json` importer at revision
`a5dd38b3bcbe3aa2477cf400f569264253d51431`; the repository declares its
schema, data, and scripts CC0/public domain. Matchday accepts only completed
domestic-league results, validates fixture identities and scores, records the
exact revision/file/license on every normalized row, and keeps the resulting
corpus research-only and zero-weight. This is not a live provider and does not
authorize unrelated football sites or moving/unpinned GitHub datasets. The
provider-neutral manual availability contract remains provenance-gated,
pregame-only, tamper-evident, and zero-weight; no source is enabled merely
because it is publicly viewable or the site is noncommercial.)

Reviewed: 2026-08-08 (SportsGameOdds v2 free-tier market fallback. Version 3
Terms, dated 2026-06-23, permit Data to reach end users inside an application
that supplies material independent value, while prohibiting standalone feeds,
bulk exports, resale, and substitute services. The live Amateur key confirms a
2,500-object monthly ceiling and access to NFL, NBA, MLB, NHL, NCAAF, NCAAB,
MLS, and UEFA Champions League. Matchday requests at most eight near-term
events per supported competition (15 for a complete MLB slate), caches the
normalized result for 24 hours,
keeps a 100-object reserve, and does not persist raw payloads. Because the free
payload includes ESPN BET, provider-wide fair/consensus fields are rejected;
Matchday recomputes the game market only from matched non-ESPN bookmakers.
Event `players` are prop-linked identities, not confirmed lineups or injury
reports, so they are neither persisted nor represented as personnel coverage.)

Reviewed: 2026-08-07 (Big Balls Sports Data pregame adapter and quota handling are
staged but disabled. The provider's terms page identifies itself as an initial draft
with an effective date pending public launch; its public attribution page does not name
the upstream source for the NBA/NHL injury feed, and its OpenAPI description says the
gateway aggregates free-tier sources and scrapers while response provenance is an opaque
source tier. That is insufficient to prove the injury rows are not ESPN-originated, so
Matchday's standing ESPN exclusion prevents activation. The provider's machine-readable
contract also says stored lineups are not ingested, despite broader marketing claims;
MLB/soccer lineups, MLB injuries, starting pitchers, bullpens, NFL injuries, and college
injuries remain explicitly missing. A configured key alone cannot enable this overlay.)

Reviewed: 2026-08-07 (market-comparison hardening adds no provider or endpoint.
Authorized The Odds API consensus snapshots now retain exact competition, fixture,
kickoff, home/away orientation, source receipt, and observed/recorded timestamps in
the existing append-only research ledger. Legacy unordered pair-cache entries and
post-lock quotes are excluded from the official same-time benchmark. Closing quotes
remain a separately labeled diagnostic and cannot alter a locked forecast.)

Reviewed: 2026-08-03 (sport-aware pregame context and a disabled-by-default SportsDataIO
overlay; activation requires a live public-redistribution agreement and endpoint coverage.
Advanced-metrics shadow expansion: nflverse `pbp` CC BY 4.0 only,
StatsBomb Open Data selective historical research with required credit/logo, Retrosheet official
event downloads with its mandatory prominent notice before any transfer/publication, authorized
basketball box-score normalization, and CFBD `/stats/season/advanced`; ESPN-origin releases remain
excluded and NHL is explicitly outside this expansion. Generated profiles do not change production
picks. The first CFBD advanced refresh returned HTTP 429 and correctly remained unavailable.)

Reviewed: 2026-08-03 (the disabled-by-default Matchday Terminal X publisher adds a new
distribution surface but no provider, endpoint, scrape, raw payload, odds line, news text,
player data, or third-party mark. Prediction copy is derived only from Matchday's verified,
immutable pregame receipt after the same integrity gate used for grading; legacy,
quarantined, mutable, graded, and post-kickoff records are excluded. The publisher links
back to Matchday, uses X's official API, keeps credentials private, and makes no claim of
league affiliation, certainty, betting advice, or provider authorship.)

NFL challenger review: the 2021–2025 training corpus uses only the same nflverse `pbp` release
family already approved above. Source file hashes are embedded in every reconstructed training row
and model artifact. ESPN-origin releases remain excluded. Generated rows, fitted artifacts, and
backtest reports are local/gitignored, and the runtime loader enforces research-only, zero-weight
attachment to future fixtures.

Quarterback research uses passer identifiers and play outcomes already contained in the approved
nflverse `pbp` releases. It does not add a roster, injury, depth-chart, ESPN, or Sports Reference
source and does not infer that the last observed primary passer is a confirmed future starter.

Elo calibration adds no provider or dataset. It is fitted only from Matchday's chronological game
outcomes and stored inside the local zero-weight research artifact.

Reviewed: 2026-07-28 (UEFA's public 2025/26 Champions League Team of the Season is
manually transcribed as a small attributed editorial selection with a direct source link; no
automated UEFA scraping, bulk extraction, API claim, images, article text, or implied endorsement.)
Reviewed: 2026-07-28 (NCAAF roster-talent recovery uses one request to the already-licensed
CollegeFootballData talent endpoint before the broader build, then persists only Matchday's
derived rating fields; no raw provider payload is published or newly redistributed.)
Reviewed: 2026-07-27 (NCAAF and NCAAM's derived way-too-early projections now blend the
already-licensed CFBD/CBBD prior-postseason rankings feeds with their existing talent/recruiting
feeds; no new provider, endpoint family, raw-feed display, or redistribution behavior.)
Reviewed: 2026-07-26 (API-FOOTBALL's free-plan date restriction confirmed live against real past
match dates while building `backfill_lineups.py` -- historical dates outside a rolling ~3-day
window are rejected outright, same key/plan already licensed for live box scores/lineups/injuries,
no new provider; full detail in the Changelog below.)
Reviewed: 2026-07-26 (Five candidate sources -- Kaggle, the Sports Reference family,
WorldFootball.net, Flashscore, Sofascore, and Sportradar -- evaluated against live ToS text for
the historical-backfill and live-score gaps; Sports Reference, WorldFootball.net, Flashscore, and
Sofascore all rejected on explicit clause text, Sportradar rejected on practical accessibility
with a licensing-clause flag for a lawyer if that changes, and Kaggle explained as needing a
per-dataset check rather than a platform-wide call -- full detail in the Changelog below); a new
one-time `backfill_history.py` script added the same day to seed `ratings_elo.json` from real past
seasons on the providers already licensed above (CFBD/CBBD/BALLDONTLIE/football-data.org/
API-FOOTBALL, no new provider), a materially different bulk-historical-pull usage pattern from the
existing hourly incremental fetch -- detailed below.
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
- **ESPN sourcing rule:** Direct ESPN site/API access, scraping, images, video,
  article text, and bulk redistribution remain excluded because Matchday has
  no licensed ESPN developer feed.

  **Amended 2026-08-31 by the owner:** the News-tab exclusion is lifted. ESPN's
  public college RSS feeds (`/espn/rss/ncf/news`, `/espn/rss/ncb/news`) are now
  the college news source, and the `_is_espn()` intake rejection is removed.
  Only the headline and the link are stored -- no article text, no images, no
  bulk redistribution -- and ESPN is credited by name on every item. The
  residual risk is that these are publicly published feeds consumed without a
  licence agreement rather than under one; that is a decision the owner has
  taken knowingly. Every other clause of this rule still stands. A narrowly reviewed, openly licensed
  secondary release may be used only when its ESPN provenance is explicit,
  the exact asset/schema/cadence has been verified, Matchday publishes only a
  normalized analytical view rather than the raw feed, and the UI identifies
  it as ESPN-derived and unofficial. The only current exception is nflverse's
  2025+ depth-chart release described in the 2026-08-11 review above. ESPN is
  still excluded as a
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
- **OpenFootball (`openfootball/football.json`):** offline historical domestic-
  league results only, pinned to the reviewed CC0 revision above. Preserve the
  revision and per-row source file, reject incomplete or implausible scores,
  and validate identity/overlap before any production use. Do not present it as
  a live, official, lineup, injury, player-value, or event-stat source.
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
- **SportsGameOdds:** Version 3 Terms sections 30-41 allow Data to be shown to
  end users only as part of an application providing material independent
  value and prohibit standalone redistribution, bulk exports, resale, and a
  substitute data service. Keep the key server-side. The Amateur plan is
  currently marketed for testing/prototyping/initial development and provides
  2,500 objects/month, 10 requests/minute, eight leagues, and ten-minute
  updates; re-check the account and terms before treating the free offering as
  permanent production infrastructure. Use `/account/usage` before fetching,
  keep the 100-object reserve and 24-hour cache, and never expand the eight-
  event response cap without recalculating monthly consumption. Do not use
  provider-wide `fairOdds`/`bookOdds`/consensus fields because ESPN BET is one
  of the free plan's nine books. Build consensus only from `byBookmaker` after
  excluding every ESPN-labelled identifier. The event `players` map is tied
  to props and is not proof of a lineup, starter, injury, or availability.
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

- **2026-08-08:** Added SportsGameOdds as a quota-bounded fallback only when
  the existing Odds API has no near-term game market. Live account verification
  confirmed all eight advertised Amateur leagues and the real monthly counters.
  The adapter requests no more than eight upcoming events in a 36-hour window,
  once per competition per 24 hours, and persists only normalized market/venue
  fields. Consensus is rebuilt per bookmaker after removing overround and
  excluding ESPN BET; provider aggregate prices and raw event/player/odds
  objects are not stored. Market snapshot and lock receipts now preserve the
  actual provider identity instead of hardcoding The Odds API. SportsGameOdds
  does not clear injuries, lineups, probable starters, starting goalies, or
  bullpen availability because the verified event schema supplies none of
  those as authoritative personnel fields.

- **2026-08-07:** Staged a disabled-by-default Big Balls Sports Data injury
  adapter for the two competitions its active injury endpoint actually supports
  (NBA and NHL). Normalization joins full team names/codes, drops a report when
  its own expected-return date precedes the target fixture, records bounded
  provenance, and lets only hard Out/Inactive/Injured Reserve/Suspension labels
  enter the existing capped injury nudge. A 45-minute normalized cache and the
  provider's observed `X-RateLimit-*` headers protect the free tier. Production
  activation is blocked: the provider's terms are explicitly a pre-launch draft,
  the attribution page omits the injury source, and response metadata does not
  identify upstream vendors, so Matchday cannot enforce its absolute ESPN-origin
  exclusion. The machine-readable OpenAPI contract also states lineup ingestion
  is not active; no lineup, starter, bullpen, NFL, college, soccer, or MLB coverage
  is fabricated from marketing copy. The configured key is retained privately,
  but a key alone does not enable any request.

- **2026-07-28:** Replaced the incomplete six-player UCL "Model-built XI" presentation with the
  organizer's published 2025/26 Team of the Season (11 names/teams/positions only), visibly
  attributed and directly linked to UEFA's source page. This is a manually maintained editorial
  fact record, not an automated UEFA feed or scraped article. No UEFA images, prose, statistics,
  logos, or page markup are copied. When an attributed complete selection is unavailable, the UI
  now calls a partial scorer-derived result "attacking leaders" instead of falsely calling it an XI.
- **2026-07-26:** Built `backfill_lineups.py`, a one-time script to backfill Team of Tournament's
  defender/goalkeeper data for a just-finished competition (UCL's 2025-26 season ended in
  March/April, before the lineup-tracking feature existed) on the same API-FOOTBALL key already
  licensed for live box scores/lineups/injuries -- no new provider. **Confirmed blocked on the
  current free plan, not a code bug:** live-tested `/fixtures?date=` against real past match dates
  (including the UCL final itself, 2026-05-30) and every one returned `"errors":{"plan":"Free
  plans do not have access to this date, try from 2026-07-25 to 2026-07-27."}` -- the free plan
  only serves a rolling ~3-day window around whenever the call is made, which is why the existing
  live hourly fetch works fine (it only ever asks about LIVE/near-term matches) but a historical
  backfill structurally cannot, on any budget or schedule. Also confirmed the bulk season endpoint
  (`/fixtures?league=...&season=2025`, API-FOOTBALL numbers a season by its starting year) is
  separately blocked for the current season ("try from 2022 to 2024"). The script fails fast with
  this exact finding the moment it hits the wall rather than silently spending quota with zero
  progress. Left in place, unused, for if a paid plan is ever adopted, or for the 2022-2024 seasons
  specifically via the bulk endpoint.

- **2026-07-26:** Evaluated five candidate sources raised for two open gaps -- multi-season
  historical results (the `data` agent's backfill work is hitting real free-tier depth limits on
  CFBD/CBBD/BALLDONTLIE/API-FOOTBALL, e.g. soccer can't reach back past 2022) and live scores
  (currently football-data.org/BALLDONTLIE/API-FOOTBALL/Sportmonks). Read each source's actual
  current terms live, not a summary or prior knowledge, matching this document's standing rule.
  **Not integrated anywhere** -- this is a report-back-only pass, same posture as the Polymarket
  entry below; no code was written for any of the five.

  - **Sports Reference family (Baseball-Reference / Pro-Football-Reference /
    Basketball-Reference / Hockey-Reference, sports-reference.com) -- REJECTED.** Read
    `sports-reference.com/termsofuse.html` (Effective Oct 1, 2004, Last Updated May 19, 2023) and
    `sports-reference.com/data_use.html` live. Section 5 (Permitted Use) bars, without a
    non-displayed/internal-use carve-out: "use any material or Content from the Site, including
    without limitation any statistics or data, (i) to create any database, archive, or other data
    store that competes with or constitutes a material substitute for the services or data stores
    offered on the Site or by the Site's Data Providers or (ii) to provide any service that
    competes with or constitutes a material substitute for the services or data stores offered on
    the Site" -- language matching SRL's own stated worry in the same section about "a bad apple...
    creat[ing] a competing statistical database." The same section separately and explicitly bars:
    "copy or use any material or Content from the Site... for purposes of training, fine-tuning,
    prompting, or instructing artificial intelligence models or technologies in any manner,
    including without limitation for purposes of... (ii) supporting machine learning methods used
    to predict, classify, label, or score inputs into the models" -- a direct textual match for
    what Matchday's Elo/SRS pipeline would do with backfilled historical results, not an inferred
    analogy. The data_use.html page states this plainly in its own words: "you should not create
    websites or tools based on data you scrape from Sports Reference or any of our sites... without
    our permission," and sets a **$5,000 minimum** for any custom-data request, well outside what a
    hobbyist/indie project can absorb. Automated access separately requires "express written
    permission" per Section 5, backed by real rate limits (10 req/min on FBref/Stathead, 20/min on
    other SR sites, per the linked bot-traffic page) and active IP blocking. Two independent,
    on-point clauses plus a $5,000 cost floor -- a clean rejection on the provider's own terms, not
    a close call. SRL's own data_use.html page points to free alternatives worth a separate look for
    baseball/hockey specifically (Lahman Baseball Database, Retrosheet.org, Hockey Summary
    Project) -- not evaluated here, since they weren't the sources asked about, but noted for
    whoever picks this back up.
  - **WorldFootball.net (weltfussball.de/at/com, voetbal.com, mondefootball.fr, livefutbol.com;
    operated by Heimspiel Medien GmbH & Co. KG) -- REJECTED.** Read
    `worldfootball.net/terms/content_terms/` live (General Terms and Conditions of Use). No
    automated-access/scraping clause is present in the text at all, but a separate clause is
    categorical on its own: "You may only use or exploit our platform or content thereof personally
    and not commercially or for business purposes. In addition, you may not use our platform for
    advertising purposes. Unless you have our express permission to do so." Matchday is a
    public-facing product, not personal use, so this clause alone blocks it regardless of the
    scraping question. No official API or data-licensing product was found (live search turned up
    none; third-party scraper packages like `worldfootballR` exist but scrape it without
    authorization, they aren't a sanctioned path). Secondary, non-decisive signal: the site's own
    `robots.txt` (confirmed live) explicitly disallows AI-training crawlers (ClaudeBot, GPTBot,
    Amazonbot, etc.) via Content-Signal directives, consistent with the ToS's non-commercial-only
    posture -- noted for completeness, not the controlling document.
  - **Flashscore (flashscore.com, operated by Livesport s.r.o.) -- REJECTED.** No official public
    API exists at all (confirmed by live search: only unofficial third-party scrapers/wrappers on
    Apify, RapidAPI, and GitHub). Read the actual governing terms live at
    `livesport.eu/terms-of-use/en` (effective 2023-04-01; `flashscore.com/terms-and-conditions/`
    itself 404s directly but resolves through `livesport.eu/terms/flashscore_com/` to this
    document). License is explicitly "personal, non-exclusive, non-transferable... solely for your
    personal use." Separately: "You may not burden our server on which the Application is run with
    automated requests, nor may you assist a third party in such activity... you may not use the
    content of the Application by embedding, aggregating, scraping, or re-creating it without our
    express consent." And on top of that, a database-specific right: "no extraction (copying) or
    utilization (making available to the public) of Database Content or of a qualitatively or
    quantitatively substantial part thereof is permitted without our explicit consent." No API, an
    explicit scraping ban, and a personal-use-only license together make this a clean rejection,
    exactly the "no official API + ToS prohibits automated access = clean rejection, not a maybe"
    case.
  - **Sofascore (sofascore.com, operated by Sofa IT d.o.o.) -- REJECTED.** Sofascore does have one
    live, keyed public API (`api.sofascore.com/api/docs/external`, confirmed live) -- but it is a
    one-way **Betting Odds** ingestion endpoint (`GET`/`POST`
    `/api/external/v1/betting-odds/{oddsType}/{event}`) for odds partners to push odds data *into*
    Sofascore's platform, not a scores/results/statistics consumption API. It does not serve
    Matchday's live-score use case at all, so this isn't really an "official API" exception to the
    scrape-ban question -- there is no legitimate access path for what Matchday would need either
    way. The actual Terms & Conditions (`sofascore.com/terms-and-conditions`, last updated
    2024-09-18) read almost identically to Flashscore's (same template family): "User's decision to
    use the Platform... is solely at his/her own risk for personal use only. The Platform is not to
    be utilized for any commercial endeavors," plus "Burdening Sofascore's server with automated
    requests or assisting others in doing so is strictly prohibited... Using website content
    through embedding, aggregating, scraping, or reproducing without explicit consent is
    prohibited," plus a database-extraction clause matching Flashscore's almost verbatim. Same
    clean-rejection reasoning as Flashscore.
  - **Kaggle (kaggle.com) -- NOT a single source; no blanket call is possible, and none was made.**
    Kaggle is a hosting platform for individually-licensed community datasets, not one data source
    with one ToS -- any specific dataset needs its own check when the user names one. Two separate
    things govern any Kaggle-sourced data, read live from `kaggle.com/terms` (effective June 22,
    2025):
    1. **The platform Terms of Use** govern use of kaggle.com/its API itself, separate from any
       dataset's own license: "You will only use the Services for your own internal, personal,
       non-commercial use, and not on behalf of or for the benefit of any third party." Whether
       pulling a dataset through Kaggle's API into a public product like Matchday counts as
       "internal, personal, non-commercial use" is a real question this checklist does not resolve
       -- flagging for an actual lawyer, not deciding it as an engineering judgment call, same
       treatment as the Polymarket Restricted-Territory ambiguity below. Separately, "Crawls,"
       scrapes," or "spiders" any page... of the Services or Content" is barred, but this targets
       unauthorized scraping of Kaggle's own site, not use of Kaggle's sanctioned dataset-download
       API/CLI -- it isn't a bar to downloading a dataset the normal, intended way.
    2. **The dataset's own license** (CC0, CC BY, CC BY-SA, CC BY-ND, CC BY-NC, etc., set by the
       uploader in the dataset's metadata) governs the actual data content, and is what most people
       mean by "is this dataset OK to use." Critically, Kaggle does not verify an uploader's right
       to publish -- the platform ToU puts the burden entirely on the uploader: "You are responsible
       for all Content you contribute to the Services, and you represent and warrant you have all
       rights necessary to do so." A CC0 tag is only as good as that warranty being true. If an
       uploader actually built their "CC0" dataset by scraping a site whose own terms forbade that
       -- Sports Reference (rejected above, today) or ESPN (Matchday's standing exclusion) being the
       two examples directly on point for this project -- the CC0 tag does not cure the underlying
       provenance problem; it only means Kaggle disclaims responsibility and the risk lands on
       whoever ingests the data next.
    **Guidance for any specific dataset the user points to later** (not a platform-wide rule): (a)
    check the actual license tag in the dataset's metadata, not just its headline description; (b)
    check the dataset's own description/documentation for a stated original source -- a lineage
    claim of "scraped from Sports-Reference.com" or "scraped from ESPN" is an automatic rejection
    here regardless of the license tag, per today's Sports Reference finding and the standing ESPN
    rule; (c) prefer datasets with clear, checkable provenance (e.g., built from a source Matchday
    has already vetted, like nflverse-data) over ones with no stated lineage at all; (d) still
    resolve the platform-ToU commercial-use question above before any production use. No specific
    dataset was named or evaluated in this pass.
  - **Sportradar (sportradar.com) -- REJECTED for now, on accessibility, with a separate clause
    flagged for a lawyer if that ever changes.** Different in kind from the other four: a real,
    publicly-traded (NASDAQ: SRAD) official data vendor with direct league licensing agreements,
    not a scrape target -- the question here is accessibility and use-scope, not ToS legitimacy.
    Checked the actual developer portal live, not marketing pages: `developer.sportradar.com`
    states plainly "Sportradar's APIs are a B2B (Business-to-Business) service and are not intended
    to be called directly from a client application," and there is no published self-serve
    pricing anywhere in the portal -- access requires a sales conversation and a negotiated
    contract. A 30-day Free Trial does exist, but per the live Master Terms and Conditions
    (`developer.sportradar.com/sportradar-updates/page/terms-and-conditions`, effective July 14,
    2026; confirmed on two independent live fetches to guard against a summarization artifact) it
    is restricted to "Non-commercial internal evaluation only" -- explicitly not usable for display
    on a live public site. Production access requires the Fee-Based Service tier, which has no
    accessible entry point comparable to football-data.org/BALLDONTLIE/API-FOOTBALL/CFBD/CBBD's
    free tiers -- this is the practical blocker regardless of how clean Sportradar's licensing
    otherwise is. Separately, for if that ever changes: the same Master Terms bar, as a material
    breach, using the licensed data or service "for any prediction market, trading platform,
    financial product or similar offering without Company's prior written consent." Given Matchday
    is literally described as a sports-prediction analytics site, whether its own Elo/SRS/
    probability output falls inside or outside "similar offering" is a real, unresolved textual
    question -- flagging for an actual lawyer, not deciding it here, exactly like the Polymarket
    Restricted-Territory ambiguity below. Coverage itself is broad and real (dedicated soccer, NFL,
    NBA, MLB, NCAAF, NCAAB APIs per the live packaging page) and would be genuinely new
    historical-depth capability if ever accessible, not merely redundant with current providers --
    so this is worth revisiting if the site owner ever pursues a paid Sportradar relationship
    directly, at which point the prediction-market clause needs real legal review before use.

  This is an engineering read of each source's own posted terms and public developer-portal pages,
  not legal advice. The Kaggle platform-use question and the Sportradar prediction-market clause
  specifically should go to an actual lawyer if either is ever revisited, exactly as flagged above.

- **2026-07-26:** Added `backfill_history.py` -- a standalone, manually-run script (same
  run-when-needed posture as `update_ratings.py`, never part of the hourly `build()` loop or CI
  cron) that seeds the self-training Elo store (`ratings_elo.json`) with real past completed
  seasons, using only providers already licensed above -- no new provider, no new key. This is
  worth its own compliance note because a bulk historical pull (tens of thousands of games in one
  run for BALLDONTLIE's NBA/MLB coverage) is a meaningfully different usage pattern from the
  existing hourly incremental fetch that these same keys otherwise see, even though the
  request-per-call and rate-limit rules already documented above are unchanged and still apply.
  **Not run against production yet** -- built, tested, and dry-run validated only; the site owner
  decides when (if ever) to actually run it, since it permanently changes every live Elo-derived
  rating/prediction.

  Every provider-per-season assignment below was live-verified against the real endpoint on
  2026-07-26, not assumed from docs:
  - **WC (World Cup):** season 2022 only, via API-FOOTBALL (league id 1) -- confirmed live: 64
    fixtures, FT/AET/PEN, spanning the real Qatar 2022 opener (Qatar 0-2 Ecuador) through the
    third-place match (Croatia vs Morocco). football-data.org 403s on season 2022 and earlier for
    every competition, including this tournament, on the free plan -- so this is the only past
    World Cup reachable on either currently-integrated provider's free tier, not an arbitrary
    2-3-season choice. No earlier World Cup (2018, 2014, ...) is reachable this way.
  - **UCL, EPL, La Liga, Serie A, Bundesliga, Ligue 1:** season 2022 via API-FOOTBALL (league ids
    2/39/140/135/78/61 respectively, each confirmed live against a real completed-season fixture
    count -- e.g. EPL 380, UCL 203 including qualifying rounds, Bundesliga 308), seasons 2023-2025
    via football-data.org (confirmed live with `?season=YYYY`, e.g. EPL 2023 returned exactly 380
    matches with `resultSet.played: 380`). football-data.org and API-FOOTBALL's free plans both
    reach seasons 2023/2024 -- pulling both into Elo would double-count those two seasons, so this
    script always uses exactly one provider per (competition, season): API-FOOTBALL only for the
    one season football-data.org can't reach (2022), football-data.org for the rest. 2022-2025 (4
    seasons) is the real ceiling for these competitions on current free-tier access -- not 2000 as
    originally asked for elsewhere in this project -- because neither provider's free plan reaches
    further back (API-FOOTBALL: seasons 2021 and 2025 both fail; football-data.org: 2022 and
    earlier all 403). Reaching further back would need a different, likely paid, provider (see the
    Sportradar entry above).
  - **NCAAF, NCAAM:** seasons 2000 through the last fully-completed season, via CFBD/CBBD (same
    keys/endpoints already used for schedules/standings/talent/recruiting/leaders above) -- CFBD
    confirmed with no restriction found back to at least 1970 in an earlier investigation this
    session, CBBD the same pattern back to at least 2000; this script caps both at 2000 to match
    what was actually asked for, not because of any provider limit.
  - **NFL:** seasons 2002 through the last fully-completed season, via BALLDONTLIE. BALLDONTLIE has
    no NFL games before season 2002 on the free plan -- confirmed live with a full `per_page=100`
    request returning zero rows for both 2000 and 2001 (not a rate-limit artifact; the same request
    shape for 2002 returned real data). NFL therefore cannot reach the full 2000 floor the way
    NBA/MLB/NCAAF/NCAAM can.
  - **NBA, MLB:** seasons 2000 through the last fully-completed season, via BALLDONTLIE -- confirmed
    live at season 2000 for both (and NBA sampled all the way back to 1960 without emptying out, so
    2000 is nowhere near BALLDONTLIE's real floor for that sport).
  - **Team relocations/renames do not fragment Elo history:** confirmed live that both BALLDONTLIE
    and CFBD report historical games under each franchise's/program's *current* name, not the name
    actually in use at the time -- BALLDONTLIE's 2003 MLB season lists "Washington Nationals," not
    "Montreal Expos"; a 1980 NBA game lists "Oklahoma City Thunder," not "Seattle SuperSonics"; CFBD's
    2015 season lists "Louisiana," not the pre-2018 "Louisiana-Lafayette." So the sport-scoped Elo
    key (`_elo_key()`, `norm(name)` scoped by `COMP["sport"]`) never splits one program's real
    history across a relocation or rename the way it would if these providers used era-accurate
    names -- no alias table was needed to handle this.

  Request budget (see `backfill_history.py`'s own docstring for the full breakdown): soccer is
  cheap (~25 requests total across API-FOOTBALL and football-data.org, a few minutes); NCAAF/NCAAM
  are cheap (~26 and ~104 requests respectively, CFBD/CBBD's per-call limits being generous, a few
  minutes); NFL is moderate (~65 requests, ~15 minutes at BALLDONTLIE's existing 5 req/min pacing);
  NBA and MLB are the long pole (~340 and ~640 requests, ~75 and ~140 minutes respectively) because
  a 24-26-season backfill at 100 games/page is simply a lot of pages at that free-tier pace. A full
  run (every competition) is therefore a roughly 4-hour job, safely splittable across multiple
  sittings/days via `--comp` since `update_elo()` is already idempotent per match id and
  `ratings_elo.json` is written after every season, not batched to the end.

  Regression coverage: `BallDontLieAdapter.historical_season()` (pagination, retry-then-raise,
  preseason filtering) in `test_provider_adapters.py`; chronological-ordering, idempotency,
  provider-per-season assignment, and sport-scoped-Elo-keying tests in the new
  `test_backfill_history.py`. `python -m unittest test_model_inputs test_provider_adapters
  test_generate_posts` stays green.

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

- **2026-07-29:** Added a provider-neutral NFL availability intake contract.
  The code performs no scraping and assumes no permission from a provider.
  Each batch must declare an accepted authorization basis and source reference;
  ESPN-origin inputs, post-kickoff ingestion, and future-dated observations are
  rejected. Accepted records remain zero-weight research receipts in a local,
  gitignored, SHA-256-chained ledger. Enabling a provider still requires a
  separate terms/tier review and configured authorized access.

- **2026-07-29:** Added a provider-neutral market snapshot and benchmarking
  contract. It performs no scraping and enables no provider. Inputs must carry
  an accepted authorization basis and source reference and must be recorded
  before kickoff. Decimal prices are converted to implied probabilities and
  normalized to remove overround. Opening, lock-time, and closing labels are
  reconstructed only from captured timestamps; the earliest captured price is
  explicitly an opening proxy unless provider coverage began at market open.
  Generated ledgers and reports remain local and gitignored.

- **2026-07-29:** Expanded basketball research using only normalized team-game
  boxes supplied by an already authorized source. The code fetches no new
  provider and does not infer permission. Incomplete or implausible boxes are
  rejected, point-in-time rows require dates and home/away identity, and the
  resulting challenger/report stay local, gitignored, and zero-weight. A
  provider export must be reviewed against its active plan before use.

- **2026-07-29:** Added a College Football advanced-metrics challenger that
  consumes only local exports obtained through the configured CFBD tier. It
  performs no scraping and makes no new provider request. Complete paired
  advanced-game rows are joined to completed `/games` metadata; an entire
  season-week is sealed before it can enter later features. Annual `/talent`
  rows are used only when their declared availability week precedes the target
  week. Generated rows/reports are gitignored, research-only, and zero-weight.
  Historical use still requires a tier/terms review and reproducible authorized
  exports; a season-end aggregate must never be relabeled as a pregame snapshot.

- **2026-07-29:** Added an offline StatsBomb Open Data three-way soccer
  challenger using only the official `hudl/open-data` repository layout. It
  does not scrape StatsBomb/Hudl sites and cannot attach its selective research
  coverage to live fixtures. Regulation outcomes are reconstructed from event
  periods 1-2; extra time and shootouts are excluded from 1X2 grading. Match-
  date blocks are sealed before updates, missing event files/incomplete pairs
  are reported, prior starting-XI continuity never reads the target lineup,
  and generated artifacts remain gitignored with production weight zero.
  Anything published from these results must credit StatsBomb and use the
  required logo under the repository's current terms.

- **2026-07-29:** Closed the authorized-profile delivery gap. CI now builds a
  derived NFL team profile from official nflverse releases, keeps raw play-by-
  play only in the private Actions cache, and embeds matched derived fields in
  the existing public fixture JSON. NCAAF continues through the configured
  CFBD API tier. The expanded view displays source/license/season/coverage and
  an explicit zero-weight receipt. Historical-only StatsBomb and Retrosheet
  profiles remain `attach_live=false`; no selective dataset is represented as
  live coverage. This is reasoning transparency, not model promotion.

- **2026-07-29:** Reviewed Retrosheet's official current use notice and data-use
  pages before the MLB historical integration. Retrosheet permits reuse, including
  commercial products, when its specified copyright/attribution statement appears
  prominently. The builder consumes only official downloaded 2020–2025 event and
  game-log archives, records source hashes and the required notice in the frozen
  derived artifact, and performs no website scraping. Historical Retrosheet inputs
  are used only to fit and validate the run-strength challenger. Live reconstruction
  uses the already authorized BALLDONTLIE team games/runs totals; unavailable stats
  endpoints, target-game starters, lineups, and bullpen availability are not inferred.
  The historical gate passed, but the live challenger remains a prospective shadow
  with production weight zero.

- **2026-08-03:** Added a credential-gated SportsDataIO pregame overlay for
  NFL, NBA, MLB, NHL, NCAAF, and NCAAM. It uses the configured licensed API,
  never scrapes pages, caches only normalized derived fields, and fails to an
  explicit unavailable state when the active account does not include an
  endpoint. The overlay is also disabled by default; a configured key alone is
  insufficient, and activation requires explicit confirmation that the active
  agreement permits live public redistribution. MLB/NBA starting-lineup requests use the provider's projections
  product; NFL weekly injury reports use the stats product, while the other
  league APIs expose `InjuredPlayers` in projections. Soccer keeps
  the existing API-FOOTBALL/Sportmonks path because it already has native
  fixture identity and lineup/injury integration. Market consensus from the
  licensed Odds API is now passed through the existing authorized, pre-kickoff,
  hash-chained snapshot contract for later benchmark analysis. Personnel,
  workload, and venue additions remain prospective shadows with production
  weight zero; this change does not claim that an unverified provider tier or
  an unvalidated feature improves the production model.
