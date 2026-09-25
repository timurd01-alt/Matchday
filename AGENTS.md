# Matchday

Sports-prediction analytics site covering college football and men's college
basketball only. **Every pick, probability, power rating and scorecard comes from
the Bet Better engine** through `betbetter_picks.json` (see below); Matchday
itself no longer forecasts. Soccer, NFL, NBA, MLB and NHL were removed
entirely on 2026-09-13; do not reintroduce them. Static JS/HTML/CSS
frontend on GitHub Pages, a small Vercel API (`api/`) for community picks, and
provider data cached to JSON by the hourly workflow.

## Production delivery

Every requested repository change is a production-delivery request unless the
owner explicitly says not to publish it. Completion means the verified work is
merged into `main`, pushed to `origin/main`, and the production deployment is
checked. Do not stop after editing, testing, committing, or pushing only a
feature branch.
Before merging, update from the current remote `main` and preserve its bot-owned
generated files. Never force-push production.

## Picks come from Bet Better, and only from Bet Better

Matchday's own in-house model (`predict()`, Elo/H2H ratings, the pick lock,
`picks_log_*.json`, the forecast ledgers, the old scorecard, recaps, promotion
gates, challengers, the NCAAM pre-registration and the X bot) was removed on
2026-09-25. Bet Better never read any of it. Do not reintroduce a second
forecast: the site previously showed two prediction systems that disagreed on
the same fixture.

The pipeline is one-way. The Bet Better engine writes `betbetter_picks.json`;
`betbetter_handoff.py` validates it and attaches each pick to its fixture as
`match["betbetter_pick"]`; `build_cfb_snapshot.py` builds the picks, scorecard,
ratings and results the browser shows (`matchday-cfb-snapshot.js`).
`fetch_data.py` still owns everything that is not a forecast: fixtures, scores,
market odds, weather, injuries, news, standings and the game archive.

## Departments

Specialist subagents are organized into de facto departments. Each agent's file
(`.claude/agents/<name>.md`) is authoritative for its exact scope — this table is a map, not a
replacement.

| Department | Agents | Owns |
|---|---|---|
| Data & Prediction Engine | `data`, `predictions`, `prediction-auditor`, `sports-rules` | Provider pipeline integrity → model logic & grading → independent audit → competition-format rules. `predictions` builds/grades; `prediction-auditor` checks it independently; `sports-rules` is the neutral rulebook both defer to. |
| Experience | `ui`, `accessibility`, `content` | Layout/interaction, inclusive access, editorial copy & SEO content. |
| Engineering & Ops | `development`, `devops`, `security`, `qa` | Implementation, deployment/reliability, defensive review, release verification. |
| Growth & Distribution | `seo-growth`, `social-media`, `analytics` | Discoverability, X/social publishing, measurement & reporting. |
| Trust & Legal | `compliance` | Provider terms, licensing, attribution, betting/legal disclosures. |
| Coordination | `product` | Resolves ownership overlaps between the above; turns goals into scoped requirements. |

**Handoff convention:** when a task crosses department boundaries or ownership is unclear,
route it to `product` rather than guessing. Domain agents report evidence and conclusions; they
don't edit files unless the parent (you, or the coordinating agent) explicitly assigns
implementation work.

## Release notes and the build label

Every pushed site change needs a release-note entry. Add a **new file**
`updates/<build>.json` — never edit an existing one — then regenerate:

```bash
python build_updates.py
```

```json
{"rank": 115, "date": "Build 0731A", "tag": "Fix", "title": "…", "items": ["…"]}
```

`rank` orders the list (highest = newest); use the previous highest plus one.
The displayed build label in the top strip and on the Updates page is **derived
from the newest entry** — do not hardcode a build string anywhere.

`updates.js` is generated and committed only so a plain static file server works
locally. Never hand-edit it, and never resolve a conflict in it by hand —
regenerate instead. `test_release_notes.py` fails if it drifts out of sync.

This layout exists because a single shared `SYSTEM_UPDATES` array literal made
**every** pull request conflict with every other one: each change prepended to
the same lines. One file per build removes the shared line entirely.

## Generated files are bot-owned

`market_snapshot_ledger.jsonl`, `posts.json` and the rendered `posts/*.html`
are committed back to `main` by the hourly workflow. Do not hand-edit them on a
feature branch; change the code that writes them. If a branch already carries
such a change, resolve in favour of `main`'s copy.

## The game archive is the raw record; everything else is derived

`archive/games/<comp>/<season>.csv` is Matchday's own copy of every finished
game it has seen. It exists because nothing else here keeps one: `data_*.json`,
every `*_cache.json` and the nflverse play-by-play are all gitignored, and a
dark provider otherwise meant a dark sport (CFBD for three weeks).

