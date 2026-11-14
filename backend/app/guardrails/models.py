"""Guardrail policy, inputs and decisions (guardrails §2–§4, §9)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from app.core.contracts import Model

Outcome = Literal["ALLOW", "ESCALATE", "DENY"]
Role = Literal["approver", "admin"]
ROLE_RANK: dict[str, int] = {"approver": 1, "admin": 2}


# --------------------------------------------------------------------------- policy (§4)


class SpendPolicy(Model):
    auto_limit_eur: Decimal = Decimal("2000")
    approver_limit_eur: Decimal = Decimal("5000")
    period_budget_eur: Decimal | None = None
    max_unit_price_increase_pct: Decimal = Decimal("10")


class QuantityPolicy(Model):
    max_qty_per_line: Decimal | None = None
    max_auto_products_per_line: int = 2


class DeliveryPolicy(Model):
    deliver_within_days: int = 14
    min_reliability_for_unconfirmed: float = 0.95


class SubstitutionPolicy(Model):
    auto_substitution: bool = True
    auto_tiers: list[str] = Field(default_factory=lambda: ["S0", "S1"])
    min_similarity: float = 0.80
    flexible_attributes: list[str] = Field(default_factory=lambda: ["brand", "pack_size"])


class ScopePolicy(Model):
    categories: list[str] | None = None


class SelectionPolicy(Model):
    tolerance_score: float = 0.05


class VelocityPolicy(Model):
    max_auto_orders_per_day: int = 10


class ApprovalPolicy(Model):
    deadline_buffer_minutes: int = 30
    max_requote_attempts: int = 1


class Policy(Model):
    """Unknown fields are rejected, so a typo cannot silently disable a rule (§13)."""

    policy_id: str = "default"
    version: int = 1
    spend: SpendPolicy = Field(default_factory=SpendPolicy)
    quantity: QuantityPolicy = Field(default_factory=QuantityPolicy)
    delivery: DeliveryPolicy = Field(default_factory=DeliveryPolicy)
    substitution: SubstitutionPolicy = Field(default_factory=SubstitutionPolicy)
    scope: ScopePolicy = Field(default_factory=ScopePolicy)
    selection: SelectionPolicy = Field(default_factory=SelectionPolicy)
    velocity: VelocityPolicy = Field(default_factory=VelocityPolicy)
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)

    def with_mandate_limits(self, limits: dict[str, Any]) -> "Policy":
        """Mandate limits override the policy: the mandate is the signed statement of authority."""
        p = self.model_copy(deep=True)
        if limits.get("maxOrderValueEUR") is not None:
            p.spend.auto_limit_eur = Decimal(str(limits["maxOrderValueEUR"]))
        if limits.get("maxQtyPerLine") is not None:
            p.quantity.max_qty_per_line = Decimal(str(limits["maxQtyPerLine"]))
        if limits.get("deliverWithinDays") is not None:
            p.delivery.deliver_within_days = int(limits["deliverWithinDays"])
        if limits.get("categories") is not None:
            p.scope.categories = list(limits["categories"])
        return p


# --------------------------------------------------------------------------- inputs (§3)


class MandateInfo(Model):
    """A mandate as verified by the gateway (trust-protocol §4.2)."""

    id: str
    customer: str
    agent: str
    expires_at: datetime
    signature_valid: bool = True
    revoked: bool = False
    actions: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)


class Context(Model):
    now: datetime
    auto_orders_last_24h: int = 0
    period_spend_eur: Decimal = Decimal("0")
    approver_role: Role | None = None  # set when re-evaluating after a human approval (§8.3)


# --------------------------------------------------------------------------- outputs (§9)


class RuleResult(Model):
    rule: str
    scope: Literal["order", "line", "item"]
    outcome: Outcome
    role: Role | None = None
    code: str
    message: str
    line_id: str | None = None
    product_id: str | None = None
    observed: Any = None
    limit: Any = None
    unit: str | None = None
    remedy: str | None = None
    satisfied_by_approval: bool = False


class PlanRef(Model):
    request_id: str
    line_id: str | None = None
    rank: int | None = None


class Decision(Model):
    decision_id: str
    plan_ref: PlanRef
    outcome: Outcome
    required_role: Role | None = None
    scopes: list[str] = Field(default_factory=lambda: ["order", "line", "item"])  # which rule scopes were evaluated
    approver_role: Role | None = None  # set on re-evaluation after a human approval
    triggered: list[RuleResult] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    informational: list[str] = Field(default_factory=list)
    policy: dict[str, Any]
    mandate: str | None = None
    inputs_digest: str
    evaluated_at: datetime
