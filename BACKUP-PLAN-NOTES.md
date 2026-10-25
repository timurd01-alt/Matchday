# Backup plan notes

## What this backup protects

Preserve the engine: formulas/source code, configuration, dependency lockfiles,
feature definitions, fitted weights and calibration, saved team-rating state,
manual ballots, and learned RAPM parameter files. These are the parts that must
survive a new computer or a damaged/deleted fixture database.

The routine backup excludes fixture tables, raw provider responses, game/play
history, odds snapshots, and large public CSV datasets. Public inputs are
recollected when needed. Existing live databases are not pruned or deleted.
Git bundles include existing committed history, which can contain older public
data already tracked in Git; no full local database is added to them.

## Make and check the small backup

From either repository, use Python 3.12:

```powershell
python scripts/backup_engine.py create --destination "PRIVATE-BACKUP-FOLDER"
```

This saves both repositories and reads only selected model-state tables from
the databases. The main database defaults to `C:/SigmaLabData/sigmalab.sqlite3`;
pass `--main-db PATH` if its setting changes. It does not call providers.

Keep the resulting dated `engine-recovery-*` folder together. Its manifest must
say `PASS_ENGINE_ARCHIVES_AND_MODEL_STATE_ROUND_TRIP`. Archive CRCs, file SHA-256
values, and source-versus-export row/value hashes are checked. Credential files
(`.env`, `config_keys.py`) and local agent settings are excluded by default.
Restore provider keys separately from secure credential storage. Keep model
state private and never commit its database to a public repository. Earlier
local full-recovery ZIPs may include credentials; do not upload those copies.

Make a new engine backup after changing formulas, fitting new weights, changing
calibration/settings, or adding a manual ballot. Keep at least one verified copy
outside this SSD. No recurring schedule or automatic deletion is installed.
The earlier full-database backup tools are optional, not the routine plan.

## If the fixture database is damaged or deleted

1. Stop Sigma Lab, its collector and any scheduled poll/refresh tasks. Stop
   Matchday's automated shipping/refresh jobs. Do not keep writing to a damaged
   database. If the file still exists, preserve it and any WAL/SHM files together
   under a different name/location for diagnosis. Do not overwrite that copy.
2. Restore the saved engine ZIPs. Their top-level folders are `matchday` and
   `Sigma Lab`; recover those project directories and use the saved lockfiles.
   Git bundles retain committed history; the ZIPs retain the working code and
   configuration at backup time. Reinstall dependencies according to each
   project's README. Check `.env` paths and provider-key availability.
3. From the engine recovery package, seed a NEW database with saved math:

   ```powershell
   python backup_engine.py restore --state "state/sigma-main.sqlite3" --output "C:/SigmaLabData/recovered.sqlite3"
   ```

   The tool refuses an existing destination and checks the package checksum and
   restored model-state integrity. Point `SIGMALAB_DB` in Sigma Lab's `.env` at
   `C:/SigmaLabData/recovered.sqlite3`. Keep the package's `learned-rapm` JSON
   files at `C:/SigmaLabData/sdv/`; those are saved learned effects, not raw games.
4. In the Sigma Lab project directory run:

   ```powershell
   python -m sigmalab doctor
   ```

   This initializes the remaining base schema and reports health/configuration.
   The relevant collection commands initialize their own additional tables.
   Saved weights remain available; do not retrain them just to create tables.
5. Recollect public schedules/results and box scores for every season the model
   uses. These are examples for 2025 and 2026; repeat for earlier required
   seasons. They make real provider requests, so respect keys, quota and pacing:

   ```powershell
   python -m sigmalab history backfill --sport ncaaf --season 2025 --season 2026
   python -m sigmalab history boxes --sport ncaaf --season 2025 --season 2026 --limit 500
   python -m sigmalab hoops backfill --league ncaam --season 2025 --season 2026
   python -m sigmalab hoops boxes --season 2025 --season 2026 --limit 500
   python -m sigmalab once
   ```

   Box collection is resumable; repeat limited batches until coverage is adequate.
   Reacquire public supplementary inputs too: the basketball impact reader
   expects `C:/SigmaLabData/sdv/ncaa_mbb_matchup_stints_<season>.csv.gz`.
   Those CSVs are intentionally not in the small backup. Check the source and
   coverage before enabling that part of the model; the code does not promise
   that `once` downloads every historical/supplementary dataset automatically.
6. Check coverage and freshness before publishing:

   ```powershell
   python -m sigmalab hoops coverage
   python -m sigmalab refresh check --sport ncaaf --sport ncaam --season 2026
   ```

   Rebuild derived ratings with the saved model/settings once inputs are complete.
   A controlled refresh can use `refresh run ... --no-publish`; review the results
   before exporting the Matchday handoff and resuming scheduled tasks. Restore
   small Matchday/Sigma-local model-state snapshots to new filenames the same
   way if needed; their other tables are recreated by their applications.

## What can and cannot be recreated

The saved engine and fitted parameters are preserved independently of fixtures.
Public fixture/history data is recoverable only while its providers still offer
it. Public endpoints can revise or remove old records. Historical pregame odds,
availability observations, published pick receipts and exact old outputs may
not be reconstructable. This plan deliberately does not promise to recover
those records or to produce identical historical ratings after recollection.

The backup preserves existing code and model state; it does not guarantee that
an empty fixture database can immediately generate valid ratings. Restore data
coverage first, and retain the previously fitted weights until you deliberately
choose to retrain on a complete replacement dataset.
