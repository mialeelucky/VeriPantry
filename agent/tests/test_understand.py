from datetime import date

from stub_agent.understand import next_weekday, parse, scenarios, understand

SUNDAY = date(2026, 11, 15)


def test_scenario_text_returns_prepared_draft():
    s = scenarios(SUNDAY)[1]
    r = understand(s["text"].upper(), SUNDAY)
    assert r["source"] == "scenario" and r["draft"]["lines"][0]["productId"] == "469363"
    assert r["draft"]["deliverBy"] == "2026-11-16"


def test_rules_parse_quantity_date_claims_brand_allergy():
    r = parse("Need 2,500 litres of lactose-free semi-skimmed milk from Valio by Tuesday, one guest has a milk allergy", SUNDAY)
    line = r["draft"]["lines"][0]
    assert line["quantity"] == {"value": 2500, "unit": "L"}
    assert r["draft"]["deliverBy"] == "2026-11-17"
    assert line["spec"]["requiredAttributes"] == ["FREE_FROM_LACTOSE"]
    assert line["spec"]["excludedAllergens"] == ["AM"]
    assert "brand:Valio" in line["spec"]["preferredAttributes"] and "fat:1.5" in line["spec"]["preferredAttributes"]
    assert r["ambiguities"] == []


def test_missing_parts_become_questions():
    r = parse("something nice for dessert", SUNDAY)
    assert r["draft"]["lines"][0]["quantity"] is None
    assert any("How much" in a for a in r["ambiguities"])
    assert any("Which product" in a for a in r["ambiguities"])
    assert any("No delivery date" in a for a in r["ambiguities"])


def test_decimal_comma_and_next_weekday():
    assert parse("2,5 kg cream tomorrow", SUNDAY)["draft"]["lines"][0]["quantity"] == {"value": 2.5, "unit": "KG"}
    assert next_weekday(SUNDAY, "sunday") == date(2026, 11, 22)  # "by Sunday" on a Sunday means next week
