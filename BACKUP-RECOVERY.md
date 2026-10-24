# Matchday and Sigma Lab recovery

For exact database recovery, use [EXACT-RECOVERY.md](EXACT-RECOVERY.md) and
`scripts/exact_database_backup.py`. Native archives preserve internal row IDs
and database settings and are verified by byte-identical decompression.
The SQL exports described below are an additional logical recovery option.

The irreplaceable input is Sigma Lab's configured database, currently
`C:\SigmaLabData\sigmalab.sqlite3` (approximately 92 GB on 2026-10-24).
Cloning GitHub alone does not restore it. Sigma Lab ignores `data/`; Matchday
also ignores many provider caches. Preserve raw data, ballots, model artifacts,
ledgers, and local configuration together with the source code.

## Create a backup

Use Python 3.11 or later. From either repository, run:

```powershell
python scripts/backup_projects.py --destination 'YOUR-PRIVATE-CLOUD-FOLDER\Matchday-SigmaLab-Recovery'
```

The tool backs up both Desktop repositories and resolves Sigma Lab's external
database from `.env`. Set `--desktop PATH` if the repositories move.
It creates a unique dated folder, never deletes older copies, and writes:

- Verified Git bundles with all referenced branches and tags.
- ZIP archives of current files, including uncommitted work, ignored data,
  `.env`, and `config_keys.py` where present. Keep these archives private.
- Compressed SQL snapshots of SQLite databases, using a read transaction to
  include committed WAL content without copying a live database file blindly.
- A manifest with source database paths, SHA-256 hashes and completion status.

Dependencies, browser profiles, Python caches, built frontend files, nested
worktrees and their changes are excluded. Original Git reflog-only commits and
Git LFS objects are not included in Git bundles. Keep separate copies of any
unique work in excluded worktrees. This is a project backup, not a disk image.

Sigma Lab's large database is streamed into compressed SQL because the SSD
does not have space for a second uncompressed copy. The initial run can take
hours. It holds a database read snapshot; concurrent writes can grow the WAL.
The database export stops if destination free space drops below 5 GiB.
Other files are copied individually and are not one cross-project transaction.

A status containing `COMPLETE_LOCAL` means files finished locally. It DOES NOT
prove cloud upload. Incomplete folders must never be treated as recovery copies.
Wait for OneDrive to show upload complete, then confirm the files exist through
the cloud website or a second device. Verify cloud quota before large runs.
After that, use OneDrive's **Free up space** on completed folders if necessary;
deleting synced folders deletes the cloud copy too.

## Restore on another computer

1. Download a complete dated folder and its manifest. Verify each file's SHA-256
   using `Get-FileHash -Algorithm SHA256` against the manifest.
2. Create new, empty project folders. Extract the corresponding ZIP. Its first
   directory is the project name. Use the bundle to recover history, for example
   `git clone Matchday.bundle recovered-matchday`, then overlay the saved
   working files. The bundle is authoritative for committed history; the ZIP
   preserves the working files.
3. Restore each compressed database to a NEW filename:

   ```powershell
   python scripts/backup_projects.py --restore 'BACKUP\Sigma-Lab-0-sigmalab.sqlite3.sql.gz' --output 'C:\RecoveredData\sigmalab.sqlite3'
   ```

   Use the actual filename in the manifest. The tool refuses overwrites and
   checks restored database integrity. An interrupted/failed restore leaves a
   partial database; retry with a fresh filename. Restoring needs enough disk
   space for the entire uncompressed database, plus operating headroom.
4. Restore the external-data ZIP contents alongside the recovered database.
   Update `SIGMALAB_DB` in Sigma Lab's `.env` to its new path. Restore the smaller
   project databases to the paths listed in the manifest. Stop services before
   replacing live database files; never mix old WAL/SHM sidecars with a restore.
5. Reinstall Python/frontend dependencies from the repository documentation.
   Run Sigma Lab's `python -m sigmalab doctor`, check historical data and ratings,
   then start both applications and verify Matchday's rating handoff.

## Backup routine

Run daily after collection and before significant model/data changes. Keep at
least seven daily and four weekly recovery points if storage allows. No daily
schedule or automatic retention is installed by this script. Keep another copy
on a separate drive when possible, and perform a full restore drill periodically.
Small sample restore tests prove the tool's basic behavior; only a successful
full restore proves the actual 92 GB database is recoverable.

Cloud account access and recovery credentials must survive loss of this PC.
Do not commit databases, secrets or backup archives into public Git history.
