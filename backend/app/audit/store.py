"""Append-only SQLite storage for audit events (audit-log §4.4)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.audit.chain import GENESIS_HASH, entry_hash, payload_digest
from app.audit.events import Actor, AuditEvent, Visibility
from app.core.jcs import canonical, to_jsonable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq             INTEGER PRIMARY KEY,
    event_id        TEXT NOT NULL UNIQUE,
    time            TEXT NOT NULL,
    type            TEXT NOT NULL,
    transaction_id  TEXT,
    customer        TEXT,
    actor           TEXT NOT NULL,
    mandate         TEXT,
    visibility      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    payload_digest  TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    hash            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_tx ON audit_events(transaction_id);
CREATE INDEX IF NOT EXISTS audit_events_type ON audit_events(type);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""

_COLUMNS = "seq, event_id, time, type, transaction_id, customer, actor, mandate, visibility, payload, payload_digest, prev_hash, hash"


def connect(path: Path | str) -> sqlite3.Connection:
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class AuditStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()  # single writer: no gaps or duplicates in seq
        conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ write

    def append(
        self,
        *,
        type: str,
        time: datetime,
        actor: Actor,
        payload: dict[str, Any],
        visibility: Visibility = "both",
        transaction_id: str | None = None,
        customer: str | None = None,
        mandate: str | None = None,
    ) -> AuditEvent:
        payload = to_jsonable(payload)
        with self._lock:
            row = self._conn.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (row[0] + 1, row[1]) if row else (1, GENESIS_HASH)
            event = AuditEvent(
                seq=seq,
                event_id=f"evt_{uuid.uuid4().hex[:20]}",
                time=time,
                type=type,
                transaction_id=transaction_id,
                customer=customer,
                actor=actor,
                mandate=mandate,
                visibility=visibility,
                payload=payload,
                payload_digest=payload_digest(payload),
                prev_hash=prev,
                hash="pending",
            )
            event = event.model_copy(update={"hash": entry_hash(prev, event.entry())})
            self._conn.execute(
                f"INSERT INTO audit_events ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.seq,
                    event.event_id,
                    event.time.isoformat(),
                    event.type,
                    event.transaction_id,
                    event.customer,
                    canonical(event.actor).decode(),
                    event.mandate,
                    event.visibility,
                    canonical(payload).decode(),
                    event.payload_digest,
                    event.prev_hash,
                    event.hash,
                ),
            )
            return event

    # ------------------------------------------------------------------ read

    @staticmethod
    def _row(row: tuple) -> AuditEvent:
        return AuditEvent(
            seq=row[0],
            event_id=row[1],
            time=datetime.fromisoformat(row[2]),
            type=row[3],
            transaction_id=row[4],
            customer=row[5],
            actor=Actor.model_validate(json.loads(row[6])),
            mandate=row[7],
            visibility=row[8],
            payload=json.loads(row[9]),
            payload_digest=row[10],
            prev_hash=row[11],
            hash=row[12],
        )

    def _query(self, sql: str, args: tuple = ()) -> list[AuditEvent]:
        return [self._row(r) for r in self._conn.execute(f"SELECT {_COLUMNS} FROM audit_events {sql}", args)]

    def head(self) -> AuditEvent | None:
        rows = self._query("ORDER BY seq DESC LIMIT 1")
        return rows[0] if rows else None

    def get(self, seq: int) -> AuditEvent | None:
        rows = self._query("WHERE seq = ?", (seq,))
        return rows[0] if rows else None

    def range(self, from_seq: int, to_seq: int) -> list[AuditEvent]:
        return self._query("WHERE seq BETWEEN ? AND ? ORDER BY seq", (from_seq, to_seq))

    def for_transaction(self, transaction_id: str) -> list[AuditEvent]:
        return self._query("WHERE transaction_id = ? ORDER BY seq", (transaction_id,))

    def of_type(self, type: str, after_seq: int = 0) -> list[AuditEvent]:
        return self._query("WHERE type = ? AND seq > ? ORDER BY seq", (type, after_seq))

    def first_checkpoint_at_or_after(self, seq: int) -> AuditEvent | None:
        """The earliest checkpoint whose signed head covers ``seq``.

        A checkpoint event itself is covered by the checkpoint that signs it,
        or, if it is the newest one, it is the anchor: we then look for the
        checkpoint covering the last non-checkpoint event before it.
        """
        target = seq
        while target > 0:
            event = self.get(target)
            if event is None or event.type != "chain.checkpoint":
                break
            target -= 1
        for ev in self._query("WHERE type = 'chain.checkpoint' AND seq > ? ORDER BY seq", (target,)):
            if ev.payload and ev.payload.get("headSeq", 0) >= target:
                return ev
        return None

    def transaction_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT transaction_id FROM audit_events WHERE type = 'request.received' ORDER BY seq"
        ).fetchall()
        return [r[0] for r in rows]
