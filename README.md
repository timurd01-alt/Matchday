# Matchday

A personal analytics hub for college football and men's college basketball.

Live at [matchdayterminal.com](https://matchdayterminal.com) · by
[@timurknowsball](https://x.com/timurknowsball)

## What this is

This is one person's analytical playground, published in the open. It exists so the
method and the record can be checked by anyone — not as a service, not as a tipster,
and not as advice. Everything on it is my own opinion and my own work.

It covers two sports and nothing else: **college football** and **men's college
basketball**. Coverage narrowed to those deliberately. They share a data source, a
season calendar that runs almost year-round between them, and a field of several
hundred programmes that is genuinely hard to price.

## Where the numbers come from

**Matchday does not compute ratings.** The power rating, the model probabilities and
the rest of the modelling come from a separate, private engine. This repository reads
its published output and renders it; it never recalculates a number.

- **The power rating** is an edition with a date on it, shown as published rather than
  recomputed, with strength of schedule beside every rating.
- **My Top 25** is my own ballot, ranked on each team's résumé. It is an opinion, kept
  apart from the power rating.
- **Match forecasts** are live shadow forecasts: they keep moving until kickoff, carry
  no pregame lock receipt, are not official picks, and are not graded.

After new engine output lands, rebuild the site's snapshot:

```bash
python build_cfb_snapshot.py
```

## Rules this project holds itself to

- **Projections are labelled.** Brackets and power rating editions say "projected" until
  real selection and championship results exist. A power rating published before a season starts
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

Upcoming games · Results · Scorecard · Bracket · Conferences (power rating and My Top 25) · Community.

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
