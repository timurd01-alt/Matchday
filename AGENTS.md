# Matchday

Sports-prediction analytics site (Elo/SRS-derived picks, probabilities, bracketology) covering
soccer, NFL, NBA, MLB, NHL, and college football/basketball. Flask backend (`app.py`,
`server/server_app.py`), static JS/HTML/CSS frontend, provider data cached to JSON.

## Production delivery

When the owner asks to push, ship, deploy, or finish a change, completion means
the verified work is merged into `main`, pushed to `origin/main`, and the
production deployment is checked. Pushing only a feature branch is not delivery.
Before merging, update from the current remote `main` and preserve its bot-owned
generated data. Never force-push production.

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

## Generated data files are bot-owned

`ratings*.json` and `picks_log*.json` are committed back to `main` by the hourly
workflow (10 of any 30 recent commits are `Update ratings and picks ledger`).
Do not commit them from a feature branch — the branch goes stale within the hour
and conflicts on a large generated JSON. Change the *code* that produces them
and let the scheduled run regenerate the data. If a branch already carries such
a change, resolve in favour of `main`'s copy.

## Hashed artifacts are byte-sensitive

Three places hash a checked-in file's raw bytes and freeze the digest into
governance: the MLB challenger artifact (`mlb_challenger_store.py`), the CFB
challenger (`build_cfb_challenger.py`), and every manual-review evidence file a
release review binds to (`mlb_recovery.py`). A hash over bytes is only stable
if the bytes are, so `.gitattributes` pins `eol=lf` repository-wide (`.bat`
keeps CRLF for `cmd.exe`).

This is not theoretical. `mlb_model_promotion.json` froze `f110758c...`, the
CRLF rendering of the challenger produced by a Windows checkout under
`core.autocrlf=true`, while CI checked the file out with LF and every shadow
lock recorded `f0177891...`. Same model, two digests, and
`exact_cohort_required` could never be satisfied — the gate spent weeks
collecting prospective evidence it would have had to discard. Corrected
2026-08-19 to the digest the evidence was recorded against, preserving it.

Never "fix" such a mismatch by writing your local digest into a policy. Check
whether the file is the same content rendered differently first;
`test_mlb_model_promotion.py` now asserts the policy digest against the
artifact on disk on every run.

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

## Self-development loops

Five loops keep the site improving. They are deliberately separate: the loop
that can write model code must never be the loop that decides a model ships.

Every loop obeys the same rule: **report findings, never opinions.** A loop
that fires without something concrete to point at makes the agent downstream
invent work to justify the trigger. Each one below must be able to say
nothing, and each has a test proving the silent case is reachable.

**Loop A -- `check_promotion_readiness.py`** (hourly, in `deploy.yml`). Compares
each frozen promotion policy against the prospective scorecard built from the
ledgers this run, and writes `promotion_readiness.json`. Read-only: it never
edits a policy and its most positive verdict is `ready_for_manual_review`. The
scorecards' own `status` only checks sample-size minimums; the extra conditions
a policy states (exact cohort identity, paired interval, Brier improvement) are
checked here. Four states matter -- `collecting` (wait), `evidence_against`
(record a rejection), `blocked` (evidence is unusable, decide now), and
`ready_for_manual_review`.

Add a gate by appending to `GATES`, naming the policy, the scorecard, and which
pair of models the policy is about. That last part cannot be inferred: MLB's
policy governs the capped blend, not the raw challenger.

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

**Loop C -- `data_coverage.py`** (hourly). Measures the gap between the inputs
the models wanted and the data that arrived, writing `data_coverage_report.json`
in four kinds: `missing_input` (absent on fixtures inside the 72h horizon),
`stale_feed` (payload past its freshness budget while still publishing),
`unsourced_family` (empty on every fixture everywhere -- a sourcing decision,
not a repair), and `thin_evidence` (picks published with too little graded
history to judge). Read-only.

Off-season is never a gap: a competition with no imminent fixtures is skipped
for input and freshness entirely, or NBA and NHL would be reported every hour
for half the year. A family reported as globally unsourced is suppressed from
the per-competition signal, so one absence is never reported twice.

**Loop D -- `next_task.py`** (hourly). Ranks live signals from Loop A's report,
Loops B and C's reports, `fetch_failure_*.json`, `provider_quota_state.json`,
`market_benchmark_report.json`, and `docs/experiments.json`, then emits **one**
scoped task prompt plus the guardrails. A quiet repository produces an explicit
"no action needed, do not invent work". Adjust priorities in `PRIORITY`.

The ranking encodes a judgement worth keeping: a broken data pipeline outranks
an interface blocker, which outranks research questions, which outrank
decisions about what to build next. Anything actively degrading what the site
publishes comes before anything that merely could be better.