Two tables, because a final score cannot produce an adjusted-efficiency rating:
`archive/games/` always, and `archive/box/` for team box detail wherever a
source provides it — possessions (`FGA - ORB + TO + 0.475*FTA`) are what tempo
and efficiency need. **`archive/box/` is currently empty**: no free source on
hand carries basketball box detail, and CBBD's box endpoint is quota-limited
with `MAPPING_VERIFIED = False`. Finding a free one is the open task.

Two writers, deliberately separate:

- **Forward, hourly.** `game_archive.record_build()` is called from
  `fetch_data.build()` just before `data_<comp>.json` is overwritten. It costs
  **zero provider calls** — it captures games the fetch already had and was
  about to discard — and it swallows its own errors, because the archive must
  never be able to fail a deploy.
- **Backward, occasional.** `archive_backfill.py` seeds history from sources
  that cost no quota: the openfootball CC0 history, the BallDontLie/CFBD/CBBD
  caches already on disk, and nflverse. Safe to re-run at any time; it seeded
  35,460 games across 11 competitions.

Two rules the archive enforces, both learned the hard way:

- **A settled score is never rewritten.** A revision is refused and logged to
  `archive/conflicts.jsonl` with the original left standing, so a provider
  cannot retroactively rewrite a published result.
- **One provider per (competition, season).** Two sources describe the same
  game with different ids and different team naming — nflverse's
  `2021_01_ARI_TEN` between "TEN" and "ARI" versus BallDontLie's
  `bdl-nfl-423945` between full club names — so nothing downstream can tell
  they are one game. Before `resolve_overlaps()` existed, NFL collected 1,709
  rows for 1,424 real games. Resolution keys on the *provider*, not the source
  label: `"BALLDONTLIE"` and `"balldontlie"` are one id scheme, and treating
  them as rivals once discarded 1,698 MLB games in favour of 113. Live pipeline
  sources outrank bulk ones, because `record_build()` keeps collecting those
  competitions under *their* ids — seeding a season from a bulk source instead
  would make the hourly hook re-add every game under a second id forever.

These partitions are append-mostly and sorted by date, so a feature branch
touching them does not conflict the way a regenerated blob does. Validate with `python game_archive.py validate` before committing.

## Line endings are pinned

`.gitattributes` pins `eol=lf` repository-wide (`.bat` keeps CRLF for
`cmd.exe`), so a Windows checkout and CI see the same bytes.

## Provider quota is enforced, not assumed

