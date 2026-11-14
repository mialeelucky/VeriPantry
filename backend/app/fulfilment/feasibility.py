"""Feasibility status per product (fulfilment §3.2, §7.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.catalog.models import Product
from app.core.contracts import (
    FLAG_CUTOFF_PASSED,
    FLAG_QUANTITY_UNCONFIRMED,
    FLAG_RELIABILITY_NO_DATA,
    ItemStatus,
    QuantityBasis,
    Unit,
)
from app.fulfilment.quantity import lot_step, resolve_content, units_for
from app.upstream.client import Availability, Price

AMPLE_THRESHOLD = Decimal("1e8")  # sentinel stock values (§3.2)
UNCONFIRMED_AMOUNT = Decimal("999999")  # supplier-direct placeholder

ON_TIME_STATUSES = frozenset({"on_time", "on_time_partial", "quantity_unconfirmed"})
LATER_STATUSES = frozenset({"late", "cutoff_passed"})


@dataclass
class Assessment:
    product: Product
    status: ItemStatus
    basis: QuantityBasis = "known"
    confirmed_sales_units: Decimal | None = None
    available_date: date | None = None
    closing_time: datetime | None = None
    unit_price: Decimal | None = None
    content: Decimal | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def usable_on_time(self) -> bool:
        return self.status in ON_TIME_STATUSES

    @property
    def usable_later(self) -> bool:
        return self.status in LATER_STATUSES and self.unit_price is not None and self.content is not None

    @property
    def unit_cost(self) -> Decimal:
        assert self.unit_price is not None and self.content
        return self.unit_price / self.content

    def can_cover(self, required: Decimal) -> bool:
        """Can this product alone deliver ``required`` (in request units)?"""
        if self.confirmed_sales_units is None:
            return True  # ample or unconfirmed
        return self.confirmed_sales_units * self.content >= required


def assess(
    product: Product,
    availability: Availability | None,
    price: Price | None,
    unit: Unit,
    required: Decimal,
    deliver_by: date,
    now: datetime,
    cutoff_policy: str = "strict",
) -> Assessment:
    content, content_flags = resolve_content(product, unit, price)
    flags = list(content_flags)
    if product.reliability is None:
        flags.append(FLAG_RELIABILITY_NO_DATA)

    def result(status: ItemStatus, **kw) -> Assessment:
        return Assessment(product=product, status=status, content=content, flags=flags, **kw)

    if price is None or price.error or price.unit_price is None:
        return result("no_price")
    common = {"unit_price": price.unit_price}
    if availability is None:
        return result("not_deliverable", **common)
    common["closing_time"] = availability.closing_time
    if availability.sales_block or availability.line_sales_block:
        return result("blocked", **common)
    if (
        not availability.has_line
        or availability.available_amount is None
        or availability.available_amount <= 0
        or availability.available_date is None
    ):
        return result("not_deliverable", **common)
    if content is None:
        return result("not_deliverable", **common)  # cannot be expressed in the request unit

    amount = availability.available_amount
    if amount >= AMPLE_THRESHOLD:
        basis, confirmed = "ample", None
    elif availability.logistic_model == "Terminal" and amount == UNCONFIRMED_AMOUNT:
        basis, confirmed = "unconfirmed", None
        flags.append(FLAG_QUANTITY_UNCONFIRMED)
    else:
        basis, confirmed = "known", amount
    common.update(basis=basis, confirmed_sales_units=confirmed, available_date=availability.available_date)

    if availability.closing_time is not None and availability.closing_time < now:
        flags.append(FLAG_CUTOFF_PASSED)
        if cutoff_policy == "strict":
            return result("cutoff_passed", **common)
    if availability.available_date > deliver_by:
        return result("late", **common)
    if basis == "unconfirmed":
        return result("quantity_unconfirmed", **common)
    needed = units_for(required, content, lot_step(product))
    if confirmed is not None and confirmed < needed:
        return result("on_time_partial", **common)
    return result("on_time", **common)