**Loop E -- the scheduled agent.** Consumes Loop D's prompt, works on a branch,
opens a PR. CI is the verifier; a human merges. It may *propose* a policy status
change with evidence attached, never apply one, and never touch a
`requirements` block, a quota reserve, or the bot-owned generated data.

## Beating the market: CLV and pre-registration

Matchday's stated goal is to beat the closing line as a forecasting claim, not
to bet. Two rules follow from that.

**Overall hit rate is not evidence about the model.** When Matchday names the
market's favourite it inherits the market's record, so a headline hit rate says
almost nothing. `independent_value.py` splits the committed pick logs on
agreement with the market and scores the two sides separately. It is
descriptive -- the pick logs are the published record, which the scorecard's
self-heal pass may correct -- and `market_benchmark_report.json` is the
tamper-evident authority once it has data. Each metric uses every row that can
support it: the agreement split needs only the market's pick, the paired
scoring comparison needs its probabilities, and they report separate n.

**Measure CLV, not win rate.** `clv_report.py` reports closing-minus-lock
probability movement toward Matchday's pick, per competition, with a game-date
block bootstrap. Match outcomes are too noisy to settle the question in a
reasonable sample; line movement answers in hundreds of fixtures rather than
thousands. A segment is given no verdict unless its median lock lead clears
`MIN_LEAD_MINUTES` -- a pick locked at the bell has nothing to be right early
about. The report is descriptive and feeds no forecast.

**`market_snapshot_ledger.jsonl` is irreplaceable.** Ratings recompute, picks
regenerate, forecasts re-derive. A closing price cannot be recovered after the
kickoff it belonged to. It is git-tracked and committed back hourly for that
reason; never move it back behind `.gitignore`.

**Pre-register before the season, not after.** `preregistration.py` seals a
declaration's immutable terms -- competition, season, hypothesis, metrics,
minimum sample, lock lead floor, decision rule -- into `terms_sha256`. Editing
any of them afterwards makes the declaration report `void`, and `--seal`
refuses to re-hash an edited file rather than laundering the change. CI runs
`--check`, so moving the goalposts breaks the build. `ncaam_preregistration.json`
is the live declaration for the 2026-27 season; its model artifact must be
frozen before `artifact_freeze_deadline` or the declaration is void.

To register a new target, write the declaration, run `--seal` once, and record
it in `docs/experiments.json`. Never amend a sealed declaration: open a new one.

**NCAAM build path.** `ncaam_advanced_metrics.py` connects CBBD team box scores
to `advanced_metrics.basketball_team_profiles`. It fails closed: `refresh()`
raises while `MAPPING_VERIFIED` is False, because a mis-named provider field
does not error -- `basketball_game_records` silently drops the row, yielding an
empty profile set and a cheerful "no data". To enable it, run
`--verify` against one real CBBD response, correct `TEAM_BOX_FIELDS` if the
names differ, and set the flag in a commit showing that evidence.

## Tests

Run before considering prediction/data/provider changes complete:

```bash
python -m unittest test_model_inputs test_provider_adapters test_generate_posts test_provider_quota
```

- `test_model_inputs.py` — prediction/model input construction
- `test_provider_adapters.py` — provider normalization and adapters
- `test_generate_posts.py` — social post generation
- `test_provider_quota.py` — persisted quota pacing, reset probes, and provider wiring

## Compliance

`PROVIDER_COMPLIANCE.md` is the live checklist of provider terms, licensing, and attribution
requirements (ESPN is fully excluded — not just link-out-only). Re-check it, and update its
review date, before any change to provider sourcing, data display, or redistribution. See also
`SECURITY.md` and `ROTATE_KEYS.md`.

## Local run

```bash
python -m http.server 8743
```

(matches `.claude/launch.json`'s `matchday-local` config)

## Local environment: two things that fail quietly

**Python 3.12 is required, not preferred.** `fetch_data.py` uses nested same-
quote f-strings, which are a syntax error before 3.12. On 3.11 the failure is
an *import* error inside the test run, so `test_model_inputs`,
`test_provider_adapters` and `test_generate_posts` -- three of the four the
guardrails call required before opening a PR -- do not fail, they never
execute. A run can look like it passed while having verified none of them.
CI pins 3.12 in `deploy.yml`; match it locally.

**On Windows, `pip install tzdata`.** `provider_adapters._iso_utc` resolves
`ZoneInfo("America/New_York")`. Linux ships a system tz database and CI is
fine; Windows has none, so zoneinfo raises `ZoneInfoNotFoundError` and two
provider tests error for a reason unrelated to the code under test.

With both in place the full CI suite runs locally: 557 tests, 4 skipped.
