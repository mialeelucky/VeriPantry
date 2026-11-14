"""Load the static data set into compact Product records.

Implements the static parts of fulfilment-and-substitution §3.1 and §4.1:
content per unit, four-state allergens, claims, labels and nutrition.
"""

from __future__ import annotations

import csv
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from app.catalog.models import Content, Product
from app.core.contracts import AllergenState

PRODUCT_FILE = "valio_aimo_junction26_product_data.json"
RELIABILITY_FILE = "valio_aimo_junction26_delivery_reliability.csv"
CARBON_FILE = "valio_aimo_junction26_carbon_footprint.csv"

_VOLUME_TO_L = {"LTR": Decimal("1"), "DLT": Decimal("0.1"), "CLT": Decimal("0.01"), "MLT": Decimal("0.001")}
_WEIGHT_TO_KG = {"KGM": Decimal("1"), "GRM": Decimal("0.001"), "MGM": Decimal("0.000001")}
_NAME_UNITS = {
    "l": ("L", Decimal("1")),
    "dl": ("L", Decimal("0.1")),
    "cl": ("L", Decimal("0.01")),
    "ml": ("L", Decimal("0.001")),
    "kg": ("KG", Decimal("1")),
    "g": ("KG", Decimal("0.001")),
}
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(kg|g|l|dl|cl|ml)\b"
# "12x397g", "100x2 cl", "250x2,5g": the name describes the whole sales unit.
_RE_INLINE_MULTI = re.compile(rf"(\d+)\s*x\s*{_NUM}\s*{_UNIT}", re.IGNORECASE)
# "5 x Arla 1 L ...": a leading multiplier, also describing the whole sales unit.
_RE_LEADING_MULTI = re.compile(r"^\s*(\d+)\s*x\s+", re.IGNORECASE)
_RE_SIZE = re.compile(rf"(?<![\w,.]){_NUM}\s*{_UNIT}", re.IGNORECASE)
_RE_TOKEN = re.compile(r"[0-9a-zäöåéü]+", re.IGNORECASE)

_NUTRIENTS = {"FAT", "PRO-", "CHOAVL", "SUGAR-", "LACS"}
_ALLERGEN_RANK = {"contains": 3, "may_contain": 2, "free_from": 1, "not_declared": 0}


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _RE_TOKEN.findall(text.replace("®", " ").replace("™", " "))]


def parse_name_size(name: str) -> tuple[Decimal, str, bool] | None:
    """Return (amount, "L"|"KG", describes_sales_unit) parsed from a product name."""
    m = _RE_INLINE_MULTI.search(name)
    if m:
        count, size, unit = int(m.group(1)), _dec(m.group(2)), m.group(3).lower()
        target, factor = _NAME_UNITS[unit]
        return Decimal(count) * size * factor, target, True
    size_match = _RE_SIZE.search(name)
    if not size_match:
        return None
    size, unit = _dec(size_match.group(1)), size_match.group(2).lower()
    target, factor = _NAME_UNITS[unit]
    lead = _RE_LEADING_MULTI.match(name)
    if lead:
        return Decimal(int(lead.group(1))) * size * factor, target, True
    return size * factor, target, False


def _base_content(raw: dict, base_unit: str) -> Content:
    if base_unit == "KG":
        return Content(kilograms=Decimal("1"), source="static")
    litres = kilograms = None
    for conv in raw.get("synkkaData", {}).get("unitConversions", []) or []:
        if conv.get("synkkaPackagingType") != "BASE_UNIT_OR_EACH":
            continue
        vol, net = conv.get("volume"), conv.get("netWeight")
        if vol and vol.get("unit") in _VOLUME_TO_L and _dec(vol.get("value")):
            litres = _dec(vol["value"]) * _VOLUME_TO_L[vol["unit"]]
        if net and net.get("unit") in _WEIGHT_TO_KG and _dec(net.get("value")):
            kilograms = _dec(net["value"]) * _WEIGHT_TO_KG[net["unit"]]
        break
    if litres is None and kilograms is None:
        return Content()
    return Content(litres=litres, kilograms=kilograms, source="static")


def _scale(content: Content, factor: Decimal | None) -> Content:
    if factor is None:
        return Content()
    return Content(
        litres=content.litres * factor if content.litres is not None else None,
        kilograms=content.kilograms * factor if content.kilograms is not None else None,
        source=content.source,
    )


def _allergens(classifications: Iterable[dict]) -> dict[str, AllergenState]:
    states: dict[str, AllergenState] = {}
    mapping = {"CONTAINS": "contains", "MAY_CONTAIN": "may_contain", "FREE_FROM": "free_from", "UNDECLARED": "not_declared"}
    for group in classifications:
        if group.get("name") not in ("allergen", "nonAllergen"):
            continue
        for value in group.get("values", []):
            code, state = value.get("id"), mapping.get(value.get("unit", ""))
            if not code or not state:
                continue
            # The most cautious statement wins if a product declares one allergen twice.
            if _ALLERGEN_RANK[state] >= _ALLERGEN_RANK.get(states.get(code, "not_declared"), 0):
                states[code] = state  # type: ignore[assignment]
    return states


