# Authorized manual personnel pilot

Matchday does not have a legally cleared universal free feed for injuries,
starters, lineups, rotations, or bullpen availability. Public visibility is
not permission for automated collection or redistribution. This pilot is the
pragmatic fallback: manually record a small number of pregame observations
only after the exact source permits the intended use.

## Current scope

The implemented intake is NFL-only (`ingest_nfl_availability.py` and
`nfl_availability.py`). It is append-only, SHA-256 chained, timestamped before
kickoff, rejects ESPN-origin records, and always produces a research receipt
with `production_weight: 0`. MLB, NBA, and soccer remain blocked until an
equivalent source-specific review and sport-native schema exist.

## Source admission

Before entering an observation, save all of the following in the batch:

1. Publisher/data owner and direct source URL or contract reference.
2. Authorization basis: `licensed`, `open_license`, `first_party`, or
   `user_supplied_with_permission`.
3. Terms/license review date and permission for automated or manual capture,
   derived analytics, retention, and public display.
4. The source's publication/observation time and Matchday's capture time.
5. Stable fixture, team, and player identity.

Do not use ESPN, Sports Reference, Flashscore, Sofascore, WorldFootball.net,
paywalled/session-only pages, undocumented JSON endpoints, or a dataset whose
upstream provenance is unclear. Noncommercial status does not waive those
terms.

## Ingest a reviewed NFL batch

Copy `docs/examples/nfl_availability_batch.example.json`, replace every
placeholder with a real reviewed observation, and run:

```powershell
python ingest_nfl_availability.py --input reviewed-batch.json
```

The command refuses missing provenance, unsupported authorization bases,
future-dated observations, and records captured at or after kickoff. The
ledger is private and gitignored. A record being accepted does not change a
forecast; training and promotion require enough frozen prospective history.
