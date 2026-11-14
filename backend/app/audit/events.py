"""Audit event envelope and event types (audit-log §3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.core.contracts import Model

Visibility = Literal["both", "valio"]
ActorKind = Literal["agent", "human", "gateway", "system"]

# Event types (audit-log §3.2). Names shared with guardrails §10 are unchanged.
AUTH_TOKEN_ISSUED = "auth.token_issued"
AUTH_DENIED = "auth.denied"
REQUEST_RECEIVED = "request.received"
CATALOG_SEARCHED = "catalog.searched"
UPSTREAM_QUERIED = "upstream.queried"
DATA_DISCLOSED = "data.disclosed"
OFFER_ISSUED = "offer.issued"
FULFILMENT_COMPLETED = "fulfilment.completed"
GUARDRAIL_EVALUATED = "guardrail.evaluated"
PLAN_SELECTED = "plan.selected"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
APPROVAL_EXPIRED = "approval.expired"
APPROVAL_SUPERSEDED = "approval.superseded"
REQUOTE_STARTED = "requote.started"
ORDER_SUBMITTED = "order.submitted"
ORDER_FAILED = "order.failed"
TRANSACTION_CLOSED = "transaction.closed"
CHAIN_CHECKPOINT = "chain.checkpoint"
REPORT_FAILED = "report.failed"

VALIO_ONLY_TYPES = frozenset({UPSTREAM_QUERIED, DATA_DISCLOSED})

# Terminal outcomes (audit-log §6.1).
OUTCOMES = ("ORDERED", "DENIED", "REJECTED", "EXPIRED", "UNFULFILLABLE", "SUPERSEDED", "FAILED")


class Actor(Model):
    kind: ActorKind
    id: str
    role: str | None = None


SYSTEM = Actor(kind="system", id="veripantry")
GATEWAY = Actor(kind="gateway", id="veripantry-gateway")


class AuditRef(Model):
    seq: int
    hash: str


class AuditEvent(Model):
    seq: int
    event_id: str
    time: datetime
    type: str
    transaction_id: str | None = None
    customer: str | None = None
    actor: Actor
    mandate: str | None = None
    visibility: Visibility = "both"
    payload: dict[str, Any] | None = None  # None when redacted (audit-log §5)
    payload_digest: str
    prev_hash: str
    hash: str

    def entry(self) -> dict[str, Any]:
        """The hashed part of the envelope: everything except payload and hash (§4.1)."""
        return {
            "seq": self.seq,
            "eventId": self.event_id,
            "time": self.time,
            "type": self.type,
            "transactionId": self.transaction_id,
            "customer": self.customer,
            "actor": self.actor,
            "mandate": self.mandate,
            "visibility": self.visibility,
            "payloadDigest": self.payload_digest,
            "prevHash": self.prev_hash,
        }

    @property
    def ref(self) -> AuditRef:
        return AuditRef(seq=self.seq, hash=self.hash)


class OpaqueLink(Model):
    """Another customer's event inside a verified range: only the chain link is shown."""

    seq: int
    prev_hash: str
    hash: str