def _class_ids(classifications: Iterable[dict], name: str) -> frozenset[str]:
    return frozenset(v["id"] for g in classifications if g.get("name") == name for v in g.get("values", []) if v.get("id"))


def _nutrition(raw_nutrition: Iterable[dict]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for n in raw_nutrition or []:
        if n.get("id") in _NUTRIENTS and n.get("unit") == "GRM" and _dec(n.get("basisQuantity")) == 100:
            value = _dec(n.get("value"))
            if value is not None:
                out[n["id"]] = value
    return out


def build_product(raw: dict) -> Product:
    synkka = raw.get("synkkaData") or {}
    classifications = synkka.get("classifications", []) or []
    names = {n["language"]: n["value"] for n in synkka.get("names", []) if n.get("value")}
    unit_sizes = {u["unitId"]: _dec(u["sizeInBaseUnits"]) for u in raw.get("units", []) if _dec(u.get("sizeInBaseUnits"))}
    base_unit, sales_unit = raw["baseUnit"], raw["salesUnit"]
    base_size = unit_sizes.get(base_unit, Decimal("1"))
    if sales_unit in unit_sizes:
        multiplier: Decimal | None = unit_sizes[sales_unit] / base_size
    elif sales_unit == base_unit:
        multiplier = Decimal("1")
    else:
        multiplier = None

    base_content = _base_content(raw, base_unit)
    sales_content = _scale(base_content, multiplier)
    if sales_content.litres is None and sales_content.kilograms is None:
        name = names.get("en") or names.get("fi") or ""
        parsed = parse_name_size(name)
        if parsed:
            amount, target, whole_sales_unit = parsed
            per_sales = amount if whole_sales_unit else (amount * multiplier if multiplier is not None else None)
            if per_sales is not None:
                kw = {"litres": per_sales} if target == "L" else {"kilograms": per_sales}
                sales_content = Content(**kw, source="name")
                if not whole_sales_unit:
                    base_content = Content(**({"litres": amount} if target == "L" else {"kilograms": amount}), source="name")
                elif multiplier:
                    per_base = per_sales / multiplier
                    base_content = Content(**({"litres": per_base} if target == "L" else {"kilograms": per_base}), source="name")

    key_ingredients = next((k["value"] for k in synkka.get("keyIngredients", []) if k.get("language") == "en"), None)
    tokens = frozenset(t for name in names.values() for t in tokenize(name))
    return Product(
        id=raw["id"],
        names={k: v.strip() for k, v in names.items()},
        brand=(synkka.get("brand") or "").strip() or None,  # the data has e.g. "Arla " with a trailing space
        category=raw["category"],
        sales_unit=sales_unit,
        base_unit=base_unit,
        allowed_lot_size=_dec(raw.get("allowedLotSize")) or Decimal("1"),
        unit_sizes=unit_sizes,
        base_content=base_content,
        sales_content=sales_content,
        pcs_per_sales_unit=multiplier if base_unit != "KG" else None,
        claims=_class_ids(classifications, "nutritionalClaim"),
        labels=_class_ids(classifications, "packagingMarkedLabel"),
        allergens=_allergens(classifications),
        nutrition=_nutrition(synkka.get("nutritionalContent", [])),
        temperature_condition=raw.get("temperatureCondition"),
        country_of_origin=raw.get("countryOfOrigin"),
        substitutes=tuple(s["substituteProduct"] for s in raw.get("substitutions", []) or []),
        gtin=raw.get("salesUnitGtin") or synkka.get("gtin"),
        key_ingredients_en=key_ingredients,
        synkka_last_updated=synkka.get("lastUpdated"),
        vendor_name=raw.get("vendorName"),
        tokens=tokens,
    )


def _read_csv_map(path: Path, value_column: str) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["productId"]: row[value_column] for row in csv.DictReader(f) if row.get(value_column)}


def load_products(data_dir: Path, raw_products: list[dict] | None = None) -> dict[str, Product]:
    if raw_products is None:
        with (data_dir / PRODUCT_FILE).open(encoding="utf-8") as f:
            raw_products = json.load(f)
    products = {p.id: p for p in (build_product(r) for r in raw_products)}
    for pid, value in _read_csv_map(data_dir / RELIABILITY_FILE, "deliveryReliability").items():
        if pid in products:
            products[pid].reliability = float(value)
    for pid, value in _read_csv_map(data_dir / CARBON_FILE, "AVG kg CO2-eq/kg").items():
        if pid in products:
            products[pid].carbon_kg_per_kg = _dec(value)
    return products
