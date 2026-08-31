# Matchday

A personal analytics hub for college football and men's college basketball.

Live at [matchdayterminal.com](https://matchdayterminal.com) · by
[@iamtimurety](https://x.com/iamtimurety)

## What this is

This is one person's analytical playground, published in the open. It exists so the
method and the record can be checked by anyone — not as a service, not as a tipster,
and not as advice. Everything on it is my own opinion and my own work.

It covers two sports and nothing else: **college football** and **men's college
basketball**. Coverage narrowed to those deliberately. They share a data source, a
season calendar that runs almost year-round between them, and a field of several
hundred programmes that is genuinely hard to price.

## Where the numbers come from

**Matchday does not compute ratings.** Every rating, ranking and model probability is
produced by the [Bet Better](https://github.com/timurd01-alt) engine and read here
through a JSON handoff (`betbetter_picks.json`, validated by `betbetter_handoff.py`).
This repository renders those numbers and never recalculates them.

- **Ratings** are an opponent-adjusted scoring margin — points per game better than an
  average team against an average opponent — solved from the engine's own stored
  results, with strength of schedule solved alongside and carried on every row.
- **Rankings** are an edition with a date on it, read as published rather than
  recomputed. A table that changed between two page loads would not be a poll.
- **SP+** is stored for conference membership only. It is CFBD's rating, not this
  model's, and never contributes to a ranking.
- **Match forecasts** are live shadow forecasts: they keep moving until kickoff, carry
  no pregame lock receipt, are not official picks, and are not graded.

`build_cfb_snapshot.py` is the only writer of the ranking blocks in
`matchday-cfb-snapshot.js`. Regenerate the handoff from the Bet Better repo:

```bash
python -m betbetter matchday export --out <matchday>/betbetter_picks.json
```

then rebuild the snapshot here:

```bash
python build_cfb_snapshot.py
```

## Rules this project holds itself to

- **Projections are labelled.** Brackets and poll editions say "projected" until real
  selection and championship results exist. A ranking published before a season starts
  describes the previous completed season, and says so in its own note.
- **Nothing is rewritten.** A settled score is never revised; a graded pick is never
  rescored. `archive/games/` is the raw record and refuses revisions.
- **Shadow forecasts never enter the official ledger.** `forecast_pause.py` governs
  publication, and a displayed live read can never later be graded as though it had
  been an official call.
- **Model-market disagreement is reported, not endorsed.** On graded college samples a
  wider gap predicted *worse* results — the sign is inverted — so nothing here ranks,
  filters or stakes on it.

## The board

Upcoming games · Results · Scorecard · Bracket · Rankings · Community.

The scorecard is deliberately two numbers, picks won and picks lost. Brier, log loss,
calibration and closing-line value are still computed by the research modules; they are
not on that page because a reader asking "is it any good" wants a record.

## Running it

```bash
python fetch_data.py      # refresh provider data
python app.py             # serve locally
python -m unittest discover -p "test_*.py"
```

Provider keys live in `config_keys.py`, which is gitignored. See `SETUP.md`.

## Notes

`AGENTS.md` documents the repository's working rules. `PROVIDER_COMPLIANCE.md` records
data licensing decisions. `legal.html` carries the privacy policy, terms and data-source
credits.
