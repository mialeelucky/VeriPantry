"""Approval notifications (frontend.md §4.4, guardrails §8.2).

The request finds the approver: every person of the customer whose role is at
least the required role is told, by web push to their installed app and/or by
the customer's webhook. Every send, failure and "nobody to tell" is an audit
event (``notification.sent``). Notifications carry no tokens and no internal
(tier T2) data, only what is needed to decide whether to open the request.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from app.guardrails.models import ROLE_RANK
from app.trust.keys import b64url
from app.trust.registry import HumanEntry, Registry

SHORT_REASONS: dict[str, Callable[[dict], str]] = {
    "spend_over_auto_limit": lambda r: f"above your agent's {_eur(r.get('limit'))} limit",
    "spend_over_approver_limit": lambda r: f"above the {_eur(r.get('limit'))} approver limit",
    "period_budget_exceeded": lambda r: "over this period's budget",
    "inflexible_deviation": lambda r: f"{r.get('observed', 'attribute')} change",
    "low_similarity": lambda r: "a less similar substitute",
    "substitution_tier": lambda r: "a product from another category",
    "substitution_needs_approval": lambda r: "a substitute product",
    "quantity_over_mandate": lambda r: "more than the agent's quantity limit",
    "partial_fulfilment": lambda r: "only part of the quantity",
    "later_delivery": lambda r: "arrives after the requested date",
    "cutoff_passed": lambda r: "the order cut-off has passed",
    "category_out_of_scope": lambda r: "outside the agent's categories",
    "unit_price_increase": lambda r: "price above the reference",
    "unconfirmed_low_reliability": lambda r: "unconfirmed supplier stock",
    "unusual_order_velocity": lambda r: "an unusual number of orders",
    "beyond_delivery_horizon": lambda r: "delivery far in the future",
}


def _eur(value: Any) -> str:
    try:
        return f"€{Decimal(str(value)):,.0f}"
    except Exception:
        return "the"


def short_reason(reasons: list[dict]) -> str:
    for r in reasons:
        fn = SHORT_REASONS.get(r.get("code", ""))
        if fn:
            return fn(r)
    return reasons[0]["code"].replace("_", " ") if reasons else "needs a decision"


def build_message(kind: str, approval: dict, decided_by: str | None = None) -> dict[str, Any]:
    """The notification payload: same fields for web push and webhook."""
    total = f"€{Decimal(str(approval.get('total', 0))):,.2f}"
    deadline = datetime.fromisoformat(approval["deadline"]).strftime("%H:%M")
    reasons = list(approval.get("orderReasons") or [])
    for line in approval.get("lines", []):
        rec = next((p for p in line["plans"] if p["rank"] == line["recommendedRank"]), None)
        if rec:
            reasons += rec["guardrail"]["reasons"]
    if kind == "request":
        title = f"Approval needed · {total}"
        body = f"{approval.get('title', 'Purchase request')} · {short_reason(reasons)} · expires {deadline}"
    elif kind == "reminder":
        title = f"Reminder: approval expires at {deadline}"
        body = f"{approval.get('title', 'Purchase request')} · {total} · {short_reason(reasons)}"
    else:
        title = f"Approval {decided_by or 'closed'}"
        body = f"{approval.get('title', 'Purchase request')} · {total} · no action needed"
    return {
        "kind": kind,
        "approvalId": approval["approvalId"],
        "title": title,
        "body": body,
        "url": f"/approvals/{approval['approvalId']}",
    }


class PushSender(Protocol):
    def __call__(self, subscription: dict, payload: dict) -> None: ...


class WebPushSender:
    """Standard Web Push with VAPID (RFC 8030, RFC 8292)."""

    def __init__(self, key_path: Path, subject: str):
        from py_vapid import Vapid

        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            vapid = Vapid()
            vapid.generate_keys()
            vapid.save_key(str(key_path))
        self._key_path = str(key_path)
        self._subject = subject
        vapid = Vapid.from_file(self._key_path)
        from cryptography.hazmat.primitives import serialization

        raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.public_key = b64url(raw)

    def __call__(self, subscription: dict, payload: dict) -> None:
        from pywebpush import webpush

        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=self._key_path,
            vapid_claims={"sub": self._subject},
            timeout=10,
        )


def post_webhook(url: str, payload: dict) -> None:
    with httpx.Client(timeout=5, transport=httpx.HTTPTransport(local_address="0.0.0.0")) as http:
        http.post(url, json=payload).raise_for_status()


class Notifier:
    def __init__(
        self,
        registry: Registry,
        subscriptions: Callable[[str], list[dict]],
        log: Callable[[str, dict], None],
        push: PushSender | None,
        webhook: Callable[[str, dict], None] = post_webhook,
        run_async: bool = True,
    ):
        self.registry = registry
        self._subscriptions = subscriptions  # person id -> push subscriptions
        self._log = log  # (transaction id, payload) -> audit event
        self._push = push
        self._webhook = webhook
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notify") if run_async else None
        self._lock = threading.Lock()

    def recipients(self, customer: str, required_role: str, exclude: str | None = None) -> list[HumanEntry]:
        need = ROLE_RANK.get(required_role, 1)
        return [
            h for h in self.registry.humans
            if h.kind == "approver" and h.customer == customer and ROLE_RANK.get(h.role or "", 0) >= need and h.id != exclude
        ]

    def send(self, kind: str, transaction_id: str, customer: str, approval: dict, decided_by: str | None = None, exclude: str | None = None) -> None:
        job = lambda: self._send(kind, transaction_id, customer, approval, decided_by, exclude)  # noqa: E731
        if self._pool:
            self._pool.submit(job)
        else:
            job()

    def _send(self, kind, transaction_id, customer, approval, decided_by, exclude) -> None:
        message = build_message(kind, approval, decided_by)
        people = self.recipients(customer, approval["requiredRole"], exclude)
        base = {"approvalId": approval["approvalId"], "kind": kind}
        reachable = False  # somebody had a channel, whether or not delivery worked

        if self._push is not None:
            sent, failed = [], []
            for person in people:
                subs = self._subscriptions(person.id)
                if not subs:
                    continue
                reachable = True
                ok = False
                for sub in subs:
                    try:
                        self._push(sub, message)
                        ok = True
                    except Exception:
                        pass
                (sent if ok else failed).append(person.id)
            if sent:
                self._log(transaction_id, {**base, "channel": "web_push", "recipients": sent, "outcome": "sent"})
            if failed:
                self._log(transaction_id, {**base, "channel": "web_push", "recipients": failed, "outcome": "failed"})

        entry = self.registry.customer(customer)
        if entry and entry.webhook_url:
            reachable = True
            try:
                self._webhook(entry.webhook_url, {**message, "customer": customer})
                self._log(transaction_id, {**base, "channel": "webhook", "recipients": [customer], "outcome": "sent"})
            except Exception:
                self._log(transaction_id, {**base, "channel": "webhook", "recipients": [customer], "outcome": "failed"})

        if not reachable and kind != "decided":
            self._log(transaction_id, {**base, "channel": None, "recipients": [p.id for p in people], "outcome": "no_recipient"})
