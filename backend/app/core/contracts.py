"""Data contracts shared between modules.

These are the objects the design documents define and pass between layers:

* the standard purchase request   (fulfilment-and-substitution §2)
* plans and line results          (fulfilment-and-substitution §11, guardrails §3)

JSON uses camelCase, Python uses snake_case.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Unit = Literal["L", "KG", "PCS"]
Tier = Literal["exact", "S0", "S1", "S2", "S3"]
Strategy = Literal["exact", "split", "full_substitute", "multi_substitute", "later_delivery", "partial"]
ItemStatus = Literal[
    "on_time",
    "on_time_partial",
    "quantity_unconfirmed",
    "cutoff_passed",
    "late",
    "not_deliverable",
    "blocked",
    "no_price",
]
QuantityBasis = Literal["known", "ample", "unconfirmed"]
LineStatus = Literal["fulfilled", "substitution_proposed", "unfulfillable"]
AllergenState = Literal["contains", "may_contain", "free_from", "not_declared"]

# Plan flags consumed by the guardrail layer (fulfilment §12).
FLAG_SUBSTITUTION = "substitution"
FLAG_SPLIT = "split"
FLAG_LATER_DELIVERY = "later_delivery"
FLAG_PARTIAL = "partial"
FLAG_QUANTITY_UNCONFIRMED = "quantity_unconfirmed"
FLAG_CUTOFF_PASSED = "cutoff_passed"
FLAG_RELIABILITY_NO_DATA = "reliability_no_data"
FLAG_CONTENT_UNCERTAIN = "content_uncertain"
FLAG_OVERFILL = "overfill"


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# --------------------------------------------------------------------------- request


class Quantity(Model):
    value: Decimal = Field(gt=0)
    unit: Unit


class Spec(Model):
    query: str | None = None
    category: str | None = None
    required_attributes: list[str] = Field(default_factory=list)
    excluded_allergens: list[str] = Field(default_factory=list)
    preferred_attributes: list[str] = Field(default_factory=list)


class Weights(Model):
    fit: float = 0.45
    cost: float = 0.30
    reliability: float = 0.15
    sustainability: float = 0.10


class Preferences(Model):
    weights: Weights = Field(default_factory=Weights)
    allow_split: bool = True
    allow_later_delivery: bool = True


class RequestLine(Model):
    line_id: str
    product_id: str | None = None
    spec: Spec = Field(default_factory=Spec)
    quantity: Quantity
    max_unit_price: Decimal | None = None  # per request unit, VAT excluded (guardrails GR-M3)


class PurchaseRequest(Model):
    request_id: str
    customer: str
    deliver_by: date
    lines: list[RequestLine] = Field(min_length=1)
    preferences: Preferences = Field(default_factory=Preferences)


# --------------------------------------------------------------------------- plans


class Rationale(Model):
    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class Deviation(Model):
    attribute: str
    requested: Any = None
    proposed: Any = None
    share: Decimal | None = None  # share of the line quantity affected


class PlanItem(Model):
    product_id: str
    name: str
    brand: str | None = None
    category: str
    tier: Tier
    sim: float
    status: ItemStatus
    quantity_basis: QuantityBasis
    sales_units: Decimal
    sales_unit: str
    quantity: Quantity
    content_per_sales_unit: Decimal
    available_date: date | None
    closing_time: datetime | None
    unit_price: Decimal
    line_total: Decimal
    unit_cost: Decimal  # per request unit (L / KG / PCS)
    reliability: float | None
    carbon_kg_per_kg: Decimal | None
    allergens: dict[str, AllergenState] = Field(default_factory=dict)
    claims: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    confirmed_sales_units: Decimal | None = None
    flags: list[str] = Field(default_factory=list)
    deviations: list[Deviation] = Field(default_factory=list)
    offer_id: str | None = None
    offer_valid_until: datetime | None = None


class Scores(Model):
    fit: float
    cost: float
    reliability: float
    sustainability: float
    total: float


class Plan(Model):
    line_id: str
    rank: int | None = None
    label: Literal["best", "second", "third", "optimal"] | None = None
    strategy: Strategy
    items: list[PlanItem]
    total: Decimal
    currency: str = "EUR"
    covered: Quantity
    coverage: Decimal  # 0..1
    complete: bool
    on_time: bool
    scores: Scores
    flags: list[str] = Field(default_factory=list)
    deviations: list[Deviation] = Field(default_factory=list)
    rationale: list[Rationale] = Field(default_factory=list)

    @property
    def product_ids(self) -> list[str]:
        return [i.product_id for i in self.items]


class NotPresented(Model):
    strategy: Strategy
    product_ids: list[str]
    total: Decimal
    score: float
    reason: str


class CandidateCounts(Model):
    retrieved: int = 0
    after_hard_filter: int = 0
    shortlisted: int = 0
    feasible: int = 0
    substitute_pool: int = 0


class LineReason(Model):
    code: str
    requested: Decimal | None = None
    available_on_time: Decimal | None = None
    unit: Unit | None = None


class LineResult(Model):
    line_id: str
    status: LineStatus
    reason: LineReason | None = None
    plans: list[Plan] = Field(default_factory=list)
    not_presented: list[NotPresented] = Field(default_factory=list)
    candidate_counts: CandidateCounts = Field(default_factory=CandidateCounts)
    reference_unit_cost: Decimal | None = None  # guardrails GR-M3


class FulfilmentResult(Model):
    request_id: str
    evaluated_at: datetime
    lines: list[LineResult]
