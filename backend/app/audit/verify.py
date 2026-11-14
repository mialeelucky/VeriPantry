"""Chain verification (audit-log §8)."""

from __future__ import annotations

from typing import Any

import jwt

from app.audit import events as ev
from app.audit.chain import GENESIS_HASH, entry_hash, payload_digest
from app.audit.events import AuditEvent, OpaqueLink
from app.core.contracts import Model
from app.trust.keys import verify_jws


class VerifyResult(Model):
    ok: bool
    from_seq: int | None = None
    to_seq: int | None = None
    checked: int = 0
    error_seq: int | None = None
    error: str | None = None
    checkpoint_seq: int | None = None
    checkpoint_kid: str | None = None


def verify_links(
    items: list[AuditEvent | OpaqueLink],
    jwks: list[dict[str, Any]],
    expected_prev: str | None = None,
    checkpoint: AuditEvent | None = None,
) -> VerifyResult:
    """Verify a contiguous range of the chain.

    Full events are recomputed. Redacted events (payload None) are recomputed
    from their envelope. Opaque links (other customers' events) are only
    checked for continuity.
    """
    if not items:
        return VerifyResult(ok=True, checked=0)
    result = VerifyResult(ok=True, from_seq=items[0].seq, to_seq=items[-1].seq)
    prev = expected_prev if expected_prev is not None else (GENESIS_HASH if items[0].seq == 1 else None)
    last_seq = None
    for item in items:
        if last_seq is not None and item.seq != last_seq + 1:
            return result.model_copy(update={"ok": False, "error_seq": item.seq, "error": "gap in sequence"})
        if prev is not None and item.prev_hash != prev:
            return result.model_copy(update={"ok": False, "error_seq": item.seq, "error": "prevHash does not match previous hash"})
        if isinstance(item, AuditEvent):
            if item.payload is not None and payload_digest(item.payload) != item.payload_digest:
                return result.model_copy(update={"ok": False, "error_seq": item.seq, "error": "payload does not match payloadDigest"})
            if entry_hash(item.prev_hash, item.entry()) != item.hash:
                return result.model_copy(update={"ok": False, "error_seq": item.seq, "error": "hash does not match entry"})
        prev, last_seq = item.hash, item.seq
        result.checked += 1

    if checkpoint is not None and checkpoint.payload:
        try:
            claims = verify_jws(checkpoint.payload["jws"], jwks)
        except jwt.InvalidTokenError as exc:
            return result.model_copy(update={"ok": False, "error_seq": checkpoint.seq, "error": f"checkpoint signature invalid: {exc}"})
        if claims.get("headSeq") != checkpoint.payload["headSeq"] or claims.get("headHash") != checkpoint.payload["headHash"]:
            return result.model_copy(update={"ok": False, "error_seq": checkpoint.seq, "error": "checkpoint payload does not match signature"})
        head = next((i for i in items if i.seq == claims["headSeq"]), None)
        if head is not None and head.hash != claims["headHash"]:
            return result.model_copy(update={"ok": False, "error_seq": head.seq, "error": "chain head does not match signed checkpoint"})
        result.checkpoint_seq = checkpoint.seq
        result.checkpoint_kid = jwt.get_unverified_header(checkpoint.payload["jws"]).get("kid")
    return result


def verify_range(store, from_seq: int, to_seq: int, jwks: list[dict[str, Any]]) -> VerifyResult:
    """Full verification of a range, including the covering checkpoint (Valio view)."""
    checkpoint = store.first_checkpoint_at_or_after(to_seq)
    end = checkpoint.payload["headSeq"] if checkpoint else to_seq
    items = store.range(from_seq, max(end, to_seq))
    prev = None
    if from_seq > 1:
        before = store.get(from_seq - 1)
        prev = before.hash if before else None
    result = verify_links(items, jwks, expected_prev=prev, checkpoint=checkpoint)
    if result.ok and checkpoint is None:
        result.error = "no checkpoint covers this range yet"
    return result
