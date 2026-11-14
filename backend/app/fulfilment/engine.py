"""Fulfilment pipeline (fulfilment-and-substitution §1).

normalise → retrieve → hard-filter → shortlist + live lookup → feasibility →
optimal plan, or substitution → plan generation + ranking.

Deterministic: no LLM, no randomness. API calls are one availability and one
price call per phase, for all lines together.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.catalog.catalog import Catalog
from app.catalog.models import Product
from app.core.clock import Clock
from app.core.contracts import (
    CandidateCounts,
    FulfilmentResult,
    LineReason,
    LineResult,
    Plan,
    PurchaseRequest,
    RequestLine,
    Tier,
)
from app.fulfilment.feasibility import Assessment, assess
from app.fulfilment.plans import (
    SINGLE_PRODUCT_TOLERANCE,
    Allocation,
    Candidate,
    add_rationale,
    allocate,
    build_plan,
    covered,
    score_plans,
    select_top_three,
)
from app.fulfilment.quantity import static_content
from app.fulfilment.similarity import deviations, name_tokens, passes_hard_filters, similarity
from app.upstream.client import Upstream

SHORTLIST = 30  # §7.1
SPLIT_SUBSTITUTES = 5  # how many substitutes are tried as split partners
LATER_PLANS = 2


class RequestError(ValueError):
    """The request cannot be processed as given (e.g. unknown product)."""


@dataclass
class _LineWork:
    line: RequestLine
    reference: Product | None
    exact: list[Product]
    counts: CandidateCounts
    exact_candidates: list[Candidate] | None = None
    pool: list[tuple[Product, Tier, float]] | None = None


class FulfilmentEngine:
    def __init__(self, catalog: Catalog, upstream: Upstream, clock: Clock, cutoff_policy: str = "strict"):
        self.catalog = catalog
        self.upstream = upstream
        self.clock = clock
        self.cutoff_policy = cutoff_policy

    # ------------------------------------------------------------------ public

    def run(self, request: PurchaseRequest) -> FulfilmentResult:
        now = self.clock.now()
        work = [self._retrieve(line) for line in request.lines]

        # Phase 1: exact-match shortlists, one batched lookup.
        live = self._lookup({p.id for w in work for p in w.exact}, request)
        results: dict[str, LineResult] = {}
        needs_substitution: list[_LineWork] = []
        for w in work:
            w.exact_candidates = [self._candidate(p, "exact", 1.0, 1.0, w, request, live, now) for p in w.exact]
            w.counts.feasible = sum(1 for c in w.exact_candidates if c.assessment.usable_on_time)
            plan = self._optimal(w, request)
            if plan is not None:
                plan.label, plan.rank = "optimal", 1
                score_plans([plan], request.preferences.weights)
                add_rationale([plan], w.line, {}, set())
                results[w.line.line_id] = LineResult(
                    line_id=w.line.line_id,
                    status="fulfilled",
                    plans=[plan],
                    candidate_counts=w.counts,
                    reference_unit_cost=self._reference_cost(w),
                )
            else:
                needs_substitution.append(w)

        # Phase 2: substitute pools, one batched lookup.
        if needs_substitution:
            for w in needs_substitution:
                w.pool = self._substitute_pool(w)
                w.counts.substitute_pool = len(w.pool)
            live2 = self._lookup({p.id for w in needs_substitution for p, _, _ in w.pool}, request)
            for w in needs_substitution:
                results[w.line.line_id] = self._substitute(w, request, live2, now)

        return FulfilmentResult(
            request_id=request.request_id,
            evaluated_at=now,
            lines=[results[line.line_id] for line in request.lines],
        )

    # ------------------------------------------------------------------ retrieval (§5, §6)

    def _retrieve(self, line: RequestLine) -> _LineWork:
        spec = line.spec
        if line.product_id:
            product = self.catalog.get(line.product_id)
            if product is None:
                raise RequestError(f"unknown product {line.product_id}")
            retrieved = [product]
            reference: Product | None = product
        else:
            if not spec.query and not spec.category:
                raise RequestError(f"line {line.line_id}: give a productId, or a spec with a query or category")
            retrieved = self.catalog.search(spec.query, spec.category, spec.required_attributes)
            reference = None
        counts = CandidateCounts(retrieved=len(retrieved))
        filtered = [p for p in retrieved if passes_hard_filters(p, line, static_content(p, line.quantity.unit))]
        counts.after_hard_filter = len(filtered)
        shortlist = filtered[:SHORTLIST]
        counts.shortlisted = len(shortlist)
        if reference is None and shortlist:
            reference = shortlist[0]  # best search match serves as the similarity reference
        return _LineWork(line=line, reference=reference, exact=shortlist, counts=counts)

    def _substitute_pool(self, w: _LineWork) -> list[tuple[Product, Tier, float]]:
        line, ref = w.line, w.reference
        exact_ids = {p.id for p in w.exact}
        if line.product_id:
            exact_ids.add(line.product_id)
        tiers: dict[str, Tier] = {}
        official = set(ref.substitutes) if ref else set()
        for p in w.exact:
            official |= set(p.substitutes)
        for pid in sorted(official):
            if pid not in exact_ids and self.catalog.get(pid):
                tiers[pid] = "S0"
        category = ref.category if ref else line.spec.category
        if category:
            for p in self.catalog.in_category(category):
                tiers.setdefault(p.id, "S1")
            for p in self.catalog.in_category(category[:3]):
                tiers.setdefault(p.id, "S2")
        pool = []
        for pid, tier in tiers.items():
            if pid in exact_ids:
                continue
            p = self.catalog.get(pid)
            if not passes_hard_filters(p, line, static_content(p, line.quantity.unit)):
                continue
            pool.append((p, tier, similarity(p, ref, line, official=tier == "S0")))
        pool.sort(key=lambda t: (-t[2], t[0].id))
        return pool[:SHORTLIST]

    # ------------------------------------------------------------------ live data

    def _lookup(self, ids: set[str], request: PurchaseRequest):
        ordered = sorted(ids)
        if not ordered:
            return {}, {}
        return (
            self.upstream.availability(ordered, request.deliver_by),
            self.upstream.price(ordered, request.deliver_by),
        )

    def _candidate(self, product, tier, sim, name_sim, w: _LineWork, request, live, now) -> Candidate:
        availability, prices = live
        a = assess(
            product,
            availability.get(product.id),
            prices.get(product.id),
            w.line.quantity.unit,
            w.line.quantity.value,
            request.deliver_by,
            now,
            self.cutoff_policy,
        )
        # Exact matches deviate only from preferred attributes, never from the reference.
        return Candidate(
            assessment=a,
            tier=tier,
            sim=sim,
            name_sim=name_sim,
            deviations=deviations(product, w.reference, w.line, is_exact=tier == "exact"),
        )

    def _reference_cost(self, w: _LineWork) -> Decimal | None:
        """Reference unit cost for guardrail GR-M3 (guardrails §5.4)."""
        if w.line.max_unit_price is not None:
            return w.line.max_unit_price
        priced = [c.assessment for c in (w.exact_candidates or []) if c.assessment.unit_price is not None and c.assessment.content]
        if w.line.product_id:
            requested = next((a for a in priced if a.product.id == w.line.product_id), None)
            if requested:
                return requested.unit_cost.quantize(Decimal("0.0001"))
        if priced:
            return min(a.unit_cost for a in priced).quantize(Decimal("0.0001"))
        return None

    # ------------------------------------------------------------------ optimal plan (§8.1)

    @staticmethod
    def _by_cost(cands: list[Candidate]) -> list[Candidate]:
        return sorted(
            cands,
            key=lambda c: (
                c.assessment.unit_cost,
                -(c.assessment.product.reliability or 0),
                c.assessment.product.carbon_kg_per_kg or Decimal("999"),
                c.id,
            ),
        )

    def _optimal(self, w: _LineWork, request: PurchaseRequest) -> Plan | None:
        line = w.line
        required = line.quantity.value
        usable = self._by_cost([c for c in w.exact_candidates if c.assessment.usable_on_time])
        if not usable:
            return None
        allow_split = request.preferences.allow_split
        multi = allocate(usable, required, allow_split)
        if covered(multi) < required:
            return None
        multi_plan = build_plan("exact", multi, line, request.deliver_by)
        singles = [c for c in usable if c.assessment.can_cover(required)]
        if singles:
            single_plan = build_plan("exact", allocate([singles[0]], required, False), line, request.deliver_by)
            if len(multi_plan.items) == 1 or single_plan.total <= multi_plan.total * SINGLE_PRODUCT_TOLERANCE:
                return single_plan
        return multi_plan

    # ------------------------------------------------------------------ substitution (§8.2, §9)

    def _substitute(self, w: _LineWork, request: PurchaseRequest, live, now) -> LineResult:
        line = w.line
        required = line.quantity.value
        allow_split = request.preferences.allow_split
        ref_tokens = name_tokens(w.reference) if w.reference else set()
        subs: list[Candidate] = []
        for p, tier, sim in w.pool:
            toks = name_tokens(p)
            name_sim = len(ref_tokens & toks) / len(ref_tokens | toks) if ref_tokens | toks else 0.0
            subs.append(self._candidate(p, tier, sim, name_sim, w, request, live, now))
        on_time_subs = sorted(
            (c for c in subs if c.assessment.usable_on_time),
            key=lambda c: (-c.sim, c.assessment.unit_cost, c.id),
        )
        exact_usable = self._by_cost([c for c in w.exact_candidates if c.assessment.usable_on_time])
        exact_part = allocate(exact_usable, required, allow_split)
        exact_cov = covered(exact_part)
        remaining = required - exact_cov

        allocations: list[tuple[str, Allocation]] = []
        # Full substitute
        for c in on_time_subs:
            if c.assessment.can_cover(required):
                allocations.append(("full_substitute", allocate([c], required, False)))
        # Split: exact part + one substitute for the remainder
        if exact_part and allow_split:
            partners = [c for c in on_time_subs if c.assessment.can_cover(remaining)][:SPLIT_SUBSTITUTES]
            for c in partners:
                allocations.append(("split", exact_part + allocate([c], remaining, False)))
            if not partners:
                extra = allocate(on_time_subs, remaining, True, max_products=2)
                if extra:
                    allocations.append(("multi_substitute", exact_part + extra))
        # Multi-substitute without exact part
        if allow_split and not any(s == "full_substitute" for s, _ in allocations):
            multi = allocate(on_time_subs, required, True, max_products=2)
            if len(multi) > 1:
                allocations.append(("multi_substitute", multi))
        # Later delivery of the exact product(s)
        if request.preferences.allow_later_delivery:
            later = sorted(
                (c for c in w.exact_candidates if c.assessment.usable_later and c.assessment.can_cover(required)),
                key=lambda c: (c.assessment.available_date, c.assessment.unit_cost, c.id),
            )
            for c in later[:LATER_PLANS]:
                allocations.append(("later_delivery", allocate([c], required, False)))

        plans = [build_plan(s, a, line, request.deliver_by) for s, a in allocations if a]
        if not any(p.complete and p.on_time for p in plans):
            # Last resort: everything usable on time, in order of fit. If it happens
            # to cover the full quantity it is a multi-substitute plan, else partial.
            fallback = allocate(exact_usable + on_time_subs, required, allow_split)
            if fallback and covered(fallback) > 0:
                strategy = "multi_substitute" if covered(fallback) >= required else "partial"
                plans.append(build_plan(strategy, fallback, line, request.deliver_by))
        # De-duplicate identical allocations
        unique: dict[tuple, Plan] = {}
        for p in plans:
            unique.setdefault(tuple((i.product_id, i.sales_units) for i in p.items), p)
        plans = list(unique.values())

        name_sims = {
            id(p): max((c.name_sim for c in subs if c.id in p.product_ids and c.tier != "exact"), default=0.0) for p in plans
        }
        score_plans(plans, request.preferences.weights)
        presented, not_presented, promoted = select_top_three(plans)
        for rank, (p, label) in enumerate(zip(presented, ("best", "second", "third")), start=1):
            p.rank, p.label = rank, label
        add_rationale(presented, line, name_sims, promoted)

        reason = self._reason(w, exact_cov)
        w.counts.feasible += sum(1 for c in subs if c.assessment.usable_on_time)
        status = "substitution_proposed" if presented else "unfulfillable"
        return LineResult(
            line_id=line.line_id,
            status=status,
            reason=reason,
            plans=presented,
            not_presented=not_presented,
            candidate_counts=w.counts,
            reference_unit_cost=self._reference_cost(w),
        )

    @staticmethod
    def _reason(w: _LineWork, exact_cov: Decimal) -> LineReason:
        line = w.line
        statuses = {c.assessment.status for c in w.exact_candidates}
        if not w.exact:
            code = "no_exact_match"
        elif exact_cov > 0:
            code = "insufficient_quantity"
        elif statuses & {"late", "cutoff_passed"}:
            code = "not_available_on_time"
        else:
            code = "not_deliverable"
        return LineReason(code=code, requested=line.quantity.value, available_on_time=exact_cov, unit=line.quantity.unit)
