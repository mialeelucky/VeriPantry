"""Signed offers (trust-protocol §6.1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.core.contracts import PlanItem
from app.core.jcs import digest
from app.trust.keys import Signer


def offer_valid_until(item: PlanItem, now: datetime, fallback_minutes: int, max_hours: int) -> datetime:
    """Valid until the order cut-off; a short window when the cut-off has passed or is unknown."""
    if item.closing_time is not None and item.closing_time > now:
        until = item.closing_time
    else:
        until = now + timedelta(minutes=fallback_minutes)
    return min(until, now + timedelta(hours=max_hours))


def build_offer(
    item: PlanItem,
    *,
    issuer: str,
    customer: str,
    agent: str,
    mandate_id: str | None,
    valid_until: datetime,
    tax_rate=None,
) -> dict[str, Any]:
    return {
        "offerId": f"off_{uuid.uuid4().hex[:12]}",
        "iss": issuer,
        "sub": customer,
        "aud": agent,
        "mandate": mandate_id,
        "productId": item.product_id,
        "quantity": {"value": item.sales_units, "salesUnit": item.sales_unit},
        "unitPrice": {"value": item.unit_price, "currency": "EUR", "vatExcluded": True},
        "taxRate": tax_rate,
        "fulfilment": {
            "on_time": "full", "on_time_partial": "partial", "quantity_unconfirmed": "unconfirmed",
        }.get(item.status, item.status),
        "availableDate": item.available_date,
        "closingTime": item.closing_time,
        "validUntil": valid_until,
    }


def sign_offer(signer: Signer, offer: dict[str, Any]) -> tuple[str, str]:
    jws = signer.sign(offer, typ="offer+jwt")
    return jws, digest(jws)
