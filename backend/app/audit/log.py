"""The single entry point every module uses to write audit events (audit-log §11)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.audit import events as ev
from app.audit.events import Actor, AuditEvent, AuditRef, Visibility
from app.audit.store import AuditStore
from app.core.clock import Clock
from app.trust.keys import Signer


class AuditLog:
    def __init__(
        self,
        store: AuditStore,
        clock: Clock,
        signer: Signer | None = None,
        checkpoint_every_events: int = 100,
        checkpoint_every_minutes: int = 10,
    ):
        self.store = store
        self.clock = clock
        self.signer = signer
        self._every_events = checkpoint_every_events
        self._every = timedelta(minutes=checkpoint_every_minutes)
        last = store.of_type(ev.CHAIN_CHECKPOINT)
        self._last_checkpoint = last[-1] if last else None

    def append(
        self,
        type: str,
        *,
        transaction_id: str | None,
        actor: Actor,
        payload: dict[str, Any],
        visibility: Visibility | None = None,
        customer: str | None = None,
        mandate: str | None = None,
    ) -> AuditRef:
        if visibility is None:
            visibility = "valio" if type in ev.VALIO_ONLY_TYPES else "both"
        event = self.store.append(
            type=type,
            time=self.clock.now(),
            actor=actor,
            payload=payload,
            visibility=visibility,
            transaction_id=transaction_id,
            customer=customer,
            mandate=mandate,
        )
        self._maybe_checkpoint(event, force=type == ev.TRANSACTION_CLOSED)
        return event.ref

    # ------------------------------------------------------------------ checkpoints (§4.3)

    def _maybe_checkpoint(self, event: AuditEvent, force: bool) -> None:
        if self.signer is None:
            return
        last = self._last_checkpoint
        since = event.seq - (last.seq if last else 0)
        due_by_count = since >= self._every_events
        due_by_time = last is not None and event.time - last.time >= self._every and since > 0
        if force or due_by_count or due_by_time:
            self.checkpoint()

    def checkpoint(self) -> AuditRef | None:
        if self.signer is None:
            return None
        head = self.store.head()
        if head is None:
            return None
        statement = {"headSeq": head.seq, "headHash": head.hash, "iat": int(self.clock.now().timestamp())}
        jws = self.signer.sign(statement, typ="audit-checkpoint+jwt")
        event = self.store.append(
            type=ev.CHAIN_CHECKPOINT,
            time=self.clock.now(),
            actor=ev.SYSTEM,
            payload={"headSeq": head.seq, "headHash": head.hash, "jws": jws},
        )
        self._last_checkpoint = event
        return event.ref