Confirmed live 2026-07-31: CFBD, CBBD, and The Odds API were all sitting at zero
remaining calls for their current billing period, with no code anywhere aware
of it — predictions and market data just quietly degraded to "no data" across
the live site. `provider_quota.py` reads the real rate-limit header(s) every
provider already returns on every response and persists them to
`provider_quota_state.json` (gitignored, CI-cached the same way as
`.ci_fetch_state.json` — see `deploy.yml`'s "Restore fetch state" step). A call
is refused **before** it fires once a provider's tracked remaining budget hits
its safety reserve, instead of firing blind and finding out via a 429.

**This is automatic for CFBD, CBBD, BallDontLie, and API-Football** — any
code that builds `CollegeFootballDataAdapter`, `CollegeBasketballDataAdapter`,
`BallDontLieAdapter`, or `APISportsAdapter` (via `provider_adapters.py`, which
every fetch/backfill/refresh script already does) is covered with zero extra
work, because the enforcement lives in each adapter's default HTTP getter, not
in each call site. football-data.org and The Odds API route through
`fetch_data.py`'s own separate `_get()` and are tagged per call site with
`provider="football_data"` / `provider="odds_api"`.

**Adding a new provider or a new call site**: pass `provider="<key>"` to
`_get_json`/`_get_csv_text` (or `fetch_data._get`) and add a `PROVIDER_SPECS`
entry in `provider_quota.py` describing its real header names — read them off
a live response first (`curl -i` or a one-off script), never assume a number.
CFBD's configured free tier is paced against its verified 1,000-call monthly
ceiling in addition to the response's real remaining count. CBBD still uses
reserve-only enforcement because no verified ceiling is configured. CFBD and
The Odds API fail closed if the private quota ledger is missing; only an
explicit `quota_bootstrap` workflow dispatch may seed a cold ledger. When a
stored CFBD or Odds balance would block a call, their documented zero-cost
status endpoints (`/info` and `/v4/sports`) may reconcile the real balance at
most once per six hours; never use a paid data endpoint as a quota probe.

## Quota is a budget, not just a floor

The reserve in `PROVIDER_SPECS` stops a provider reaching zero. It does not
ration the period, which is why cfbd spent its entire 1,000-call month by
2026-08-10 and went dark for three weeks with the reserve working exactly as
designed. Two pieces address that, and they were built in that order on
purpose.

**Accounting (`entry["spent"]`, `entry["by_endpoint"]`).** The ledger used to
record only what a provider *said was left*, never what Matchday *spent or on
what*, so every cache TTL in this codebase was a guess nobody could check and
an exhausted budget could not be traced to the call that drained it. Pass
`url=` to `record_response()` and the spend is attributed;
`provider_quota.usage_report()` returns per-period totals and the top
endpoints, and `next_task.py` attaches them to any quota task so it names the
call that spent the budget instead of asking someone to guess at a TTL.

**Budget (`quota_budget.json`).** A daily allowance derived from budget
remaining over days remaining, with four call tiers: 1 is a fixture inside its
lock window (a pick about to be frozen permanently), 4 is slow-moving
background data. Each tier may use a stated multiple of the day's allowance,
so pressure closes tiers from the bottom up and a lock-window call is the last
thing to be refused. Pass `tier=` to `check()`; omitted, it takes the policy
default.

**It ships advisory (`"enforce": false`).** The allowances are derived from a
ceiling and a calendar, not from measured behaviour -- enforcing them before a
period of accounting exists would ration real calls against a guess, which is
the mistake the fixed TTLs already make. While advisory, every refusal it
*would* have made is counted in `budget_would_decline`. Flip `enforce` once
`usage_report()` shows where the budget actually goes, not before.

Never relax an allowance or a reserve to make calls succeed. If the budget is
mis-shaped rather than overspent, propose the change with the spend data
attached.

## Self-development loops

Three loops keep the site improving. Every loop obeys the same rule: **report
findings, never opinions.** A loop that fires without something concrete to
point at makes the agent downstream invent work to justify the trigger. Each
one must be able to say nothing, and each has a test proving the silent case is
reachable.

**Loop B -- `ui_audit.py`** (hourly). Audits the shipped HTML/CSS against
published interface requirements -- WCAG 2.2 AA contrast, focus visibility,
tap-target size, heading order, `lang`, pinch-zoom, reduced motion -- plus the
CLS and render-blocking budgets stated in the module. Writes
`ui_audit_report.json`. Every finding names a file, a line and a rule.

It reports **violations only, never taste**. "Does this look modern?" is not a
checkable question and a loop that asks it hourly answers it hourly; judging
the design is the job of whoever picks the task up, arriving with evidence.
Two false-positive classes are already fixed and regression-tested: a
translucent background is unresolvable (not flattened to opaque), and a tap
target is the selector's *subject* (not any interactive ancestor). When adding
a rule, add its silent case too.

**Loop D -- `next_task.py`** (hourly). Ranks live signals from
`fetch_failure_*.json`, `provider_quota_state.json` and Loop B's report, then
emits **one** scoped task prompt plus the guardrails. A quiet repository
produces an explicit "no action needed, do not invent work". Adjust priorities
in `PRIORITY`. A broken data pipeline outranks a quota warning, which outranks
an interface defect.

**Loop E -- the scheduled agent.** Consumes Loop D's prompt, works on a branch,
opens a PR. CI is the verifier; a human merges. It never touches a quota
reserve or the bot-owned generated files.

(Loops A and C graded and fed the retired in-house model and were removed with
it; the letters are kept so older references still line up.)

## The market price ledger

**`market_snapshot_ledger.jsonl` is irreplaceable.** It holds bookmaker prices,
not picks. A closing price cannot be recovered after the kickoff it belonged
to, so it is git-tracked and committed back hourly; never move it back behind
`.gitignore`. It is the evidence any future closing-line comparison of Bet
Better's picks would need.

## Tests

Run before considering prediction/data/provider changes complete:

```bash
python -m unittest discover -p "test_*.py"
```

This is the exact command `deploy.yml` runs, and `test_next_task` asserts the two
stay identical — so what you run locally is what your PR is judged by. Don't
narrow it to a named subset: this section previously listed four suites while CI
ran thirty, and the thirty themselves left 26 modules on disk gating nothing.

The suites most worth knowing by name when something fails:

- `test_betbetter_handoff.py` — the Bet Better handoff: validation and attachment
- `test_cfb_snapshot.py` — the snapshot the browser shows picks, ratings and results from
- `test_provider_adapters.py` — provider normalization and adapters
- `test_generate_posts.py` — post pages and the sitemap
- `test_provider_quota.py` — persisted quota pacing, reset probes, and provider wiring

## Compliance

`PROVIDER_COMPLIANCE.md` is the live checklist of provider terms, licensing, and attribution
requirements (ESPN supplies public facts only — final scores, AP Top 25 rank/team, news headlines — never its statistics or content). Re-check it, and update its
review date, before any change to provider sourcing, data display, or redistribution. See also
`SECURITY.md` and `ROTATE_KEYS.md`.

## Local run

```bash
python -m http.server 8743
```

(matches `.claude/launch.json`'s `matchday-local` config)
