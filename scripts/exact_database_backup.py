"""Native SQLite recovery with verified byte-identical compression round trip.

create --source DB --folder NEW_FOLDER
restore --archive DB.sqlite3.gz --output NEW_DB
Only standard Python libraries and Windows' built-in NTFS compression are used.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


def hash_stream(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def prepare_output(path, expected_bytes):
    if any(Path(str(path) + suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')):
        raise FileExistsError('Refusing to overwrite: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)
    if os.name == 'nt':
        subprocess.run(['compact.exe', '/C', '/Q', str(path)], check=True, capture_output=True)
        if not path.stat().st_file_attributes & 0x800:
            raise OSError('NTFS compression was not enabled on the recovery file')
    elif shutil.disk_usage(path.parent).free < expected_bytes + 5 * 2**30:
        raise OSError('Insufficient space for uncompressed database plus 5 GiB reserve')


def check_space(folder):
    if shutil.disk_usage(folder).free < 5 * 2**30:
        raise OSError('Stopped to preserve 5 GiB of free disk space')


def integrity(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Database integrity check failed')


def create(source, folder):
    if not source.is_file():
        raise FileNotFoundError(source)
    folder.mkdir(parents=True, exist_ok=False)
    image = folder / source.name
    archive = folder / (source.name + '.gz')
    manifest_path = folder / 'exact-recovery.json'
    report = {'status': 'INCOMPLETE', 'source': str(source.resolve()),
              'snapshot_started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'method': 'SQLite native online backup; lossless gzip; NTFS-compressed local image',
              'native_image': image.name, 'archive': archive.name}
    def save():
        manifest_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        prepare_output(image, source.stat().st_size)
        last = time.monotonic()
        def progress(status, remaining, total):
            nonlocal last
            check_space(folder)
            if time.monotonic() - last >= 30 or remaining == 0:
                print(f'Native snapshot: {total - remaining:,}/{total:,} pages', flush=True)
                last = time.monotonic()
        with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=60) as src:
            src.execute('BEGIN')
            src.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
            report['page_size'] = src.execute('PRAGMA page_size').fetchone()[0]
            report['page_count'] = src.execute('PRAGMA page_count').fetchone()[0]
            report['user_version'] = src.execute('PRAGMA user_version').fetchone()[0]
            report['application_id'] = src.execute('PRAGMA application_id').fetchone()[0]
            report['encoding'] = src.execute('PRAGMA encoding').fetchone()[0]
            report['table_names'] = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            save()
            with sqlite3.connect(image) as dest:
                src.backup(dest, pages=2048, progress=progress, sleep=0.1)
            src.rollback()
        report['status'] = 'CHECKING_NATIVE_IMAGE'
        save()
        print('Checking native database integrity', flush=True)
        integrity(image)
        report['native_integrity'] = 'PASS'
        report['uncompressed_bytes'] = image.stat().st_size
        report['status'] = 'COMPRESSING'
        save()
        original_hash = hashlib.sha256()
        copied = 0
        last = time.monotonic()
        with image.open('rb') as raw, gzip.open(archive, 'wb', compresslevel=1) as packed:
            for block in iter(lambda: raw.read(8 * 1024 * 1024), b''):
                check_space(folder)
                original_hash.update(block)
                packed.write(block)
                copied += len(block)
                if time.monotonic() - last >= 30:
                    print(f'Lossless compression: {copied / 2**30:.2f}/{image.stat().st_size / 2**30:.2f} GiB', flush=True)
                    last = time.monotonic()
        report['image_sha256'] = original_hash.hexdigest()
        report['status'] = 'VERIFYING_DECOMPRESSION'
        save()
        print('Verifying decompression reproduces every byte of the native image', flush=True)
        with gzip.open(archive, 'rb') as packed:
            restored_hash = hash_stream(packed)
        if restored_hash != report['image_sha256']:
            raise ValueError('Compressed archive does not reproduce the native database image')
        with archive.open('rb') as packed:
            report['archive_sha256'] = hash_stream(packed)
        report['archive_bytes'] = archive.stat().st_size
        report['decompressed_sha256'] = restored_hash
        report['status'] = 'PASS_NATIVE_INTEGRITY_AND_BYTE_IDENTICAL_DECOMPRESSION'
        report['verified_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Only this tool's own staging image is removed, after verified recovery.
        # The original source and the verified archive are always preserved.
        try:
            image.unlink()
            report['native_image_retained'] = False
        except OSError:
            report['native_image_retained'] = True
        save()
        print(report['status'], flush=True)
    except BaseException as error:
        report['status'] = 'FAILED'
        report['error'] = str(error)
        save()
        raise


def restore(archive, output):
    manifest_path = archive.parent / 'exact-recovery.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['status'] != 'PASS_NATIVE_INTEGRITY_AND_BYTE_IDENTICAL_DECOMPRESSION':
        raise ValueError('Backup has not passed exact recovery verification')
    if archive.name != manifest['archive']:
        raise ValueError('Archive name does not match its recovery manifest')
    with archive.open('rb') as packed:
        if hash_stream(packed) != manifest['archive_sha256']:
            raise ValueError('Backup archive checksum failed')
    prepare_output(output, manifest['uncompressed_bytes'])
    restored_hash = hashlib.sha256()
    with gzip.open(archive, 'rb') as packed, output.open('wb') as raw:
        for block in iter(lambda: packed.read(8 * 1024 * 1024), b''):
            check_space(output.parent)
            raw.write(block)
            restored_hash.update(block)
    if output.stat().st_size != manifest['uncompressed_bytes'] or restored_hash.hexdigest() != manifest['image_sha256']:
        raise ValueError('Restored database is not byte-identical to the saved native snapshot')
    integrity(output)
    print('PASS: restored database is byte-identical to the native snapshot and integrity checked', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--source', type=Path, required=True)
    make.add_argument('--folder', type=Path, required=True)
    recover = commands.add_parser('restore')
    recover.add_argument('--archive', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'create':
        create(args.source, args.folder)
    else:
        restore(args.archive, args.output)
