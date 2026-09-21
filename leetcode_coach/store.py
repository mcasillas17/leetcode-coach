"""SQLite schema, serialized writes, and consistent non-destructive backups."""

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


class CoachError(ValueError):
    """An actionable input or state error safe to show in the CLI."""


SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE problems (
    slug TEXT PRIMARY KEY, frontend_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL, difficulty TEXT NOT NULL, url TEXT NOT NULL,
    tags TEXT NOT NULL
);
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
    mode TEXT NOT NULL, summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
    slug TEXT NOT NULL REFERENCES problems(slug), language TEXT NOT NULL,
    working_file TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL,
    is_review INTEGER NOT NULL, state TEXT NOT NULL,
    phase TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    outcome TEXT, timing_confirmed INTEGER NOT NULL DEFAULT 1,
    hint_level INTEGER NOT NULL DEFAULT 0, hint_count INTEGER NOT NULL DEFAULT 0,
    teach_back INTEGER NOT NULL DEFAULT 0, review_date TEXT, review_override TEXT
);
CREATE UNIQUE INDEX one_open_attempt ON attempts((1))
    WHERE state IN ('running', 'paused');
CREATE TABLE intervals (
    id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    phase TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
    corrected_seconds REAL
);
CREATE UNIQUE INDEX one_open_interval ON intervals(attempt_id) WHERE ended_at IS NULL;
CREATE TABLE events (
    id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    created_at TEXT NOT NULL, language TEXT NOT NULL, sha256 TEXT NOT NULL,
    code BLOB NOT NULL
);
CREATE TABLE judge_results (
    id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), at TEXT NOT NULL,
    source TEXT NOT NULL, kind TEXT NOT NULL, verdict TEXT NOT NULL,
    submission_id TEXT NOT NULL DEFAULT '', runtime_ms REAL, memory_mb REAL,
    UNIQUE(attempt_id, snapshot_id, source, kind, verdict, submission_id)
);
CREATE TABLE feedback (
    attempt_id INTEGER PRIMARY KEY REFERENCES attempts(id),
    at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TRIGGER immutable_snapshots_update BEFORE UPDATE ON snapshots
BEGIN SELECT RAISE(ABORT, 'Snapshots are immutable'); END;
CREATE TRIGGER immutable_snapshots_delete BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'Snapshots are immutable'); END;
CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
"""


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.directory = self.root / '.coach'
        if self.directory.is_symlink():
            raise CoachError('The .coach data directory must not be a symlink.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'progress.sqlite3'
        if self.path.is_symlink():
            raise CoachError('The database must not be a symlink.')
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            with self.transaction():
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, SCHEMA_VERSION):
                    raise CoachError('Unsupported database schema; use a compatible coach version.')
                if version == 0:
                    if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        raise CoachError('Unrecognized database schema; refusing to change it.')
                    # executescript commits implicitly; complete statements preserve this transaction.
                    statement = ''
                    for line in SCHEMA.splitlines(True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            self.db.execute(statement)
                            statement = ''
                    self.db.execute('PRAGMA user_version=1')
            os.chmod(self.path, 0o600)
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()

    @staticmethod
    def copy_database(connection, destination):
        destination = Path(destination).expanduser().absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CoachError('Backup/restore destination already exists; choose a new path.') from exc
        os.close(fd)
        try:
            with closing(sqlite3.connect(destination)) as target:
                connection.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise CoachError('Backup integrity check failed.')
            return str(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def backup(self, destination):
        return self.copy_database(self.db, destination)

    @classmethod
    def restore(cls, root, source):
        source = Path(source).expanduser().resolve(strict=True)
        destination_dir = Path(root).expanduser().resolve() / '.coach'
        if destination_dir.is_symlink():
            raise CoachError('The .coach data directory must not be a symlink.')
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise CoachError('Unsupported backup schema.')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise CoachError('Backup integrity check failed.')
            required = {'problems', 'sessions', 'attempts', 'intervals', 'events', 'snapshots', 'judge_results', 'feedback'}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required.issubset(tables) or db.execute('PRAGMA foreign_key_check').fetchone():
                raise CoachError('Invalid backup schema or references.')
            destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            return cls.copy_database(db, destination_dir / 'progress.sqlite3')
