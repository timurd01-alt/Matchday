"""Small engine backup: source, configuration and fitted state; no fixtures.

create --destination PRIVATE_FOLDER
restore --state STATE.sqlite3 --output NEW_DATABASE.sqlite3
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

MODEL_TABLES = ('hoops_weights', 'model_reports', 'model_runs', 'model_run_metadata',
                'hoops_ratings', 'ballot_editions', 'ballot_rankings')
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.browser-profile', '.worktrees',
             '.matchday-status-worktree', 'data', 'archive', 'output', 'reports',
             'dist', '_site', '.venv', 'venv', 'logs', '.claude', '.codex', '.aws'}
TEXT_EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.scss', '.md',
                   '.txt', '.toml', '.yaml', '.yml', '.lock', '.ps1', '.cmd', '.bat', '.sql'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def table_hash(db, table):
    info = db.execute('PRAGMA table_info(' + quote(table) + ')').fetchall()
    keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    order = ','.join(map(quote, keys)) if keys else 'rowid'
    h = hashlib.sha256()
    count = 0
    for row in db.execute('SELECT * FROM ' + quote(table) + ' ORDER BY ' + order):
        h.update(repr(tuple(row)).encode('utf-8'))
        h.update(b'\n')
        count += 1
    return {'rows': count, 'values_sha256': h.hexdigest()}


def export_state(source, output):
    if output.exists():
        raise FileExistsError(output)
    result = {}
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=60) as src:
        src.execute('BEGIN')
        with sqlite3.connect(output) as dst:
            for table in MODEL_TABLES:
                schema = src.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone()
                if not schema:
                    continue
                dst.execute(schema[0])
                cursor = src.execute('SELECT * FROM ' + quote(table))
                insert = 'INSERT INTO ' + quote(table) + ' VALUES (' + ','.join('?' for _ in cursor.description) + ')'
                while batch := cursor.fetchmany(512):
                    dst.executemany(insert, batch)
                expected = table_hash(src, table)
                if table_hash(dst, table) != expected:
                    raise ValueError('Model-state round trip failed: ' + table)
                result[table] = expected
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Model-state database integrity failed')
        src.rollback()
    return result


def include_file(path):
    name = path.name.lower()
    if name.startswith(('.env', 'config_keys')) or name in {'.npmrc', '.pypirc'}:
        return False
    if name in {'.gitignore', '.gitattributes'}:
        return True
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    if path.suffix.lower() != '.json':
        return False
    if any(word in name for word in ('cache', 'ledger', 'rows', 'scorecard', 'picks', 'odds', 'data_', 'report')):
        return False
    return name in {'package.json', 'tsconfig.json', 'vercel.json', 'manifest.json'} or any(
        word in name for word in ('model', 'weight', 'calib', 'config', 'parameter', 'preregistration', 'promotion', 'experiment', 'quota_budget'))


def create(destination, desktop, main_db):
    destination, desktop, main_db = destination.resolve(), desktop.resolve(), main_db.resolve()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    root = destination / ('engine-recovery-' + stamp)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'state').mkdir()
    report = {'status': 'INCOMPLETE', 'created_local': stamp, 'scope': 'engine and fitted state; fixtures excluded',
              'python': sys.version, 'sqlite': sqlite3.sqlite_version, 'files': [], 'model_state': {}}
    manifest = root / 'engine-manifest.json'
    def save():
        manifest.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        for name in ('matchday', 'Sigma Lab'):
            project = desktop / name
            label = name.replace(' ', '-')
            bundle = root / (label + '.bundle')
            subprocess.run(['git', '-C', str(project), 'bundle', 'create', str(bundle), '--all'], check=True)
            subprocess.run(['git', '-C', str(project), 'bundle', 'verify', str(bundle)], check=True, capture_output=True)
            archive = root / (label + '-engine.zip')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for current, dirs, names in os.walk(project):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (Path(current) / d).is_symlink()]
                    for filename in names:
                        path = Path(current) / filename
                        if not path.is_symlink() and include_file(path):
                            z.write(path, str(Path(name) / path.relative_to(project)))
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    raise ValueError('Engine archive CRC failed')
        for label, database in [('sigma-main', main_db), ('sigma-local', desktop/'Sigma Lab/data/betbetter.sqlite3'),
                                ('matchday', desktop/'matchday/data/betbetter.sqlite3')]:
            if database.is_file():
                report['model_state'][label] = export_state(database, root/'state'/(label+'.sqlite3'))
        learned = root / 'learned-rapm'
        learned.mkdir()
        for path in sorted((main_db.parent/'sdv').glob('rapm_*.json')):
            shutil.copy2(path, learned/path.name)
        shutil.copy2(Path(__file__), root/'backup_engine.py')
        for name in ('BACKUP-PLAN-NOTES.md',):
            guide = Path(__file__).parent/name
            if not guide.exists():
                guide = desktop/'Sigma Lab'/name
            if guide.exists():
                shutil.copy2(guide, root/name)
        for path in sorted(root.rglob('*')):
            if path.is_file() and path != manifest:
                report['files'].append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)})
        report['status'] = 'PASS_ENGINE_ARCHIVES_AND_MODEL_STATE_ROUND_TRIP'
        save()
        print('Verified engine package:', root, flush=True)
    except BaseException as error:
        report['status'] = 'FAILED'
        report['error'] = str(error)
        save()
        raise


def restore(state, output):
    if any(Path(str(output)+suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')):
        raise FileExistsError('Use a new database filename')
    # Verify the package fingerprint before copying fitted state.
    root = state.parent.parent
    manifest = json.loads((root/'engine-manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'PASS_ENGINE_ARCHIVES_AND_MODEL_STATE_ROUND_TRIP':
        raise ValueError('Engine package has not passed verification')
    item = next(x for x in manifest['files'] if x['path'] == state.relative_to(root).as_posix())
    if sha(state) != item['sha256']:
        raise ValueError('Model-state checksum mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(state, output)
    with sqlite3.connect(output) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Restored model state integrity failed')
    print('Restored engine parameters into new database:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--destination', type=Path, required=True)
    make.add_argument('--desktop', type=Path, default=Path.home()/'Desktop')
    make.add_argument('--main-db', type=Path, default=Path('C:/SigmaLabData/sigmalab.sqlite3'))
    recover = commands.add_parser('restore')
    recover.add_argument('--state', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'create':
        create(args.destination, args.desktop, args.main_db)
    else:
        restore(args.state, args.output)
