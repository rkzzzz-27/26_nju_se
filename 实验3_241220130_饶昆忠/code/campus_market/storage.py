"""SQLite schema and transaction boundary for the campus market."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('student', 'admin')),
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_codes (
    email TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES accounts(id),
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    images_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    audited_by TEXT REFERENCES accounts(id),
    audited_at TEXT,
    audit_reason TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_public
    ON listings(status, published_at DESC, price_cents);
CREATE INDEX IF NOT EXISTS idx_listings_seller
    ON listings(seller_id, created_at DESC);

CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(id),
    buyer_id TEXT NOT NULL REFERENCES accounts(id),
    request_id TEXT NOT NULL,
    price_snapshot_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    ended_at TEXT,
    end_reason TEXT,
    pending_reminded_at TEXT,
    confirmed_reminded_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_reservation
    ON reservations(listing_id)
    WHERE status IN ('pending_seller', 'confirmed');
CREATE INDEX IF NOT EXISTS idx_reservations_buyer
    ON reservations(buyer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reservations_deadline
    ON reservations(status, created_at, confirmed_at);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(id),
    reporter_id TEXT NOT NULL REFERENCES accounts(id),
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    handled_by TEXT REFERENCES accounts(id),
    handled_at TEXT,
    decision_reason TEXT,
    merged_into_id TEXT REFERENCES reports(id),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_report_per_student
    ON reports(listing_id, reporter_id)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_reports_listing
    ON reports(listing_id, status);

CREATE TABLE IF NOT EXISTS request_receipts (
    account_id TEXT NOT NULL REFERENCES accounts(id),
    request_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    target_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    first_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, request_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    recipient_id TEXT NOT NULL REFERENCES accounts(id),
    event_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    UNIQUE (recipient_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications(recipient_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT REFERENCES accounts(id),
    operation TEXT NOT NULL,
    target_id TEXT,
    before_state TEXT,
    after_state TEXT,
    result TEXT NOT NULL,
    request_id TEXT,
    reason TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_search
    ON audit_logs(operation, actor_id, occurred_at DESC);
"""


class Storage:
    """Creates one SQLite connection per operation for safe threaded access."""

    def __init__(self, database_path: str | Path):
        self.path = str(database_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(SCHEMA)
        finally:
            connection.close()

    @contextmanager
    def transaction(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


def one(connection: sqlite3.Connection, query: str, args: tuple = ()) -> dict | None:
    row = connection.execute(query, args).fetchone()
    return dict(row) if row is not None else None


def many(connection: sqlite3.Connection, query: str, args: tuple = ()) -> list[dict]:
    return [dict(row) for row in connection.execute(query, args).fetchall()]
