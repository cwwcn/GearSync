import fcntl
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sync_types import SyncError


class SyncState:
    def __init__(self, path, source, source_account, target, target_account):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        identity = json.dumps([source, source_account, target, target_account], separators=(',', ':'))
        self.scope = hashlib.sha256(identity.encode()).hexdigest()
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sync_runs (
                    scope TEXT PRIMARY KEY, cutoff INTEGER, watermark INTEGER, full_scan_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS sync_transfers (
                    scope TEXT NOT NULL, activity_id TEXT NOT NULL, start_ms INTEGER NOT NULL,
                    sport TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT 'pending',
                    file_hash TEXT NOT NULL DEFAULT '', original_hash TEXT NOT NULL DEFAULT '',
                    object_key TEXT NOT NULL DEFAULT '',
                    object_bucket TEXT NOT NULL DEFAULT '', object_service TEXT NOT NULL DEFAULT '',
                    object_md5 TEXT NOT NULL DEFAULT '', object_size INTEGER NOT NULL DEFAULT 0,
                    task_id TEXT NOT NULL DEFAULT '', remote_id TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    PRIMARY KEY (scope, activity_id)
                );
                CREATE INDEX IF NOT EXISTS sync_transfer_phase ON sync_transfers (scope, phase, start_ms);
                CREATE TABLE IF NOT EXISTS sync_legacy_binding (
                    source TEXT NOT NULL, target TEXT NOT NULL, scope TEXT NOT NULL,
                    PRIMARY KEY (source, target)
                );
            ''')
            db.execute('INSERT OR IGNORE INTO sync_runs (scope) VALUES (?)', (self.scope,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity_table'").fetchone():
                claimed = db.execute('''
                    INSERT OR IGNORE INTO sync_legacy_binding (source, target, scope)
                    SELECT ?, ?, ? WHERE EXISTS (
                        SELECT 1 FROM activity_table WHERE activity_source=? AND activity_target=?
                    )
                ''', (source, target, self.scope, source, target)).rowcount
                if claimed:
                    db.execute('''
                        INSERT OR IGNORE INTO sync_transfers (scope, activity_id, start_ms, phase, last_error)
                        SELECT ?, CAST(activity_id AS TEXT), 0,
                               CASE WHEN is_sync=1 THEN 'done' ELSE 'legacy_review' END,
                               CASE WHEN is_sync=1 THEN '' ELSE 'Legacy attempt has no import receipt' END
                        FROM activity_table WHERE activity_source=? AND activity_target=?
                        ORDER BY is_sync=1 DESC, id
                    ''', (self.scope, source, target))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        except sqlite3.Error as error:
            raise SyncError('Local sync database write or read failed') from error
        finally:
            db.close()

    @contextmanager
    def claim(self, activity_id):
        key = hashlib.sha256(activity_id.encode()).hexdigest()
        lock_directory = self.path.parent / 'activitySync-locks' / self.scope
        lock_directory.mkdir(parents=True, exist_ok=True)
        # Keep the lock file in place so all processes keep locking the same inode.
        with (lock_directory / f'{key}.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True

    def checkpoint(self):
        with self.connection() as db:
            return db.execute('SELECT * FROM sync_runs WHERE scope=?', (self.scope,)).fetchone()

    def discover(self, activities, *, cutoff=None, watermark=None, full_scan_at=None, checkpoint=None):
        with self.connection() as db:
            db.executemany('''
                INSERT INTO sync_transfers (scope, activity_id, start_ms, sport) VALUES (?, ?, ?, ?)
                ON CONFLICT (scope, activity_id) DO UPDATE SET start_ms=excluded.start_ms, sport=excluded.sport
                WHERE sync_transfers.phase IN ('pending', 'storage_ready', 'legacy_review')
                  AND (sync_transfers.start_ms<>excluded.start_ms OR sync_transfers.sport<>excluded.sport)
            ''', ((self.scope, activity.id, activity.start_ms, activity.sport) for activity in activities))
            if cutoff is not None:
                previous = (None, None, None) if checkpoint is None else (
                    checkpoint['cutoff'], checkpoint['watermark'], checkpoint['full_scan_at'],
                )
                db.execute('''
                    UPDATE sync_runs SET cutoff=?, watermark=?, full_scan_at=COALESCE(?, full_scan_at) WHERE scope=?
                    AND (? OR (cutoff IS ? AND watermark IS ? AND full_scan_at IS ?))
                ''', (cutoff, watermark, full_scan_at, self.scope, checkpoint is None, *previous))

    def outstanding(self, only_id=''):
        with self.connection() as db:
            return db.execute('''
                SELECT * FROM sync_transfers WHERE scope=? AND phase<>'done' AND (?='' OR activity_id=?)
                ORDER BY CASE WHEN phase IN ('submitting', 'accepted') THEN 0 ELSE 1 END, start_ms, activity_id
            ''', (self.scope, only_id, only_id)).fetchall()

    def transfer(self, activity_id):
        with self.connection() as db:
            return db.execute('SELECT * FROM sync_transfers WHERE scope=? AND activity_id=?',
                              (self.scope, activity_id)).fetchone()

    def record(self, activity_id, phase, *, file_hash=None, original_hash=None, uploaded=None,
               task_id=None, remote_id=None, error=''):
        storage = (uploaded.key, uploaded.bucket, uploaded.service, uploaded.md5, uploaded.size) if uploaded else (None,) * 5
        with self.connection() as db:
            updated = db.execute('''
                UPDATE sync_transfers SET phase=?, last_error=?, updated_at=unixepoch(),
                    file_hash=COALESCE(?, file_hash), original_hash=COALESCE(?, original_hash),
                    object_key=COALESCE(?, object_key),
                    object_bucket=COALESCE(?, object_bucket), object_service=COALESCE(?, object_service),
                    object_md5=COALESCE(?, object_md5), object_size=COALESCE(?, object_size),
                    task_id=COALESCE(?, task_id), remote_id=COALESCE(?, remote_id)
                WHERE scope=? AND activity_id=? AND phase<>'done'
            ''', (phase, error, file_hash, original_hash, *storage, task_id, remote_id,
                  self.scope, activity_id)).rowcount
            if updated != 1:
                raise SyncError('Could not update the outstanding activity')
