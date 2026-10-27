"""Create and verify consistent SQLite backups for the pilot service.

The source database may remain online while SQLite's backup API takes a
transactionally consistent snapshot. Backups are created with restrictive
filesystem permissions and verified before the temporary file is promoted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3


def verify_database(path: Path) -> None:
    """Raise when *path* is missing or fails SQLite's integrity check."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Database file does not exist: {path}')
    uri = f'{path.as_uri()}?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        result = connection.execute('PRAGMA integrity_check').fetchone()
    if not result or result[0] != 'ok':
        detail = result[0] if result else 'no result'
        raise RuntimeError(f'SQLite integrity check failed: {detail}')


def create_backup(source: Path, output_dir: Path, keep: int = 14) -> Path:
    """Create a verified online backup and retain the newest *keep* copies."""
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if keep < 1:
        raise ValueError('Backup retention must be at least 1.')
    verify_database(source)

    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        output_dir.chmod(0o700)
    except OSError:
        pass

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = output_dir / f'academic-weapon-{timestamp}.sqlite3'
    temporary = destination.with_suffix('.sqlite3.incomplete')

    if temporary.exists():
        temporary.unlink()
    source_uri = f'{source.as_uri()}?mode=ro'
    try:
        with sqlite3.connect(source_uri, uri=True) as source_connection:
            with sqlite3.connect(temporary) as backup_connection:
                source_connection.backup(backup_connection)
        temporary.chmod(0o600)
        verify_database(temporary)
        os.replace(temporary, destination)
        destination.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()

    backups = sorted(
        output_dir.glob('academic-weapon-*.sqlite3'),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create or verify a consistent Academic Weapon SQLite backup.'
    )
    parser.add_argument(
        '--source',
        type=Path,
        default=Path(os.getenv('APSS_DB_PATH', 'academic_weapon.sqlite3')),
        help='Active SQLite database (defaults to APSS_DB_PATH).',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Backup directory (defaults to a backups folder beside the database).',
    )
    parser.add_argument('--keep', type=int, default=14, help='Number of backups to retain.')
    parser.add_argument(
        '--verify-only',
        type=Path,
        help='Verify one existing database or backup without creating a new copy.',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify_only:
        verify_database(args.verify_only)
        print(f'Integrity check passed: {args.verify_only.expanduser().resolve()}')
        return 0
    output_dir = args.output_dir or args.source.expanduser().resolve().parent / 'backups'
    destination = create_backup(args.source, output_dir, args.keep)
    print(f'Backup created and verified: {destination}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
