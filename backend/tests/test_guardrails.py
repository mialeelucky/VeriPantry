"""Guardrail acceptance tests T01–T33 (guardrails §12).

Every case starts from scenario 1 (§11): 1,000 L lactose-free semi-skimmed
milk, fulfilled by 464306 for €1,010.00 (real fixture data), and changes one
input. T34–T36 (approval workflow) live in test_gateway.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.contracts import Deviation, LineResult, PurchaseRequest, Quantity
from app.fulfilment.engine import FulfilmentEngine
from app.guardrails.engine import evaluate
from app.guardrails.models import Context, MandateInfo, Policy
from app.guardrails.selection import select_line

OFFER_VALID_UNTIL = datetime.fromisoformat("2026-11-15T17:00:00+02:00")


@pytest.fixture
def base(catalog, upstream, clock):
    request = PurchaseRequest.model_validate(
        {
            "requestId": "req_t",
            "customer": "customer:HOTEL-123",
            "deliverBy": "2026-11-16",
            "lines": [
                {
                    "lineId": "L1",
                    "spec": {"query": "semi skimmed milk", "category": "10400", "requiredAttributes": ["FREE_FROM_LACTOSE"]},
                    "quantity": {"value": 1000, "unit": "L"},
                }
            ],
        }
    )
    result = FulfilmentEngine(catalog, upstream, clock).run(request).lines[0]
    plan = result.plans[0]
    for item in plan.items:
        item.offer_id, item.offer_valid_until = "off_test", OFFER_VALID_UNTIL
    mandate = MandateInfo(
        id="mdt_7f3c9a",
        customer="customer:HOTEL-123",
        agent="agent:hotel-123-procurement-01",
        expires_at=clock.now() + timedelta(days=7),
        actions=["catalog.search", "offer.request", "order.place"],
        limits={"maxOrderValueEUR": 2000, "maxQtyPerLine": 1500, "deliverWithinDays": 14},
    )
    policy = Policy(scope={"categories": ["104"]})
    return {
        "request": request,
        "result": result,
        "plan": plan,
        "mandate": mandate,
        "policy": policy,
        "context": Context(now=clock.now()),
        "refs": {"L1": result.reference_unit_cost},
    }


def run(b, **overrides):
    s = {**b, **overrides}
    return evaluate(s["request"], {"L1": s["plan"]}, s["mandate"], s["policy"], s["context"], s["refs"])


def rules(decision):
    return sorted({r.rule for r in decision.triggered})


def item(b):
    return b["plan"].items[0]


def as_substitute(b, tier="S1", sim=0.82, attribute="brand"):
    i = item(b)
    i.tier, i.sim = tier, sim
    i.deviations = [Deviation(attribute=attribute, requested="x", proposed="y")]


# --------------------------------------------------------------------------- authority


def test_T01_baseline_allows(base):
    assert base["plan"].total == Decimal("1010.00")
    d = run(base)
    assert (d.outcome, rules(d)) == ("ALLOW", [])


def test_T02_expired_mandate(base):
    base["mandate"].expires_at = base["context"].now - timedelta(seconds=1)
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-A1"])


def test_T03_order_place_not_permitted(base):
    base["mandate"].actions = ["catalog.search", "offer.request"]
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-A2"])


def test_T04_category_out_of_scope(base):
    d = run(base, policy=Policy(scope={"categories": ["106"]}))
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "admin", ["GR-A3"])


def test_T05_beyond_delivery_horizon(base):
    now = base["context"].now.date()
    item(base).available_date = now + timedelta(days=20)
    base["request"].deliver_by = now + timedelta(days=30)
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-A4"])


# --------------------------------------------------------------------------- safety


def test_T06_milk_allergy_denies_lactose_free_milk(base):
    base["request"].lines[0].spec.excluded_allergens = ["AM"]
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-S1"])
    assert "CONTAINS" in d.triggered[0].message


def test_T07_not_declared_allergen_is_unsafe(base):
    base["request"].lines[0].spec.excluded_allergens = ["AW"]
    item(base).allergens.pop("AW", None)
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-S1"])
    assert d.triggered[0].observed == "not_declared"


def test_T08_required_attribute_missing(base):
    base["request"].lines[0].spec.required_attributes = ["FREE_FROM_GLUTEN"]
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-S2"])


# --------------------------------------------------------------------------- validity


def test_T09_expired_offer_denies_with_requote(base):
    d = run(base, context=Context(now=OFFER_VALID_UNTIL + timedelta(minutes=1)))
    assert (d.outcome, rules(d)) == ("DENY", ["GR-V1"])
    assert d.triggered[0].remedy == "requote"


def test_T10_not_deliverable(base):
    item(base).status = "not_deliverable"
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-V2"])


def test_T11_exceeds_confirmed_quantity(base):
    item(base).confirmed_sales_units = Decimal("384")
    d = run(base)
    assert (d.outcome, rules(d)) == ("DENY", ["GR-V3"])


def test_T12_cutoff_passed(base):
    item(base).flags = ["cutoff_passed"]
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-V4"])


# --------------------------------------------------------------------------- money


def _total(b, value):
    b["plan"].total = Decimal(value)
    b["refs"] = {}  # isolate the spend rules from GR-M3


def test_T13_limit_is_inclusive(base):
    _total(base, "2000.00")
    d = run(base)
    assert (d.outcome, rules(d)) == ("ALLOW", [])


def test_T14_just_over_auto_limit(base):
    _total(base, "2000.01")
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-M1"])


def test_T15_over_approver_limit(base):
    _total(base, "5000.01")
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "admin", ["GR-M1", "GR-M2"])


def test_T16_unit_price_increase(base):
    base["request"].lines[0].quantity = Quantity(value=Decimal(500), unit="L")
    base["plan"].covered = Quantity(value=Decimal(500), unit="L")
    base["plan"].total = Decimal("1365.00")  # €2.73/L
    base["refs"] = {"L1": Decimal("2.48")}
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-M3"])


def test_T17_no_reference_cost_skips_M3(base):
    base["refs"] = {}
    d = run(base)
    assert (d.outcome, rules(d), d.skipped) == ("ALLOW", [], ["GR-M3"])


def test_T18_period_budget(base):
    policy = Policy(scope={"categories": ["104"]}, spend={"periodBudgetEur": 5000})
    d = run(base, policy=policy, context=Context(now=base["context"].now, period_spend_eur=Decimal(4500)))
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "admin", ["GR-M4"])


# --------------------------------------------------------------------------- quantity


def test_T19_quantity_over_mandate(base):
    base["request"].lines[0].quantity = Quantity(value=Decimal(1600), unit="L")
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-Q1"])


def test_T20_partial_fulfilment(base):
    p = base["plan"]
    p.complete, p.coverage = False, Decimal("0.384")
    d = run(base)
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "approver", ["GR-Q2"])


def test_T21_three_products(base):
    p = base["plan"]
    first = p.items[0]
    p.items = [first.model_copy(update={"product_id": pid}) for pid in ("464306", "464201", "464398")]
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-Q4"])


# --------------------------------------------------------------------------- delivery


def test_T22_later_delivery(base):
    item(base).available_date = base["request"].deliver_by + timedelta(days=1)
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-D1"])


def test_T23_unconfirmed_without_reliability(base):
    item(base).flags, item(base).reliability = ["quantity_unconfirmed"], None
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-D2"])


def test_T24_unconfirmed_with_good_reliability(base):
    item(base).flags, item(base).reliability = ["quantity_unconfirmed"], 0.97
    d = run(base)
    assert (d.outcome, rules(d)) == ("ALLOW", [])


# --------------------------------------------------------------------------- substitution


def test_T25_auto_substitution_off(base):
    as_substitute(base)
    d = run(base, policy=Policy(scope={"categories": ["104"]}, substitution={"autoSubstitution": False}))
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-X1"])


def test_T26_tier_S2(base):
    as_substitute(base, tier="S2")
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-X2"])


def test_T27_low_similarity(base):
    as_substitute(base, sim=0.79)
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-X3"])


def test_T28_inflexible_deviation(base):
    as_substitute(base, attribute="origin")
    d = run(base)
    assert (d.outcome, rules(d)) == ("ESCALATE", ["GR-X4"])


def test_T29_flexible_brand_change_allowed(base):
    as_substitute(base, attribute="brand")
    d = run(base)
    assert (d.outcome, rules(d)) == ("ALLOW", [])


# --------------------------------------------------------------------------- anomalies and aggregation


def test_T30_order_velocity(base):
    d = run(base, context=Context(now=base["context"].now, auto_orders_last_24h=10))
    assert (d.outcome, d.required_role, rules(d)) == ("ESCALATE", "admin", ["GR-T2"])


def test_T31_deny_dominates_and_all_rules_listed(base):
    base["request"].lines[0].spec.excluded_allergens = ["AM"]
    _total(base, "3030.00")
    d = run(base)
    assert d.outcome == "DENY"
    assert rules(d) == ["GR-M1", "GR-S1"]


def _two_plans(b, second_score):
    best = b["plan"]
    best.scores.total = 0.92
    best.items[0].flags = ["cutoff_passed"]  # makes Best ESCALATE
    second = best.model_copy(deep=True)
    second.rank, second.label = 2, "second"
    second.items[0].flags = []
    second.scores.total = second_score
    best.rank, best.label = 1, "best"
    return LineResult(line_id="L1", status="substitution_proposed", plans=[best, second], reference_unit_cost=b["refs"]["L1"])


def test_T32_equivalent_plan_within_tolerance_selected(base):
    lr = _two_plans(base, 0.88)
    sel = select_line(lr, base["request"], base["mandate"], base["policy"], base["context"])
    assert (sel.step, sel.selected.rank, sel.reason) == (3, 2, "equivalent_plan_within_tolerance")


def test_T33_outside_tolerance_goes_to_approval(base):
    lr = _two_plans(base, 0.81)
    sel = select_line(lr, base["request"], base["mandate"], base["policy"], base["context"])
    assert (sel.step, sel.selected, sel.recommended.rank, sel.required_role) == (4, None, 1, "approver")


# --------------------------------------------------------------------------- determinism


def test_decision_is_reproducible(base):
    assert run(base).inputs_digest == run(base).inputs_digest
