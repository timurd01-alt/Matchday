# Matchday

Sports-prediction analytics site (Elo/SRS-derived picks, probabilities, bracketology) covering
soccer, NFL, NBA, MLB, NHL, and college football/basketball. Flask backend (`app.py`,
`server/server_app.py`), static JS/HTML/CSS frontend, provider data cached to JSON.

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

## Tests

Run before considering prediction/data/provider changes complete:

```bash
python -m unittest test_model_inputs test_provider_adapters test_generate_posts
```

- `test_model_inputs.py` — prediction/model input construction
- `test_provider_adapters.py` — provider normalization and adapters
- `test_generate_posts.py` — social post generation

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
