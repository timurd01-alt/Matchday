# Recover the same Matchday and Sigma Lab data

This is an optional full-database procedure. The owner's current routine plan
preserves the engine and recollects fixtures; see
[Backup plan notes](BACKUP-PLAN-NOTES.md) and `scripts/backup_engine.py`.

Recovery uses saved database contents, not a fresh provider download. APIs can
change or remove history, so refetching is not an exact recovery method.

## What must travel together

- Native database archives (`*.sqlite3.gz`) and their `exact-recovery.json`
  manifests. They preserve tables, values, internal row IDs, indexes, triggers,
  and database settings from one committed SQLite snapshot.
- The saved project-file ZIPs, including local configuration, ballots, model
  artifacts, raw supplementary files and rating inputs.
- Git bundles for code history; Python/dependency versions and lockfiles for
  reproducing the application environment.

The verified SHA-256 identifies the saved native snapshot. Decompression must
produce exactly those bytes. This does not mean the file will match the live
database after later writes. Each database has its own snapshot timestamp;
the project-file archives and different databases are not a single transaction.

## On the replacement computer

1. Install Python 3.12. Extract `project-files/matchday-files.zip` and move its
   `matchday` directory to `Desktop\matchday`. Extract
   `project-files/Sigma-Lab-files.zip`, then move/rename its `Sigma-Lab`
   directory to `Desktop\Sigma Lab`. Keep its separate
   `Sigma-Lab-external-data` directory for step 4.
   Recover Git history from the corresponding `.bundle` if needed; overlay the
   saved project files so uncommitted work and ignored input files are restored.
2. Keep both apps and their scheduled collectors stopped during restoration.
   For Sigma Lab's main database, run this using the actual recovery folder:

   ```powershell
   python tools/exact_database_backup.py restore --archive "sigma-main/sigmalab.sqlite3.gz" --output "C:/SigmaLabData/sigmalab.sqlite3"
   ```

   Run it from the recovery package directory. If using the script saved in a
   repository instead, its path is `scripts/exact_database_backup.py`.
   The tool checks the archive checksum, reconstructs the native database,
   compares every restored byte by SHA-256, and runs SQLite integrity checks.
   It refuses to overwrite an existing file. A failed/interrupted restore must
   be retried with a new output filename. NTFS compression keeps the large
   restored file compressed on disk transparently; SQLite reads it normally.
3. Keep `SIGMALAB_DB` in Sigma Lab's restored `.env` set to
   `C:/SigmaLabData/sigmalab.sqlite3`. Restore the original directory layout:
   the basketball impact model also explicitly reads its supplementary files
   from `C:/SigmaLabData/sdv`, independently of the database setting.
4. Restore the two smaller databases with the same tool:

   ```powershell
   python tools/exact_database_backup.py restore --archive "matchday/betbetter.sqlite3.gz" --output "$env:USERPROFILE/Desktop/matchday/data/betbetter.sqlite3"
   python tools/exact_database_backup.py restore --archive "sigma-local/betbetter.sqlite3.gz" --output "$env:USERPROFILE/Desktop/Sigma Lab/data/betbetter.sqlite3"
   ```

   Use new empty destinations. Never combine recovered databases with WAL/SHM
   files left by another copy. Restore `Sigma-Lab-external-data` from the saved
   project ZIP into `C:/SigmaLabData`, including its `sdv` directory. Copy the
   contents of `Sigma-Lab-external-data`, not that enclosing directory itself.
5. Restore the same code, model settings, ballots and dependency versions
   before running ratings. Use the saved lockfiles. Check the rating workflow
   with collection disabled/offline first; then resume normal collection.
   New collection changes the database, so compare checksums before starting it.

## Proof of recovery

Only use a native archive whose manifest says
`PASS_NATIVE_INTEGRITY_AND_BYTE_IDENTICAL_DECOMPRESSION`. It records the source
path, snapshot timestamp, database size and settings, archive SHA-256, and the
matching native/decompressed SHA-256 values. The restore command repeats those
checks when used on the replacement computer.

The earlier `.sql.gz` export is an additional logical recovery copy. Prefer the
native `.sqlite3.gz` archive for exact recovery, because SQL replay can change
internal row IDs and does not preserve every database-file setting.

Having the same data is necessary but does not alone prove identical rating
outputs. The model/code version, inputs, configuration, dependency versions,
time-dependent behavior and any random seeds must also match. No prediction
pipeline is run automatically as part of this database recovery test.

Local copies prove restoration but remain vulnerable to loss of this SSD.
Keep the verified recovery package on another device/location for hardware
failure protection. The storage choice is separate from these recovery checks.
