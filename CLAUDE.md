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
