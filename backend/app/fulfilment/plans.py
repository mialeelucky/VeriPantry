"""Plan building, scoring, ranking and rationale (fulfilment §8.1, §9; audit-log §7.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.contracts import (
    FLAG_LATER_DELIVERY,
    FLAG_OVERFILL,
    FLAG_PARTIAL,
    FLAG_QUANTITY_UNCONFIRMED,
    FLAG_SPLIT,
    FLAG_SUBSTITUTION,
    Deviation,
    NotPresented,
    Plan,
    PlanItem,
    Quantity,
    Rationale,
    RequestLine,
    Scores,
    Strategy,
    Tier,
    Weights,
)
from app.fulfilment.feasibility import Assessment
from app.fulfilment.quantity import floor_to, lot_step, overfill_tolerance, units_for

CENT = Decimal("0.01")
MAX_CO2 = Decimal("30.46")  # data-set maximum, kg CO2-eq/kg (§9.2)
MISSING_RELIABILITY = 0.9
UNCONFIRMED_FACTOR = 0.9
SPLIT_PENALTY = 0.03
SINGLE_PRODUCT_TOLERANCE = Decimal("1.03")  # §8.1 step 3
KEY_PRODUCT_SHARE = Decimal("0.2")  # product diversity (§9.3)


@dataclass
class Candidate:
    """An assessed product plus how it relates to the request."""

    assessment: Assessment
    tier: Tier
    sim: float
    name_sim: float
    deviations: list[Deviation] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.assessment.product.id


Allocation = list[tuple[Candidate, Decimal]]  # (candidate, sales units)


# --------------------------------------------------------------------------- allocation


def allocate(candidates: list[Candidate], required: Decimal, allow_split: bool, max_products: int | None = None) -> Allocation:
    out: Allocation = []
    remaining = required
    for c in candidates:
        if remaining <= 0:
            break
        a = c.assessment
        step = lot_step(a.product)
        su = units_for(remaining, a.content, step)
        if a.confirmed_sales_units is not None:
            su = min(su, floor_to(a.confirmed_sales_units, step))
        if su <= 0:
            continue
        out.append((c, su))
        remaining -= su * a.content
        if not allow_split or (max_products and len(out) >= max_products):
            break
    return out


def covered(allocation: Allocation) -> Decimal:
    return sum((su * c.assessment.content for c, su in allocation), Decimal(0))


# --------------------------------------------------------------------------- plan construction


def _item(c: Candidate, su: Decimal, line: RequestLine, required: Decimal) -> PlanItem:
    a = c.assessment
    p = a.product
    qty = su * a.content
    share = (qty / required).quantize(Decimal("0.0001")) if required else None
    return PlanItem(
        product_id=p.id,
        name=p.name_en,
        brand=p.brand,
        category=p.category,
        tier=c.tier,
        sim=round(c.sim, 4),
        status=a.status,
        quantity_basis=a.basis,
        sales_units=su,
        sales_unit=p.sales_unit,
        quantity=Quantity(value=qty, unit=line.quantity.unit),
        content_per_sales_unit=a.content,
        available_date=a.available_date,
        closing_time=a.closing_time,
        unit_price=a.unit_price,
        line_total=(su * a.unit_price).quantize(CENT),
        unit_cost=(a.unit_price / a.content).quantize(Decimal("0.0001")),
        reliability=p.reliability,
        carbon_kg_per_kg=p.carbon_kg_per_kg,
        allergens=dict(sorted(p.allergens.items())),
        claims=sorted(p.claims),
        labels=sorted(p.labels),
        confirmed_sales_units=a.confirmed_sales_units,
        flags=sorted(set(a.flags)),
        deviations=[d.model_copy(update={"share": share}) for d in c.deviations],
    )


def build_plan(strategy: Strategy, allocation: Allocation, line: RequestLine, deliver_by) -> Plan:
    required = line.quantity.value
    items = [_item(c, su, line, required) for c, su in allocation]
    total_cov = covered(allocation)
    # Overfill beyond tolerance is flagged on the last item (§4.2).
    if items and total_cov - required > overfill_tolerance(required, allocation[-1][0].assessment.content):
        items[-1].flags = sorted(set(items[-1].flags) | {FLAG_OVERFILL})
    complete = total_cov >= required
    on_time = all(i.available_date is not None and i.available_date <= deliver_by for i in items)
    flags: set[str] = set()
    for i in items:
        flags |= set(i.flags)
    if any(i.tier != "exact" for i in items):
        flags.add(FLAG_SUBSTITUTION)
    if len({i.product_id for i in items}) > 1:
        flags.add(FLAG_SPLIT)
    if not on_time:
        flags.add(FLAG_LATER_DELIVERY)
    if not complete:
        flags.add(FLAG_PARTIAL)
    merged: dict[str, Deviation] = {}
    for i in items:
        for d in i.deviations:
            if d.attribute in merged:
                prev = merged[d.attribute]
                merged[d.attribute] = prev.model_copy(update={"share": (prev.share or 0) + (d.share or 0)})
            else:
                merged[d.attribute] = d
    return Plan(
        line_id=line.line_id,
        strategy=strategy,
        items=items,
        total=sum((i.line_total for i in items), Decimal(0)).quantize(CENT),
        covered=Quantity(value=total_cov, unit=line.quantity.unit) if total_cov > 0 else line.quantity,
        coverage=min(Decimal(1), (total_cov / required)).quantize(Decimal("0.0001")),
        complete=complete,
        on_time=on_time,
        scores=Scores(fit=0, cost=0, reliability=0, sustainability=0, total=0),
        flags=sorted(flags),
        deviations=list(merged.values()),
    )


# --------------------------------------------------------------------------- scoring (§9.2)


def _weighted(plan: Plan, value) -> float:
    total_q = sum(float(i.quantity.value) for i in plan.items) or 1.0
    return sum(value(i) * float(i.quantity.value) for i in plan.items) / total_q


def _reliability(i: PlanItem) -> float:
    r = i.reliability if i.reliability is not None else MISSING_RELIABILITY
    return r * UNCONFIRMED_FACTOR if FLAG_QUANTITY_UNCONFIRMED in i.flags else r


def _sustainability(i: PlanItem) -> float:
    base = 0.5 if i.carbon_kg_per_kg is None else max(0.0, 1 - float(i.carbon_kg_per_kg / MAX_CO2))
    eco = 0.1 if any(lbl in i.labels for lbl in _ECO) else 0.0
    return min(1.0, base + eco)


from app.catalog.models import ECO_LABELS as _ECO  # noqa: E402


def score_plans(plans: list[Plan], weights: Weights) -> None:
    per_unit = [p.total / p.covered.value for p in plans if p.covered.value > 0]
    cheapest = min(per_unit) if per_unit else Decimal(1)
    for p in plans:
        fit = _weighted(p, lambda i: 1.0 if i.tier == "exact" else i.sim)
        cost = float(cheapest / (p.total / p.covered.value)) if p.covered.value > 0 and p.total > 0 else 0.0
        rel = _weighted(p, _reliability)
        sus = _weighted(p, _sustainability)
        n_products = len({i.product_id for i in p.items})
        total = (
            weights.fit * fit
            + weights.cost * cost
            + weights.reliability * rel
            + weights.sustainability * sus
            - SPLIT_PENALTY * (n_products - 1)
        )
        p.scores = Scores(fit=round(fit, 4), cost=round(cost, 4), reliability=round(rel, 4), sustainability=round(sus, 4), total=round(total, 4))


# --------------------------------------------------------------------------- ranking (§9.3)


def rank_key(p: Plan):
    if p.complete and p.on_time:
        group, secondary = 0, 0.0
    elif p.complete:
        latest = max((i.available_date for i in p.items if i.available_date), default=None)
        group, secondary = 1, float(latest.toordinal()) if latest else 1e9
    else:
        group, secondary = 2, -float(p.coverage)
    return (group, secondary, -p.scores.total, p.total, tuple(p.product_ids))


def key_products(p: Plan) -> frozenset[str]:
    cov = p.covered.value or Decimal(1)
    shares: dict[str, Decimal] = {}
    for i in p.items:
        shares[i.product_id] = shares.get(i.product_id, Decimal(0)) + i.quantity.value / cov
    return frozenset(pid for pid, s in shares.items() if s >= KEY_PRODUCT_SHARE)


def select_top_three(plans: list[Plan]) -> tuple[list[Plan], list[NotPresented], set[int]]:
    """Apply ranking plus product and strategy diversity. Returns (presented, not presented, promoted ids)."""
    ranked = sorted(plans, key=rank_key)
    presented: list[Plan] = []
    rejected: list[NotPresented] = []
    promoted: set[int] = set()
    seen_keys: list[frozenset[str]] = []
    pending = list(ranked)
    while pending and len(presented) < 3:
        p = pending.pop(0)
        if key_products(p) in seen_keys:
            rejected.append(_not_presented(p, "duplicate_products"))
            continue
        if len(presented) == 2 and presented[0].strategy == presented[1].strategy == p.strategy:
            alt = next((q for q in pending if q.strategy != p.strategy and key_products(q) not in seen_keys), None)
            if alt is not None:
                rejected.append(_not_presented(p, "strategy_diversity"))
                pending.remove(alt)
                p = alt
                promoted.add(id(p))
        presented.append(p)
        seen_keys.append(key_products(p))
    rejected += [_not_presented(p, "ranked_below_third") for p in pending]
    return presented, rejected, promoted


def _not_presented(p: Plan, reason: str) -> NotPresented:
    return NotPresented(strategy=p.strategy, product_ids=p.product_ids, total=p.total, score=p.scores.total, reason=reason)


# --------------------------------------------------------------------------- rationale (audit-log §7.4)


def add_rationale(presented: list[Plan], line: RequestLine, name_sims: dict[int, float], promoted: set[int]) -> None:
    if not presented:
        return
    best = presented[0]
    complete = sorted((p for p in presented if p.complete and p.on_time), key=lambda p: p.total)
    most_expensive = max(p.total for p in presented)
    sub_fits = [p.scores.fit for p in presented if FLAG_SUBSTITUTION in p.flags]

    def strictly_top(value, values) -> bool:
        return len(values) > 1 and value == max(values) and sorted(values)[-2] < value

    # complete_on_time only distinguishes a plan when not every presented plan has it.
    all_complete = all(q.complete and q.on_time for q in presented)
    presented_names = [name_sims.get(id(q), 0.0) for q in presented]

    for p in presented:
        # Codes in priority order: the most distinguishing reasons come first,
        # and at most four are kept (audit-log §7.4).
        codes: list[Rationale] = []
        if complete and p is complete[0]:
            margin = complete[1].total - p.total if len(complete) > 1 else None
            codes.append(Rationale(code="cheapest_complete", params={"marginEUR": margin} if margin is not None else {}))
        elif p is not best and p.total > best.total:
            codes.append(Rationale(code="cost_above_best", params={"deltaEUR": p.total - best.total}))
        if line.product_id and line.product_id in p.product_ids:
            kept = sum((i.quantity.value for i in p.items if i.product_id == line.product_id), Decimal(0))
            codes.append(
                Rationale(
                    code="keeps_requested_product",
                    params={"quantity": kept, "unit": line.quantity.unit, "share": (kept / line.quantity.value).quantize(Decimal("0.01"))},
                )
            )
        if id(p) in promoted:
            codes.append(Rationale(code="diversity_rule_applied"))
        if not p.on_time:
            latest = max((i.available_date for i in p.items if i.available_date), default=None)
            codes.append(Rationale(code="later_delivery", params={"date": latest}))
        if not p.complete:
            codes.append(
                Rationale(code="partial", params={"quantity": p.covered.value, "requested": line.quantity.value, "unit": line.quantity.unit})
            )
        if p.complete and p.on_time and (len(presented) == 1 or not all_complete):
            codes.append(Rationale(code="complete_on_time"))
        n = len({i.product_id for i in p.items})
        codes.append(Rationale(code="split", params={"n": n}) if n > 1 else Rationale(code="single_product"))
        if p.deviations:
            codes.append(Rationale(code="only_deviation", params={"attributes": [d.attribute for d in p.deviations]}))
        if FLAG_SUBSTITUTION in p.flags and strictly_top(p.scores.fit, sub_fits):
            codes.append(Rationale(code="highest_fit"))
        elif strictly_top(name_sims.get(id(p), 0.0), presented_names):
            codes.append(Rationale(code="closest_name"))
        if strictly_top(p.scores.reliability, [q.scores.reliability for q in presented]):
            codes.append(Rationale(code="highest_reliability"))
        if strictly_top(p.scores.sustainability, [q.scores.sustainability for q in presented]):
            codes.append(Rationale(code="lowest_carbon"))
        if len(presented) > 1 and p.total == most_expensive and p is not best:
            codes.append(Rationale(code="most_expensive"))
        p.rationale = codes[:4]
