"""Audit chain integrity (audit-log §4, §5, §8; acceptance tests AT09–AT14)."""

from __future__ import annotations

import sqlite3

import pytest

from app.audit import events as ev
from app.audit.events import Actor
from app.audit.verify import verify_links, verify_range
from app.audit.views import view_events

AGENT = Actor(kind="agent", id="agent:hotel-123-procurement-01")


def _transaction(audit, tx="req_1", customer="customer:HOTEL-123"):
    audit.append(ev.REQUEST_RECEIVED, transaction_id=tx, actor=AGENT, customer=customer, payload={"purpose": "quote_for_order"})
    audit.append(ev.UPSTREAM_QUERIED, transaction_id=tx, actor=ev.GATEWAY, customer=customer, payload={"endpoint": "availability", "productCount": 3})
    audit.append(ev.TRANSACTION_CLOSED, transaction_id=tx, actor=ev.SYSTEM, customer=customer, payload={"outcome": "ORDERED"})


def test_chain_verifies(audit, keys):
    _transaction(audit)
    head = audit.store.head()
    result = verify_range(audit.store, 1, head.seq, keys.jwks)
    assert result.ok, result.error
    assert result.checkpoint_seq is not None


def test_valio_only_types_get_valio_visibility(audit):
    _transaction(audit)
    queried = audit.store.of_type(ev.UPSTREAM_QUERIED)[0]
    assert queried.visibility == "valio"


def test_AT09_changed_payload_byte_is_detected(audit, keys, conn):
    _transaction(audit)
    conn.execute("DROP TRIGGER audit_events_no_update")  # simulate an attacker with raw DB access
    target = audit.store.of_type(ev.REQUEST_RECEIVED)[0].seq
    conn.execute(
        "UPDATE audit_events SET payload = replace(payload, 'quote_for_order', 'quote_for_ordeR') WHERE seq = ?", (target,)
    )
    result = verify_range(audit.store, 1, audit.store.head().seq, keys.jwks)
    assert not result.ok
    assert result.error_seq == target


def test_AT10_deleted_event_is_detected(audit, keys, conn):
    _transaction(audit)
    conn.execute("DROP TRIGGER audit_events_no_delete")
    conn.execute("DELETE FROM audit_events WHERE seq = 3")
    result = verify_range(audit.store, 1, audit.store.head().seq, keys.jwks)
    assert not result.ok


def test_AT14_update_and_delete_rejected_by_trigger(audit, conn):
    _transaction(audit)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_events SET type = 'x' WHERE seq = 1")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_events WHERE seq = 1")


def test_AT11_buyer_view_redacts_valio_events_and_still_verifies(audit, keys):
    _transaction(audit, tx="req_1", customer="customer:HOTEL-123")
    _transaction(audit, tx="req_2", customer="customer:OTHER")
    items, checkpoint = view_events(audit.store, "req_1", "buyer", "customer:HOTEL-123")
    queried = next(i for i in items if getattr(i, "type", None) == ev.UPSTREAM_QUERIED)
    assert queried.payload is None  # redacted stub
    result = verify_links(items, keys.jwks, checkpoint=checkpoint)
    assert result.ok, result.error


def test_buyer_view_hides_other_customers(audit):
    audit.append(ev.REQUEST_RECEIVED, transaction_id="req_1", actor=AGENT, customer="customer:HOTEL-123", payload={})
    audit.append(ev.REQUEST_RECEIVED, transaction_id="req_9", actor=AGENT, customer="customer:OTHER", payload={"secret": 1})
    audit.append(ev.TRANSACTION_CLOSED, transaction_id="req_1", actor=ev.SYSTEM, customer="customer:HOTEL-123", payload={})
    items, _ = view_events(audit.store, "req_1", "buyer", "customer:HOTEL-123")
    other_seq = audit.store.for_transaction("req_9")[0].seq
    other = [i for i in items if i.seq == other_seq]
    assert other and not hasattr(other[0], "payload")


def test_tampered_checkpoint_signature_is_detected(audit, keys):
    _transaction(audit)
    from app.trust.keys import GatewayKeys

    other_keys = GatewayKeys.ephemeral()
    other_keys.audit.kid = keys.audit.kid  # same kid, different key
    result = verify_range(audit.store, 1, audit.store.head().seq, other_keys.jwks)
    assert not result.ok
    assert "signature" in result.error
