"""Private recovery backup. Python 3.11+, standard library only.

Run with --destination PATH. Restore SQL with --restore SQL.GZ --output NEW.DB.
Never publish the resulting archives: they include private data and configuration.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import time
import zipfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump_database(source, target):
    # One read transaction includes committed WAL data and fixes the snapshot.
    # A logical dump avoids needing a second 92GB uncompressed database.
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=60) as db:
        db.execute('BEGIN')
        db.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
        last_report = time.monotonic()
        rows = 0
        with gzip.open(target, 'wt', encoding='utf-8', compresslevel=6) as stream:
            for statement in db.iterdump():
                stream.write(statement)
                stream.write('\n')
                rows += 1
                if time.monotonic() - last_report >= 30:
                    print(f'{source.name}: {rows:,} SQL statements; compressed {target.stat().st_size / 2**30:.2f} GiB', flush=True)
                    if shutil.disk_usage(target.parent).free < 5 * 2**30:
                        raise OSError('Stopped backup to preserve 5 GiB of free disk space')
                    last_report = time.monotonic()
        db.rollback()


def restore(source, output):
    # Never overwrite an existing database, including one with WAL sidecars.
    if any(Path(str(output) + suffix).exists() for suffix in ('', '-wal', '-shm')):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as db:
        pending = ''
        with gzip.open(source, 'rt', encoding='utf-8') as stream:
            for line in stream:
                pending += line
                if sqlite3.complete_statement(pending):
                    db.execute(pending)
                    pending = ''
        if pending.strip():
            raise ValueError('Incomplete SQL backup')
        result = db.execute('PRAGMA integrity_check').fetchall()
        if result != [('ok',)]:
            raise ValueError(result)
    print('Restored and integrity checked:', output, flush=True)


def database_path(project):
    values = dict(os.environ)
    env = project / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip().strip('\"\''))
    raw = values.get('SIGMALAB_DB', values.get('BETBETTER_DB'))
    return (project / raw).resolve() if raw else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--desktop', type=Path, default=Path.home() / 'Desktop')
    parser.add_argument('--restore', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.restore:
        if not args.output:
            parser.error('--output NEW.DB is required')
        restore(args.restore, args.output)
        return
    if not args.destination:
        parser.error('--destination is required; choose a private cloud-synced folder')
    projects = [args.desktop / 'matchday', args.desktop / 'Sigma Lab']
    for project in projects:
        if not (project / '.git').exists():
            raise FileNotFoundError(project)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    folder = args.destination / ('recovery-' + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'INCOMPLETE', 'created_local': stamp, 'files': [],
                'notes': 'Private. Cloud upload must be confirmed separately. No automatic deletion.'}
    manifest_path = folder / 'manifest.json'
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    save()
    try:
        for project in projects:
            label = project.name.replace(' ', '-')
            print('Backing up', project, flush=True)
            bundle = folder / (label + '.bundle')
            subprocess.run(['git', '-C', str(project), 'bundle', 'create', str(bundle), '--all'], check=True)
            subprocess.run(['git', '-C', str(project), 'bundle', 'verify', str(bundle)], check=True,
                           stdout=subprocess.DEVNULL)
            configured = database_path(project) if project.name == 'Sigma Lab' else None
            databases = set()
            excluded = {'.git', 'node_modules', '__pycache__', '.browser-profile', '.worktrees',
                        '.matchday-status-worktree', 'dist', '.venv', 'venv'}
            archive = folder / (label + '-files.zip')
            roots = [(project, Path(label))]
            if configured:
                if not configured.is_file():
                    raise FileNotFoundError(configured)
                databases.add(configured)
                if not configured.is_relative_to(project):
                    roots.append((configured.parent, Path(label + '-external-data')))
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
                for root, prefix in roots:
                    for current, dirs, names in os.walk(root):
                        dirs[:] = [d for d in dirs if d not in excluded and not (Path(current) / d).is_symlink()]
                        for name in names:
                            path = Path(current) / name
                            if path.is_symlink() or name.endswith(('-wal', '-shm', '.pyc')):
                                continue
                            with path.open('rb') as probe:
                                header = probe.read(16)
                            if header == b'SQLite format 3\x00':
                                databases.add(path.resolve())
                                continue
                            z.write(path, str(prefix / path.relative_to(root)))
            for index, database in enumerate(sorted(databases)):
                target = folder / f'{label}-{index}-{database.name}.sql.gz'
                print('Snapshotting database:', database, '->', target, flush=True)
                dump_database(database, target)
                manifest['files'].append({'name': target.name, 'source': str(database),
                                          'bytes': target.stat().st_size, 'sha256': digest(target)})
                save()
            for path in (bundle, archive):
                manifest['files'].append({'name': path.name, 'bytes': path.stat().st_size,
                                          'sha256': digest(path)})
            save()
        manifest['status'] = 'COMPLETE_LOCAL_CLOUD_UPLOAD_UNCONFIRMED'
        save()
        print('Backup complete locally:', folder, flush=True)
    except BaseException as error:
        manifest['error'] = str(error)
        save()
        raise


if __name__ == '__main__':
    main()
