"""Fulfilment and substitution on recorded real data (fulfilment-and-substitution §10)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.catalog.loader import parse_name_size
from app.core.contracts import PurchaseRequest
from app.fulfilment.engine import FulfilmentEngine, RequestError


def request(line: dict, **kw) -> PurchaseRequest:
    return PurchaseRequest.model_validate(
        {"requestId": "req_f", "customer": "customer:HOTEL-123", "deliverBy": "2026-11-16", "lines": [line], **kw}
    )


ARLA = {
    "lineId": "L1",
    "productId": "469363",
    "spec": {"requiredAttributes": ["FREE_FROM_LACTOSE"], "preferredAttributes": ["brand:Arla", "fat:1.5"]},
    "quantity": {"value": 1000, "unit": "L"},
}
SPEC = {
    "lineId": "L1",
    "spec": {"query": "semi skimmed milk", "category": "10400", "requiredAttributes": ["FREE_FROM_LACTOSE"]},
    "quantity": {"value": 1000, "unit": "L"},
}


@pytest.fixture
def engine(catalog, upstream, clock):
    return FulfilmentEngine(catalog, upstream, clock)


def test_spec_request_is_fulfilled_by_cheapest_exact_match(engine):
    line = engine.run(request(SPEC)).lines[0]
    assert line.status == "fulfilled"
    (plan,) = line.plans
    assert (plan.label, plan.strategy, plan.total) == ("optimal", "exact", Decimal("1010.00"))
    assert plan.items[0].product_id == "464306"
    assert plan.flags == []


def test_specific_product_short_triggers_substitution(engine):
    line = engine.run(request(ARLA)).lines[0]
    assert line.status == "substitution_proposed"
    assert (line.reason.code, line.reason.available_on_time) == ("insufficient_quantity", Decimal("384.0"))
    assert line.reference_unit_cost == Decimal("2.4800")


def test_worked_example_best_and_third(engine):
    line = engine.run(request(ARLA)).lines[0]
    best, second, third = line.plans
    assert (best.label, best.strategy, best.product_ids, best.total) == ("best", "full_substitute", ["464306"], Decimal("1010.00"))
    assert round(best.scores.total, 2) == 0.92
    assert [d.attribute for d in best.deviations] == ["brand"]
    assert [r.code for r in best.rationale] == ["cheapest_complete", "single_product", "only_deviation"]
    # Third: the only plan keeping the requested Arla product, promoted by strategy diversity.
    assert (third.strategy, third.product_ids, third.total) == ("split", ["469363", "464306"], Decimal("1574.48"))
    assert third.items[0].deviations == []  # the requested Arla product does not deviate (brand "Arla " is trimmed)
    codes = [r.code for r in third.rationale]
    assert "keeps_requested_product" in codes and "diversity_rule_applied" in codes
    # Second: the cheaper skimmed milk narrowly outscores 464201 (fulfilment doc §10).
    assert (second.strategy, second.product_ids, second.total) == ("full_substitute", ["464401"], Decimal("1100.00"))
    assert {d.attribute for d in second.deviations} == {"brand", "fat"}
    diversity = [n for n in line.not_presented if n.reason == "strategy_diversity"]
    assert [n.product_ids for n in diversity] == [["464201"]]


def test_milk_allergy_excludes_all_milk_and_offers_only_milk_free_substitutes(engine):
    line = engine.run(request({**SPEC, "spec": {**SPEC["spec"], "excludedAllergens": ["AM"]}})).lines[0]
    assert line.candidate_counts.after_hard_filter == 0  # every lactose-free milk still CONTAINS milk
    assert (line.status, line.reason.code) == ("substitution_proposed", "no_exact_match")
    items = [i for p in line.plans for i in p.items]
    assert items and all(i.allergens.get("AM") == "free_from" for i in items)  # only explicit FREE_FROM passes
    assert all(i.tier == "S2" for i in items)  # plant drinks: a different category, so approval is required
    assert all(p.strategy in ("multi_substitute", "full_substitute", "partial") for p in line.plans)
    assert all(p.strategy != "partial" or not p.complete for p in line.plans)


def test_supplier_direct_cutoff_passed_is_not_promised(engine):
    line = engine.run(request({**ARLA, "productId": "469330"})).lines[0]  # Terminal, cut-off 2026-11-12
    assert line.status == "substitution_proposed"
    later = [p for p in line.plans + [] if p.strategy == "later_delivery"]
    assert all("cutoff_passed" in p.flags for p in later)


def test_lenient_cutoff_policy_uses_supplier_direct(catalog, upstream, clock):
    engine = FulfilmentEngine(catalog, upstream, clock, cutoff_policy="lenient")
    line = engine.run(request({**ARLA, "productId": "469330"})).lines[0]
    assert line.status == "fulfilled"
    plan = line.plans[0]
    assert plan.items[0].sales_units == Decimal("200")  # 5 x 1 L per carton
    assert {"cutoff_passed", "quantity_unconfirmed"} <= set(plan.flags)


def test_api_calls_are_batched(engine, upstream):
    engine.run(request(ARLA))
    assert upstream.calls == [("availability", 1), ("price", 1), ("availability", 30), ("price", 30)]


def test_deterministic(engine):
    a = engine.run(request(ARLA)).model_dump_json()
    b = engine.run(request(ARLA)).model_dump_json()
    assert a == b


def test_unknown_product_is_rejected(engine):
    with pytest.raises(RequestError):
        engine.run(request({**ARLA, "productId": "000000"}))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("5 x Arla 1 L lactose free semi-skimmed milk drink", (Decimal("5"), "L", True)),
        ("Arla Portion milk 100x2 cl lactose free", (Decimal("2.00"), "L", True)),
        ("Valio semi skimmed milk 2,5 dl lactose free UHT", (Decimal("0.25"), "L", False)),
        ("Törsleffs condensed milk 12x397g", (Decimal("4.764"), "KG", True)),
        ("Valio skimmed milk 10 l novobox", (Decimal("10"), "L", False)),
    ],
)
def test_name_size_parsing(name, expected):
    amount, unit, whole = parse_name_size(name)
    assert (amount.normalize(), unit, whole) == (expected[0].normalize(), expected[1], expected[2])
