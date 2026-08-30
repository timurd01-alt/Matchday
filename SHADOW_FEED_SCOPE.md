# Bet Better shadow feed — ingestion scope

Draft, 2026-08-30. Not yet committed; see "Where this lands" at the end.

## Purpose

Accumulate the graded sample that `forecast_pause.RESTORE_CRITERIA` demands,
without publishing an unpromoted forecast as a pick. Today the pause has no
exit work in flight: nothing is collecting the evidence that would end it.

The goal is **not** to restore picks. It is to make the pause end on evidence
instead of on patience.

## Starting position

Bet Better appears in this repository seven times, all of it prose
(`forecast_pause.py`, `fetch_data.py:4850`, `MLB_RECOVERY.md`). There is no
adapter, no credential, no event-catalogue mapping. This is a build, not a
flag.

What already exists and should be reused rather than rewritten:

| Need | Existing code | Fit |
|---|---|---|
| Private pre-kickoff lock, append-only, hash-chained | `mlb_shadow_ledger.py` | Exact pattern, one sport |
| Grade forecasts against timestamped no-vig closing market | `market_benchmark.py` | Ready; needs a ledger pointed at it |
| Block-bootstrap interval, minimum-sample discipline | `market_benchmark.py` (`MIN_PAIRED_FIXTURES=100`, `MIN_TIME_BLOCKS=5`) | Ready |
| Labelled non-pick research surface | `mfti_research.py`, `research_posts.json` | Precedent for tone and framing |

## Work items

### 1. Fixture identity bridge — the hard part, do it first

Bet Better describes a fixture under its own ids and its own team naming.
Matchday's fixtures come from a different provider per competition. Joining
them wrongly is the failure mode AGENTS.md already documents: before
`resolve_overlaps()` existed, NFL collected **1,709 rows for 1,424 real games**
because nflverse's `2021_01_ARI_TEN` and BallDontLie's `bdl-nfl-423945` could
not be told to be one game.

This join is a *forecast* join, not a game join, so the archive's
one-provider-per-(competition, season) rule does not transfer. Proposed rule:

- Join on `(competition, kickoff_date, home, away)` through an explicit,
  reviewed name map — never fuzzy matching.
- An ambiguous or unmatched event is **dropped and logged**, never guessed.
  A shadow forecast that cannot be tied to a Matchday fixture is worthless
  anyway, so failing closed costs nothing.
- Log unmatched rates per competition. A high rate is the signal the name map
  is stale, and it should be visible rather than silently shrinking the sample.

### 2. Generalise the shadow ledger

`mlb_shadow_ledger.py` is the right design already: `LOCK_EVENT`/`GRADE_EVENT`,
`PROTOCOL_VERSION`, a 2-hour lock window, sha256 digests over canonical JSON.
Generalise to a competition-keyed `shadow_ledger.py`; keep MLB's existing file
readable so its 121 rows are not orphaned.

**Hard boundary:** shadow locks must never reach `forecast_ledger_*.jsonl` or
`picks_log_*.json`. `fetch_data._lock_decision()` deliberately returns
`wait / official_forecasts_paused` during the pause so that "a paused pick that
was never shown must not later be graded as though it had been." A shadow feed
that wrote into the official ledger would defeat exactly that.

### 3. Grade against the closing market

Point `market_benchmark.py` at the shadow ledger. This produces the only number
that matters for the pause: paired performance versus the closing no-vig
consensus, with a block-bootstrap interval.

Current standing evidence, from `forecast_pause.PAUSE_EVIDENCE`:

- 4,194 forecasts in shadow status, 0 ever promoted
- 86 graded games — model Brier **0.1907** vs market **0.1809**

So the model is behind the market on the only sample that exists, and that
sample is too small to conclude anything in either direction. The feed's job is
to grow it under lock discipline until the interval actually says something.

### 4. Display surface — labelled, and nowhere near a match card

Shadow output goes in a research view: no confidence figure, no edge, no "our
pick", no percentage rendered in the pick slot. It is labelled as a shadow
model that has not cleared promotion and is currently trailing the market.

This is the whole difference between the good version of this idea and the bad
one. On a card in the pick slot, it is the pause with a side door.

## What this does not do

- **Does not cover MLB, NBA or NHL.** The engine holds no events for them.
- **Does not help NCAAM.** 52 events is not a feed.
- **Does not restore publication.** `PAUSE_ACTIVE` stays `True` throughout.

## Open decision, and it has a date on it

Does Bet Better output ever become **NCAAM's** model for the pre-registered
2026-27 claim? If yes, `ncaam_preregistration.json` requires its artifact
built, hashed and frozen — `cohort.model_version`, `artifact_sha256`,
`feature_schema_version`, `transformation_version` — before
**2026-11-01**, or the declaration is void and no claim may be made from the
season's evidence.

If no, NCAAM stays on the CBBD adjusted-efficiency path and this feed is NCAAF
and soccer only.

That question should be answered before any code is written, because it decides
whether this feed is research infrastructure or the critical path to a
registered claim.

## Where this lands

Not on `pause-forecasts-betbetter` — that branch is a different unit of work and
is being actively committed to. New branch off `main`, and this file at repo
root alongside `MLB_RECOVERY.md` and `MFTI_RESEARCH_PROTOCOL.md`.
