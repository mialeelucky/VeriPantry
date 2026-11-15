"""Turn a chef's sentence into a draft purchase request, without an LLM.

Two sources, tried in order:
1. Demo scenarios: an exact (case-insensitive) match returns a prepared draft,
   so a recorded take never depends on parsing.
2. A small rule-based parser for free text. It recognises quantities, dates,
   a few products, dietary claims, allergies and brands, and reports anything
   it had to assume as an ambiguity for the chef to confirm.

The LLM buyer agent replaces step 2 later; the response shape stays the same.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Words for products the demo data covers, with their category and query.
PRODUCTS = [
    (r"semi[- ]?skimmed\s+milk", "semi skimmed milk", "10400", ["fat:1.5"]),
    (r"skimmed\s+milk", "skimmed milk", "10400", []),
    (r"whole\s+milk", "whole milk", "10400", []),
    (r"coffee\s+milk", "coffee milk", "10400", []),
    (r"\bmilk\b", "milk", "10400", []),
    (r"whipping\s+cream|\bcream\b", "cream", "10401", []),
]
CLAIMS = [
    (r"lactose[- ]free", "FREE_FROM_LACTOSE"),
    (r"gluten[- ]free", "FREE_FROM_GLUTEN"),
    (r"\bvegan\b", "VEGAN"),
]
ALLERGIES = [
    (r"milk allerg|allerg\w* to milk|dairy allerg", "AM"),
    (r"gluten allerg|coeliac|celiac", "AW"),
    (r"egg allerg|allerg\w* to eggs?", "AE"),
    (r"nut allerg|allerg\w* to nuts", "AN"),
]
BRANDS = ["Arla", "Valio"]


def next_weekday(today: date, name: str) -> date:
    target = WEEKDAYS.index(name)
    days = (target - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def scenarios(today: date) -> list[dict[str, Any]]:
    monday = next_weekday(today, "monday").isoformat()
    spec = {"query": "semi skimmed milk", "category": "10400", "requiredAttributes": ["FREE_FROM_LACTOSE"]}
    arla = {"requiredAttributes": ["FREE_FROM_LACTOSE"], "preferredAttributes": ["brand:Arla", "fat:1.5"]}

    def draft(line: dict) -> dict:
        return {"deliverBy": monday, "lines": [{"lineId": "L1", **line}]}

    return [
        {"id": "lactose-free", "title": "Lactose-free milk for Monday",
         "text": "We need 1,000 litres of lactose-free semi-skimmed milk by Monday.",
         "draft": draft({"spec": spec, "quantity": {"value": 1000, "unit": "L"}})},
        {"id": "arla-short", "title": "Arla, but stock is short",
         "text": "We need 1,000 litres of the Arla lactose-free semi-skimmed milk by Monday.",
         "draft": draft({"productId": "469363", "spec": arla, "quantity": {"value": 1000, "unit": "L"}})},
        {"id": "arla-event", "title": "Arla, 3,000 litres for an event",
         "text": "Big event this week: 3,000 litres of the Arla lactose-free semi-skimmed milk by Monday.",
         "draft": draft({"productId": "469363", "spec": arla, "quantity": {"value": 3000, "unit": "L"}})},
        {"id": "whole-chain", "title": "6,000 litres for the whole chain",
         "text": "6,000 litres of lactose-free semi-skimmed milk by Monday, for all our hotels.",
         "draft": draft({"spec": spec, "quantity": {"value": 6000, "unit": "L"}})},
        {"id": "milk-allergy", "title": "A guest with a milk allergy",
         "text": "1,000 litres of semi-skimmed milk drink by Monday. Some guests have a milk allergy.",
         "draft": draft({"spec": {**spec, "excludedAllergens": ["AM"]}, "quantity": {"value": 1000, "unit": "L"}})},
    ]


def _quantity(text: str) -> dict | None:
    m = re.search(r"(\d[\d,. ]*)\s*(litres?|liters?|l\b|kg|kilos?|kilograms?|pieces|pcs)", text, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    # "1,000" and "1.000" are thousands; "2,5" is a decimal comma.
    if re.fullmatch(r"\d{1,3}([,.]\d{3})+", raw):
        value = float(re.sub(r"[,.]", "", raw))
    else:
        value = float(raw.replace(",", "."))
    unit_word = m.group(2).lower()
    unit = "KG" if unit_word.startswith("k") else "PCS" if unit_word.startswith(("piece", "pcs")) else "L"
    return {"value": int(value) if value.is_integer() else value, "unit": unit}


def _date(text: str, today: date) -> tuple[str, bool]:
    lower = text.lower()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1), True
    if "tomorrow" in lower:
        return (today + timedelta(days=1)).isoformat(), True
    for name in WEEKDAYS:
        if re.search(rf"\b{name}\b", lower):
            return next_weekday(today, name).isoformat(), True
    return (today + timedelta(days=2)).isoformat(), False


def parse(text: str, today: date) -> dict[str, Any]:
    lower = text.lower()
    ambiguities: list[str] = []
    quantity = _quantity(text)
    if quantity is None:
        ambiguities.append("How much do you need?")
    deliver_by, explicit = _date(text, today)
    if not explicit:
        ambiguities.append(f"No delivery date given. I assumed {deliver_by}.")
    product = next(((q, c, prefs) for pattern, q, c, prefs in PRODUCTS if re.search(pattern, lower)), None)
    spec: dict[str, Any] = {}
    if product:
        spec["query"], spec["category"] = product[0], product[1]
        prefs = list(product[2])
    else:
        ambiguities.append("Which product do you mean? I could not recognise it.")
        prefs = []
    required = [claim for pattern, claim in CLAIMS if re.search(pattern, lower)]
    excluded = [code for pattern, code in ALLERGIES if re.search(pattern, lower)]
    prefs += [f"brand:{b}" for b in BRANDS if re.search(rf"\b{b.lower()}\b", lower)]
    if required:
        spec["requiredAttributes"] = required
    if excluded:
        spec["excludedAllergens"] = excluded
    if prefs:
        spec["preferredAttributes"] = prefs
    line: dict[str, Any] = {"lineId": "L1", "spec": spec, "quantity": quantity}
    return {"draft": {"deliverBy": deliver_by, "lines": [line]}, "ambiguities": ambiguities, "source": "rules"}


def understand(text: str, today: date) -> dict[str, Any]:
    wanted = text.strip().casefold()
    for s in scenarios(today):
        if s["text"].casefold() == wanted:
            return {"draft": s["draft"], "ambiguities": [], "source": "scenario", "scenario": s["id"]}
    return parse(text, today)
