"""Quantity normalisation (fulfilment §4)."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.catalog.models import Product
from app.core.contracts import FLAG_CONTENT_UNCERTAIN, Unit
from app.upstream.client import Price

CONTENT_TOLERANCE = Decimal("0.05")  # §4.1 step 3
OVERFILL_PCT = Decimal("0.05")  # §4.2


def lot_step(product: Product) -> Decimal:
    """Order step in sales units.

    The data lists ``allowedLotSize = 0.01`` even for countable units such as
    cartons. Fractions of a carton cannot be delivered, so countable sales
    units are rounded to whole units (still a multiple of the lot size).
    """
    step = product.allowed_lot_size
    if product.sales_unit in ("KG", "L"):
        return step
    return max(step, Decimal("1"))


def ceil_to(value: Decimal, step: Decimal) -> Decimal:
    return ((value / step).to_integral_value(rounding=ROUND_CEILING) * step).quantize(step)


def floor_to(value: Decimal, step: Decimal) -> Decimal:
    return ((value / step).to_integral_value(rounding=ROUND_FLOOR) * step).quantize(step)


def static_content(product: Product, unit: Unit) -> Decimal | None:
    if unit == "PCS":
        return product.pcs_per_sales_unit
    return product.sales_content.get(unit)


def resolve_content(product: Product, unit: Unit, price: Price | None) -> tuple[Decimal | None, list[str]]:
    """Content of one sales unit in the request unit, cross-checked with the price ratio."""
    static = static_content(product, unit)
    live = None
    if (
        price is not None
        and unit != "PCS"
        and price.comparison_unit == unit
        and price.comparison_price
        and price.unit_price
    ):
        live = price.unit_price / price.comparison_price
    if static:
        if live and abs(live - static) / static > CONTENT_TOLERANCE:
            return static, [FLAG_CONTENT_UNCERTAIN]
        return static, []
    if live:
        return live.quantize(Decimal("0.001")), []
    return None, []


def units_for(required: Decimal, content: Decimal, step: Decimal) -> Decimal:
    return ceil_to(required / content, step)


def overfill_tolerance(required: Decimal, content: Decimal) -> Decimal:
    return max(required * OVERFILL_PCT, content)
