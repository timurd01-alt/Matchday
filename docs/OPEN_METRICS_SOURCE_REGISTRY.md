# Matchday open-metrics source registry

Reviewed: 2026-07-29

Status: research allowlist; every production integration still requires a fresh terms/tier check

Scope: sources that can improve Matchday without scraping access-controlled or contractually prohibited sites

This registry is an engineering control, not legal advice. "Publicly reachable" is not the
same thing as "licensed for automated reuse." A source is eligible only when the data owner
or provider gives an affirmative API, download, or open-data permission for Matchday's use.

## Decision labels

- **Approved:** already reviewed for Matchday's present use. Preserve attribution, plan limits,
  storage limits, and the restrictions in `PROVIDER_COMPLIANCE.md`.
- **Research candidate:** suitable for an isolated offline experiment after its exact license and
  Matchday's intended use are recorded. It is not automatically approved for live production.
- **Do not use:** no adequate permission, prohibited automation, unclear provenance, or a standing
  Matchday exclusion.

## Source allowlist and candidates

| Sport/use | Source | Status | What it can contribute | Conditions and caveats |
|---|---|---:|---|---|
| Cross-sport fixtures and results | Existing licensed Matchday providers | Approved | Point-in-time schedules, scores, standings, player summaries, injuries, lineups, and odds where the active plan provides them | Follow `PROVIDER_COMPLIANCE.md`; never expose keys or redistribute raw feeds |
| Consensus sportsbook benchmark | The Odds API | Approved | Opening and pregame no-vig probabilities, bookmaker count/disagreement, line movement | Benchmark or separately labeled hybrid input; do not present it as Matchday's independent model |
| Weather | Open-Meteo | Approved for current noncommercial use | Temperature, wind, precipitation, venue-time conditions | CC BY 4.0 attribution; free API is noncommercial and rate-limited; upgrade or disable before commercial use |
| NFL historical play-by-play and player summaries | nflverse-data, excluding every ESPN-origin release | Approved with attribution | EPA/play, success rate, CPOE, early-down tendency, explosive-play rate, pace, drive efficiency, red-zone performance | Main repository is CC BY 4.0; inspect each release because some datasets have different attribution/share-alike terms. Do not use `espn_data` or ESPN-sourced depth charts. Source: https://github.com/nflverse/nflverse-data |
| Soccer event-data research | StatsBomb Open Data | Research candidate | Event-level shots, possessions, pressure, lineups, and xG for the competitions/seasons actually published | Intended for research and genuine football-analytics interest; published analysis requires StatsBomb credit/logo and acceptance of its user agreement. Coverage is selective, so it is best for offline method research, not assumed live coverage. Source: https://github.com/statsbomb/open-data |
| MLB historical game/event research | Retrosheet downloads | Research candidate | Historical play-by-play, game context, outcome rates, and independent feature validation | Retrosheet permits broad use but requires its specified attribution statement to appear prominently when data or a derived product is transferred. Confirm the current notice at integration time. It is historical evidence, not a substitute for a licensed live feed. Source: https://www.retrosheet.org/game.htm |
| NHL advanced-stat research | MoneyPuck listed downloads only | Deferred — excluded from this expansion | Not integrated | Excluded at the owner's direction on 2026-07-29. Re-open only through a new explicit decision and fresh terms review. |
| College football | CollegeFootballData endpoints in the active tier | Approved within current tier | PPA, success rate, schedules, talent, recruiting, player stats, opponent context | A free key is for testing and limited usage; recurring/app-scale use may require a paid tier. Use only documented endpoints and exclude any field whose upstream origin conflicts with Matchday's rules. Source: https://collegefootballdata.com/ |
| College basketball | CollegeBasketballData endpoints in the active tier | Approved within current tier | Box-score and team/player inputs from which Matchday can derive tempo, efficiency, and four factors | Same tier and no-raw-redistribution controls as CFBD. Source: https://collegebasketballdata.com/ |
| NBA/MLB live inputs | BALLDONTLIE endpoints in the active tier | Approved within current tier | Game, team, and player inputs from which Matchday can derive its own ratings | Use the official API only; respect retention, quota, branding, and redistribution terms |
| Soccer live inputs | football-data.org, API-FOOTBALL, and/or Sportmonks within active plans | Approved within current tiers | Fixtures, tables, box-score events, lineups, and availability where supplied | Training features must be reproducible from the fields available at forecast time and from the serving provider |

## Explicit exclusions

- ESPN, ESPN FPI, ESPN QBR, and downstream datasets containing ESPN-originated fields.
- Sports Reference sites, WorldFootball.net, Flashscore, Sofascore, or another site whose terms
  prohibit the intended automated use.
- Polymarket scraping or direct automated extraction under the currently reviewed terms. A licensed
  sportsbook consensus is Matchday's present market benchmark.
- Kaggle, GitHub, or community datasets merely because the file is downloadable. The dataset must
  identify its upstream provenance and grant a compatible data license; a code license does not
  necessarily license the included data.
- Undocumented JSON endpoints, paywall/session workarounds, CAPTCHA bypasses, browser automation
  intended to evade blocking, or data obtained through another person's account.
- Proprietary named indexes copied from a publisher. Matchday may implement a public mathematical
  method from authorized raw inputs, but it must use its own name and document its formula.

## Candidate feature families

These are hypotheses to test, not assertions that a metric improves forecasts.

| Sport | First candidate families | Avoid treating as truth |
|---|---|---|
| Soccer | opponent-adjusted xG difference where licensed; non-penalty shot quality; shots in box; set-piece share; possession territory/field tilt; pressing proxy; keeper shot-stopping; lineup strength; rest/travel; home advantage; Poisson scoring rates | raw possession, last-five form, and H2H without opponent/sample adjustment |
| NFL | offensive/defensive EPA per play; early-down success; dropback EPA and CPOE; explosive-play rate; pressure/sack rate when available; red-zone and special-teams efficiency; pace; rest/travel; quarterback availability | total yards, final score margin, or turnover margin without regression and context |
| NCAAF | PPA/EPA-style efficiency; success rate; explosiveness; line-yards/havoc proxies; pace; opponent adjustment; returning/talent prior; home/travel/rest | polls, recruiting, or last season's record as if they were current performance |
| NBA/NCAAM | adjusted offensive and defensive efficiency; possessions/tempo; eFG%; turnover rate; offensive rebound rate; free-throw rate; three-point attempt profile; rest/back-to-back; player/lineup availability | points per game without pace and schedule adjustment |
| MLB | starting-pitcher and bullpen components; K-BB%; FIP-like defense-independent measures; platoon split; park/weather; bullpen workload; team baserunning/defense proxies; Pythagorean/BaseRuns-style strength | batting average, pitcher wins, saves, or tiny recent samples as primary signals |
| NHL | score/venue-adjusted xG share; flurry-adjusted xG; high-danger and rebound creation; GSAx; special teams; confirmed/probable goalie; back-to-back/rest/travel | raw shot count, save percentage, or recent shooting percentage without regression |

## Admission checklist for a new source

Before code is added, record:

1. Data owner and upstream provenance.
2. Exact terms/license URL, version or review date, and permitted purpose.
3. Whether public display, derived analytics, model training, betting-related analysis, retention,
   and commercial use are allowed.
4. Authentication, rate limits, caching/retention limits, attribution, and deletion obligations.
5. Available historical depth and whether the same field exists live before forecast lock.
6. Stable event/team/player identifiers and a deduplication strategy.
7. A kill switch and a missing-data fallback that does not silently invent a value.
8. Confirmation that no excluded upstream source is embedded in the selected release.
