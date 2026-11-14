"""The rule catalogue (guardrails §5). One pure function per rule ID.

Each rule receives the evaluation input and returns the results it triggers
(an empty list when it passes). A rule that cannot be evaluated raises
``Skip`` and is recorded under ``skipped``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Callable, Iterable

from app.core.bands import reliability_band
from app.core.contracts import (
    FLAG_CONTENT_UNCERTAIN,
    FLAG_CUTOFF_PASSED,
    FLAG_OVERFILL,
    FLAG_QUANTITY_UNCONFIRMED,
    Plan,
    PlanItem,
    PurchaseRequest,
    RequestLine,
)
from app.guardrails.models import Context, MandateInfo, Policy, RuleResult

CENT = Decimal("0.01")


class Skip(Exception):
    pass


@dataclass
class EvalInput:
    request: PurchaseRequest
    plans: dict[str, Plan]  # line id -> plan under evaluation
    mandate: MandateInfo | None
    policy: Policy  # effective policy (mandate limits merged)
    context: Context
    reference_costs: dict[str, Decimal | None] = field(default_factory=dict)

    @property
    def order_total(self) -> Decimal:
        return sum((p.total for p in self.plans.values()), Decimal(0)).quantize(CENT)

    def line(self, line_id: str) -> RequestLine:
        return next(line for line in self.request.lines if line.line_id == line_id)

    def items(self) -> Iterable[tuple[RequestLine, Plan, PlanItem]]:
        for line_id, plan in self.plans.items():
            for item in plan.items:
                yield self.line(line_id), plan, item


def eur(value: Decimal) -> str:
    return f"€{Decimal(value).quantize(CENT):,.2f}"


def _r(rule, scope, outcome, code, message, role=None, **kw) -> RuleResult:
    return RuleResult(rule=rule, scope=scope, outcome=outcome, role=role, code=code, message=message, **kw)


def _substitutes(inp: EvalInput):
    return [(line, plan, item) for line, plan, item in inp.items() if item.tier != "exact"]


# --------------------------------------------------------------------------- A: authority


def gr_a1(inp: EvalInput):
    m = inp.mandate
    if m is None or not m.signature_valid or m.revoked or m.expires_at <= inp.context.now:
        why = "missing" if m is None else "invalid signature" if not m.signature_valid else "revoked" if m.revoked else "expired"
        return [_r("GR-A1", "order", "DENY", "mandate_invalid", f"The agent's mandate is {why}.", observed=why)]
    return []


def gr_a2(inp: EvalInput):
    if inp.mandate is not None and "order.place" not in inp.mandate.actions:
        return [_r("GR-A2", "order", "DENY", "action_not_permitted", "The mandate does not permit placing orders.", observed=inp.mandate.actions)]
    return []


def gr_a3(inp: EvalInput):
    cats = inp.policy.scope.categories
    if not cats:
        return []
    out = []
    for line, _, item in inp.items():
        if not any(item.category.startswith(c) for c in cats):
            out.append(
                _r("GR-A3", "item", "ESCALATE", "category_out_of_scope", f"Category {item.category} is outside the mandate's categories {cats}.",
                   role="admin", line_id=line.line_id, product_id=item.product_id, observed=item.category, limit=cats)
            )
    return out


def gr_a4(inp: EvalInput):
    horizon = inp.context.now.date() + timedelta(days=inp.policy.delivery.deliver_within_days)
    out = []
    for line, _, item in inp.items():
        if item.available_date is not None and item.available_date > horizon:
            out.append(
                _r("GR-A4", "item", "ESCALATE", "beyond_delivery_horizon",
                   f"Delivery on {item.available_date} is beyond the {inp.policy.delivery.deliver_within_days}-day horizon ({horizon}).",
                   role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.available_date, limit=horizon)
            )
    return out


# --------------------------------------------------------------------------- S: safety


def gr_s1(inp: EvalInput):
    out = []
    for line, _, item in inp.items():
        for code in line.spec.excluded_allergens:
            state = item.allergens.get(code, "not_declared")
            if state != "free_from":
                out.append(
                    _r("GR-S1", "item", "DENY", "allergen_violation",
                       f"{item.product_id} declares allergen {code} as {state.upper()}; {code} is excluded for this request. "
                       "No approver can override this rule.",
                       line_id=line.line_id, product_id=item.product_id, observed=state, limit="free_from")
                )
    return out


def gr_s2(inp: EvalInput):
    out = []
    for line, _, item in inp.items():
        have = set(item.claims) | set(item.labels)
        missing = [a for a in line.spec.required_attributes if a not in have]
        if missing:
            out.append(
                _r("GR-S2", "item", "DENY", "required_attribute_missing", f"{item.product_id} lacks required attribute(s) {missing}.",
                   line_id=line.line_id, product_id=item.product_id, observed=missing)
            )
    return out


# --------------------------------------------------------------------------- V: validity


def gr_v1(inp: EvalInput):
    out = []
    for line, _, item in inp.items():
        if item.offer_valid_until is None or inp.context.now >= item.offer_valid_until:
            out.append(
                _r("GR-V1", "item", "DENY", "offer_expired",
                   f"The offer for {item.product_id} is no longer valid" + (f" (valid until {item.offer_valid_until.isoformat()})." if item.offer_valid_until else "."),
                   line_id=line.line_id, product_id=item.product_id, observed=inp.context.now, limit=item.offer_valid_until, remedy="requote")
            )
    return out


def gr_v2(inp: EvalInput):
    out = []
    for line, _, item in inp.items():
        if item.status in ("not_deliverable", "blocked", "no_price") or item.tier == "S3":
            out.append(
                _r("GR-V2", "item", "DENY", "item_not_orderable", f"{item.product_id} cannot be ordered (status {item.status}, tier {item.tier}).",
                   line_id=line.line_id, product_id=item.product_id, observed=item.status)
            )
    return out


def gr_v3(inp: EvalInput):
    out = []
    for line, _, item in inp.items():
        if item.confirmed_sales_units is not None and item.sales_units > item.confirmed_sales_units:
            out.append(
                _r("GR-V3", "item", "DENY", "exceeds_confirmed_quantity",
                   f"{item.sales_units} {item.sales_unit} of {item.product_id} exceeds the confirmed {item.confirmed_sales_units}.",
                   line_id=line.line_id, product_id=item.product_id, observed=item.sales_units, limit=item.confirmed_sales_units, unit=item.sales_unit)
            )
    return out


def gr_v4(inp: EvalInput):
    return [
        _r("GR-V4", "item", "ESCALATE", "cutoff_passed", f"The order cut-off for {item.product_id} has passed; the delivery date is not guaranteed.",
           role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.closing_time)
        for line, _, item in inp.items()
        if FLAG_CUTOFF_PASSED in item.flags
    ]


# --------------------------------------------------------------------------- M: money


def gr_m1(inp: EvalInput):
    total, limit = inp.order_total, inp.policy.spend.auto_limit_eur
    if total > limit:
        return [_r("GR-M1", "order", "ESCALATE", "spend_over_auto_limit", f"Order total {eur(total)} exceeds the autonomous limit of {eur(limit)}.",
                   role="approver", observed=total, limit=limit, unit="EUR")]
    return []


def gr_m2(inp: EvalInput):
    total, limit = inp.order_total, inp.policy.spend.approver_limit_eur
    if total > limit:
        return [_r("GR-M2", "order", "ESCALATE", "spend_over_approver_limit", f"Order total {eur(total)} exceeds the approver limit of {eur(limit)}.",
                   role="admin", observed=total, limit=limit, unit="EUR")]
    return []


def gr_m3(inp: EvalInput):
    out = []
    evaluated = False
    for line_id, plan in inp.plans.items():
        ref = inp.reference_costs.get(line_id)
        if ref is None or plan.covered.value <= 0:
            continue
        evaluated = True
        unit_cost = (plan.total / plan.covered.value).quantize(Decimal("0.0001"))
        limit = (ref * (1 + inp.policy.spend.max_unit_price_increase_pct / 100)).quantize(Decimal("0.0001"))
        if unit_cost > limit:
            pct = ((unit_cost / ref - 1) * 100).quantize(Decimal("0.1"))
            out.append(
                _r("GR-M3", "line", "ESCALATE", "unit_price_increase",
                   f"Unit cost €{unit_cost}/{plan.covered.unit} is {pct} % above the reference €{ref}/{plan.covered.unit} "
                   f"(limit +{inp.policy.spend.max_unit_price_increase_pct} %).",
                   role="approver", line_id=line_id, observed=unit_cost, limit=limit, unit=f"EUR/{plan.covered.unit}")
            )
    if not evaluated:
        raise Skip("GR-M3")
    return out


def gr_m4(inp: EvalInput):
    budget = inp.policy.spend.period_budget_eur
    if budget is None:
        return []
    projected = inp.context.period_spend_eur + inp.order_total
    if projected > budget:
        return [_r("GR-M4", "order", "ESCALATE", "period_budget_exceeded",
                   f"Period spend would reach {eur(projected)}, above the budget of {eur(budget)}.", role="admin", observed=projected, limit=budget, unit="EUR")]
    return []


# --------------------------------------------------------------------------- Q: quantity


def gr_q1(inp: EvalInput):
    limit = inp.policy.quantity.max_qty_per_line
    if limit is None:
        return []
    out = []
    for line_id in inp.plans:
        q = inp.line(line_id).quantity
        if q.value > limit:
            out.append(_r("GR-Q1", "line", "ESCALATE", "quantity_over_mandate", f"Requested {q.value} {q.unit} exceeds the mandate's {limit} {q.unit} per line.",
                          role="approver", line_id=line_id, observed=q.value, limit=limit, unit=q.unit))
    return out


def gr_q2(inp: EvalInput):
    return [
        _r("GR-Q2", "line", "ESCALATE", "partial_fulfilment",
           f"The plan covers {plan.covered.value} of {inp.line(lid).quantity.value} {plan.covered.unit} ({(plan.coverage * 100).quantize(Decimal('0.1'))} %).",
           role="approver", line_id=lid, observed=plan.coverage, limit=Decimal(1))
        for lid, plan in inp.plans.items()
        if not plan.complete
    ]


def gr_q3(inp: EvalInput):
    return [
        _r("GR-Q3", "item", "ESCALATE", "excess_overfill", f"{item.product_id} over-delivers beyond the silent tolerance.",
           role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.quantity.value)
        for line, _, item in inp.items()
        if FLAG_OVERFILL in item.flags
    ]


def gr_q4(inp: EvalInput):
    limit = inp.policy.quantity.max_auto_products_per_line
    out = []
    for lid, plan in inp.plans.items():
        n = len({i.product_id for i in plan.items})
        if n > limit:
            out.append(_r("GR-Q4", "line", "ESCALATE", "too_many_products", f"The line uses {n} products; at most {limit} are allowed autonomously.",
                          role="approver", line_id=lid, observed=n, limit=limit))
    return out


# --------------------------------------------------------------------------- D: delivery


def gr_d1(inp: EvalInput):
    deliver_by = inp.request.deliver_by
    return [
        _r("GR-D1", "item", "ESCALATE", "later_delivery",
           f"{item.product_id} arrives " + (f"on {item.available_date}" if item.available_date else "on an unconfirmed date") + f", after the requested {deliver_by}.",
           role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.available_date, limit=deliver_by)
        for line, _, item in inp.items()
        if item.available_date is None or item.available_date > deliver_by
    ]


def gr_d2(inp: EvalInput):
    minimum = inp.policy.delivery.min_reliability_for_unconfirmed
    out = []
    for line, _, item in inp.items():
        if FLAG_QUANTITY_UNCONFIRMED in item.flags and (item.reliability is None or item.reliability < minimum):
            # The raw score is internal (trust-protocol §5.1); only its band is disclosed.
            band = reliability_band(item.reliability)
            out.append(_r("GR-D2", "item", "ESCALATE", "unconfirmed_low_reliability",
                          f"{item.product_id} is supplier-direct with unconfirmed quantity and delivery reliability '{band}', "
                          f"below the policy minimum.",
                          role="approver", line_id=line.line_id, product_id=item.product_id, observed=band, limit=minimum))
    return out


# --------------------------------------------------------------------------- X: substitution


def gr_x1(inp: EvalInput):
    if inp.policy.substitution.auto_substitution:
        return []
    return [_r("GR-X1", "item", "ESCALATE", "substitution_needs_approval", f"{item.product_id} is a substitute; automatic substitution is off.",
               role="approver", line_id=line.line_id, product_id=item.product_id) for line, _, item in _substitutes(inp)]


def gr_x2(inp: EvalInput):
    tiers = inp.policy.substitution.auto_tiers
    return [_r("GR-X2", "item", "ESCALATE", "substitution_tier", f"{item.product_id} is a tier {item.tier} substitute; only {tiers} are auto-approved.",
               role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.tier, limit=tiers)
            for line, _, item in _substitutes(inp) if item.tier not in tiers]


def gr_x3(inp: EvalInput):
    minimum = inp.policy.substitution.min_similarity
    return [_r("GR-X3", "item", "ESCALATE", "low_similarity", f"{item.product_id} has similarity {item.sim:.2f}, below the minimum {minimum:.2f}.",
               role="approver", line_id=line.line_id, product_id=item.product_id, observed=item.sim, limit=minimum)
            for line, _, item in _substitutes(inp) if item.sim < minimum]


def gr_x4(inp: EvalInput):
    flexible = set(inp.policy.substitution.flexible_attributes)
    out = []
    for line, _, item in _substitutes(inp):
        for d in item.deviations:
            if d.attribute not in flexible:
                out.append(_r("GR-X4", "item", "ESCALATE", "inflexible_deviation",
                              f"{d.attribute} changes from {d.requested} to {d.proposed}; {d.attribute} is not a flexible attribute in your policy.",
                              role="approver", line_id=line.line_id, product_id=item.product_id, observed=d.attribute, limit=sorted(flexible)))
    return out


# --------------------------------------------------------------------------- T: data quality and anomalies


def gr_t1(inp: EvalInput):
    return [_r("GR-T1", "item", "ESCALATE", "content_uncertain", f"The content per sales unit of {item.product_id} is uncertain.",
               role="approver", line_id=line.line_id, product_id=item.product_id)
            for line, _, item in inp.items() if FLAG_CONTENT_UNCERTAIN in item.flags]


def gr_t2(inp: EvalInput):
    limit = inp.policy.velocity.max_auto_orders_per_day
    if inp.context.auto_orders_last_24h >= limit:
        return [_r("GR-T2", "order", "ESCALATE", "unusual_order_velocity",
                   f"{inp.context.auto_orders_last_24h} autonomous orders in the last 24 h (limit {limit}).",
                   role="admin", observed=inp.context.auto_orders_last_24h, limit=limit)]
    return []


Rule = tuple[str, str, Callable[[EvalInput], list[RuleResult]]]

# Ordered by ID (§6.1). Adding a rule = adding one function and one entry here.
RULES: list[Rule] = [
    ("GR-A1", "order", gr_a1),
    ("GR-A2", "order", gr_a2),
    ("GR-A3", "item", gr_a3),
    ("GR-A4", "item", gr_a4),
    ("GR-D1", "item", gr_d1),
    ("GR-D2", "item", gr_d2),
    ("GR-M1", "order", gr_m1),
    ("GR-M2", "order", gr_m2),
    ("GR-M3", "line", gr_m3),
    ("GR-M4", "order", gr_m4),
    ("GR-Q1", "line", gr_q1),
    ("GR-Q2", "line", gr_q2),
    ("GR-Q3", "item", gr_q3),
    ("GR-Q4", "line", gr_q4),
    ("GR-S1", "item", gr_s1),
    ("GR-S2", "item", gr_s2),
    ("GR-T1", "item", gr_t1),
    ("GR-T2", "order", gr_t2),
    ("GR-V1", "item", gr_v1),
    ("GR-V2", "item", gr_v2),
    ("GR-V3", "item", gr_v3),
    ("GR-V4", "item", gr_v4),
    ("GR-X1", "item", gr_x1),
    ("GR-X2", "item", gr_x2),
    ("GR-X3", "item", gr_x3),
    ("GR-X4", "item", gr_x4),
]
