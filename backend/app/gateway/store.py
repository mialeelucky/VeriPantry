"""Gateway working state: transactions, approvals, orders, offers, search sessions.

Unlike the audit log these rows change state; the audit log is the immutable
record of every change (audit-log L4).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.jcs import to_jsonable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, customer TEXT NOT NULL, agent TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, customer TEXT NOT NULL, state TEXT NOT NULL,
    required_role TEXT NOT NULL, deadline TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, customer TEXT NOT NULL, total TEXT NOT NULL,
    approval TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, valid_until TEXT NOT NULL, jws TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_sessions (
    id TEXT PRIMARY KEY, mandate_id TEXT NOT NULL, product_ids TEXT NOT NULL, expires_at TEXT NOT NULL
);
"""

TERMINAL_STATES = frozenset({"ORDERED", "DENIED", "REJECTED", "EXPIRED", "UNFULFILLABLE", "SUPERSEDED", "FAILED"})


def _dump(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


class GatewayStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()
        conn.executescript(_SCHEMA)

    def _exec(self, sql: str, args: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, args)

    # ------------------------------------------------------------------ transactions

    def create_transaction(self, tx_id: str, customer: str, agent: str, now: datetime, data: dict) -> None:
        self._exec(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?)",
            (tx_id, customer, agent, "OPEN", now.isoformat(), now.isoformat(), _dump(data)),
        )

    def get_transaction(self, tx_id: str) -> dict | None:
        row = self._exec("SELECT id, customer, agent, state, created_at, updated_at, data FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "customer": row[1], "agent": row[2], "state": row[3], "created_at": row[4], "updated_at": row[5], "data": json.loads(row[6])}

    def update_transaction(self, tx_id: str, now: datetime, state: str | None = None, data: dict | None = None) -> None:
        current = self.get_transaction(tx_id)
        self._exec(
            "UPDATE transactions SET state = ?, updated_at = ?, data = ? WHERE id = ?",
            (state or current["state"], now.isoformat(), _dump(data if data is not None else current["data"]), tx_id),
        )

    def transactions(self, customer: str | None = None) -> list[dict]:
        sql, args = "SELECT id FROM transactions", ()
        if customer:
            sql, args = sql + " WHERE customer = ?", (customer,)
        return [self.get_transaction(r[0]) for r in self._exec(sql + " ORDER BY created_at", args).fetchall()]

    # ------------------------------------------------------------------ approvals

    def create_approval(self, ap_id: str, tx_id: str, customer: str, role: str, deadline: datetime, now: datetime, data: dict) -> None:
        self._exec(
            "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)",
            (ap_id, tx_id, customer, "PENDING", role, deadline.isoformat(), now.isoformat(), _dump(data)),
        )

    def get_approval(self, ap_id: str) -> dict | None:
        row = self._exec(
            "SELECT id, transaction_id, customer, state, required_role, deadline, created_at, data FROM approvals WHERE id = ?", (ap_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "transaction_id": row[1], "customer": row[2], "state": row[3], "required_role": row[4],
            "deadline": datetime.fromisoformat(row[5]), "created_at": row[6], "data": json.loads(row[7]),
        }

    def set_approval_state(self, ap_id: str, state: str) -> None:
        self._exec("UPDATE approvals SET state = ? WHERE id = ?", (state, ap_id))

    def approvals(self, customer: str | None = None, state: str | None = None) -> list[dict]:
        clauses, args = [], []
        if customer:
            clauses.append("customer = ?")
            args.append(customer)
        if state:
            clauses.append("state = ?")
            args.append(state)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._exec(f"SELECT id FROM approvals{where} ORDER BY created_at", tuple(args)).fetchall()
        return [self.get_approval(r[0]) for r in rows]

    # ------------------------------------------------------------------ orders

    def create_order(self, order_id: str, tx_id: str, customer: str, total: Decimal, approval: str, now: datetime, data: dict) -> None:
        self._exec("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", (order_id, tx_id, customer, str(total), approval, now.isoformat(), _dump(data)))

    def orders_since(self, customer: str, since: datetime) -> list[dict]:
        rows = self._exec(
            "SELECT id, total, approval, created_at FROM orders WHERE customer = ? AND created_at >= ?", (customer, since.isoformat())
        ).fetchall()
        return [{"id": r[0], "total": Decimal(r[1]), "approval": r[2], "created_at": r[3]} for r in rows]

    def order_for_transaction(self, tx_id: str) -> dict | None:
        row = self._exec("SELECT id, data FROM orders WHERE transaction_id = ?", (tx_id,)).fetchone()
        return {"id": row[0], **json.loads(row[1])} if row else None

    # ------------------------------------------------------------------ offers and search sessions

    def save_offer(self, offer_id: str, tx_id: str, valid_until: datetime, jws: str, payload: dict) -> None:
        self._exec("INSERT INTO offers VALUES (?,?,?,?,?)", (offer_id, tx_id, valid_until.isoformat(), jws, _dump(payload)))

    def offers_for(self, tx_id: str) -> dict[str, str]:
        return {r[0]: r[1] for r in self._exec("SELECT id, jws FROM offers WHERE transaction_id = ?", (tx_id,)).fetchall()}

    def save_search(self, search_id: str, mandate_id: str, product_ids: list[str], expires_at: datetime) -> None:
        self._exec("INSERT INTO search_sessions VALUES (?,?,?,?)", (search_id, mandate_id, json.dumps(product_ids), expires_at.isoformat()))

    def get_search(self, search_id: str) -> dict | None:
        row = self._exec("SELECT mandate_id, product_ids, expires_at FROM search_sessions WHERE id = ?", (search_id,)).fetchone()
        if not row:
            return None
        return {"mandate_id": row[0], "product_ids": json.loads(row[1]), "expires_at": datetime.fromisoformat(row[2])}
