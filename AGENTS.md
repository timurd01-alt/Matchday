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
explicit `quota_bootstrap` workflow dispatch may seed a cold ledger.

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
