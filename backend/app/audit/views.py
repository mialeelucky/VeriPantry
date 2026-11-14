"""Buyer and Valio views of one chain (audit-log §5)."""

from __future__ import annotations

from typing import Literal

from app.audit import events as ev
from app.audit.events import AuditEvent, OpaqueLink
from app.audit.store import AuditStore

View = Literal["buyer", "valio"]


def transaction_range(store: AuditStore, transaction_id: str) -> tuple[list[AuditEvent], AuditEvent | None]:
    """All chain events from the transaction's first event up to its covering checkpoint."""
    own = store.for_transaction(transaction_id)
    if not own:
        return [], None
    checkpoint = store.first_checkpoint_at_or_after(own[-1].seq)
    end = checkpoint.payload["headSeq"] if checkpoint else own[-1].seq
    return store.range(own[0].seq, end), checkpoint


def present(event: AuditEvent, view: View, customer: str | None) -> AuditEvent | OpaqueLink:
    """Return what a viewer may see of one event."""
    if view == "valio":
        return event
    if event.type == ev.CHAIN_CHECKPOINT:
        return event  # checkpoints are public statements
    if event.customer != customer:
        return OpaqueLink(seq=event.seq, prev_hash=event.prev_hash, hash=event.hash)
    if event.visibility == "valio":
        return event.model_copy(update={"payload": None})  # redacted stub
    return event


def view_events(store: AuditStore, transaction_id: str, view: View, customer: str | None):
    items, checkpoint = transaction_range(store, transaction_id)
    return [present(e, view, customer) for e in items], checkpoint
