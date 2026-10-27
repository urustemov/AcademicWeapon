"""Backup checks use disposable databases and never touch pilot data."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from backup_database import create_backup, verify_database


def create_source(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
        connection.execute('INSERT INTO records(value) VALUES (?)', ('original',))


def test_online_backup_is_consistent_and_restrictive(tmp_path):
    source = tmp_path / 'source.sqlite3'
    output_dir = tmp_path / 'backups'
    create_source(source)

    backup = create_backup(source, output_dir, keep=2)
    verify_database(backup)
    with sqlite3.connect(source) as connection:
        connection.execute('UPDATE records SET value=?', ('changed later',))
    with sqlite3.connect(backup) as connection:
        assert connection.execute('SELECT value FROM records').fetchone()[0] == 'original'

    assert backup.parent == output_dir
    assert backup.stat().st_mode & 0o077 == 0
    assert output_dir.stat().st_mode & 0o077 == 0


def test_backup_retention_and_validation(tmp_path):
    source = tmp_path / 'source.sqlite3'
    output_dir = tmp_path / 'backups'
    create_source(source)

    for _ in range(3):
        create_backup(source, output_dir, keep=2)
    assert len(list(output_dir.glob('academic-weapon-*.sqlite3'))) == 2

    invalid = tmp_path / 'invalid.sqlite3'
    invalid.write_text('not a database', encoding='utf-8')
    with pytest.raises((sqlite3.DatabaseError, RuntimeError)):
        verify_database(invalid)
