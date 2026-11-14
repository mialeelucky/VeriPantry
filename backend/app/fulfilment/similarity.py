"""Similarity, hard filters and deviations (fulfilment §6, §8.3)."""

from __future__ import annotations

import math
import re
from decimal import Decimal

from app.catalog.models import Product
from app.core.contracts import Deviation, RequestLine, Unit

W_CATEGORY, W_ATTR, W_NUTRITION, W_PACK, W_NAME, W_BRAND = 0.30, 0.25, 0.15, 0.10, 0.10, 0.10
OFFICIAL_FLOOR = 0.8
_NUTRITION_KEYS = ("FAT", "PRO-", "CHOAVL", "SUGAR-")
_RE_WORD = re.compile(r"[a-zäöå]+")
_SIZE_WORDS = {"l", "dl", "cl", "ml", "g", "kg", "x"}


# --------------------------------------------------------------------------- hard filters (§6)


def passes_hard_filters(product: Product, line: RequestLine, content: Decimal | None) -> bool:
    if any(not product.has_attribute(a) for a in line.spec.required_attributes):
        return False
    # Only an explicit FREE_FROM passes; "unknown" never counts as safe.
    if any(product.allergen_state(code) != "free_from" for code in line.spec.excluded_allergens):
        return False
    return content is not None


# --------------------------------------------------------------------------- preferences


def satisfies(product: Product, preference: str) -> bool | None:
    """True/False if the product meets a preferred attribute, None if not assessable."""
    key, _, value = preference.partition(":")
    if not value:
        key, value = "attr", preference
    if key == "brand":
        return bool(product.brand) and product.brand.strip().casefold() == value.strip().casefold()
    if key == "fat":
        fat = product.nutrition.get("FAT")
        return None if fat is None else abs(fat - Decimal(value)) < Decimal("0.05")
    if key == "origin":
        return (product.country_of_origin or "").lower() == value.lower()
    if key in ("claim", "label", "attr"):
        return product.has_attribute(value)
    return None


def name_tokens(product: Product) -> set[str]:
    brand = (product.brand or "").casefold()
    return {w for w in _RE_WORD.findall(product.name_en.casefold()) if w != brand and w not in _SIZE_WORDS}


def _pack_size(product: Product, unit: Unit) -> Decimal | None:
    content = product.base_content
    if unit in ("L", "KG"):
        return content.get(unit)
    return content.litres or content.kilograms


# --------------------------------------------------------------------------- similarity (§8.3)


def similarity(candidate: Product, reference: Product | None, line: RequestLine, official: bool = False) -> float:
    spec = line.spec
    # Category
    ref_cat = reference.category if reference else (spec.category or "")
    if official or (ref_cat and candidate.category == ref_cat):
        category = 1.0
    elif ref_cat and candidate.family == ref_cat[:3]:
        category = 0.5
    else:
        category = 0.0

    # Attributes: reference's soft claims/labels preserved + preferred attributes (brand excluded)
    hard = set(spec.required_attributes)
    items: list[bool] = []
    if reference:
        ref_soft = (reference.claims | reference.soft_labels) - hard
        items += [candidate.has_attribute(a) for a in sorted(ref_soft)]
    for pref in spec.preferred_attributes:
        if pref.startswith("brand:"):
            continue
        ok = satisfies(candidate, pref)
        if ok is not None:
            items.append(ok)
    attributes = sum(items) / len(items) if items else 1.0

    # Nutrition
    if reference and reference.nutrition and candidate.nutrition:
        dist = 0.0
        for k in _NUTRITION_KEYS:
            a, b = reference.nutrition.get(k), candidate.nutrition.get(k)
            if a is not None and b is not None:
                dist += float(abs(a - b) / max(a, b, Decimal(1)))
        nutrition = 1 - min(1.0, dist / len(_NUTRITION_KEYS))
    else:
        nutrition = 0.5

    # Pack format
    unit = line.quantity.unit
    a, b = (_pack_size(reference, unit) if reference else None), _pack_size(candidate, unit)
    pack = 1 - min(1.0, abs(math.log10(float(b / a)))) if a and b else 0.5

    # Name
    if reference:
        ra, cb = name_tokens(reference), name_tokens(candidate)
    else:
        ra, cb = set(_RE_WORD.findall((spec.query or "").casefold())), name_tokens(candidate)
    name = len(ra & cb) / len(ra | cb) if ra | cb else 0.0

    # Brand
    ref_brand = reference.brand if reference else next(
        (p.split(":", 1)[1] for p in spec.preferred_attributes if p.startswith("brand:")), None
    )
    brand = 1.0 if ref_brand and candidate.brand and candidate.brand.casefold() == ref_brand.casefold() else 0.0

    score = (
        W_CATEGORY * category
        + W_ATTR * attributes
        + W_NUTRITION * nutrition
        + W_PACK * pack
        + W_NAME * name
        + W_BRAND * brand
    )
    return max(score, OFFICIAL_FLOOR) if official else score


# --------------------------------------------------------------------------- deviations


def deviations(candidate: Product, reference: Product | None, line: RequestLine, is_exact: bool) -> list[Deviation]:
    """How an item differs from what was asked (fulfilment §11)."""
    found: dict[str, Deviation] = {}
    for pref in line.spec.preferred_attributes:
        if satisfies(candidate, pref) is False:
            key, _, value = pref.partition(":")
            attr = key if value else f"attr:{pref}"
            found[attr] = Deviation(attribute=attr, requested=value or pref, proposed=_proposed(candidate, key))
    if reference is not None and not is_exact and candidate.id != reference.id:
        if reference.brand and (candidate.brand or "").casefold() != reference.brand.casefold():
            found.setdefault("brand", Deviation(attribute="brand", requested=reference.brand, proposed=candidate.brand))
        if reference.country_of_origin and candidate.country_of_origin != reference.country_of_origin:
            found.setdefault(
                "origin", Deviation(attribute="origin", requested=reference.country_of_origin, proposed=candidate.country_of_origin)
            )
        a, b = _pack_size(reference, line.quantity.unit), _pack_size(candidate, line.quantity.unit)
        if a and b and abs(a - b) / a > Decimal("0.05"):
            found.setdefault("pack_size", Deviation(attribute="pack_size", requested=str(a.normalize()), proposed=str(b.normalize())))
        fa, fb = reference.nutrition.get("FAT"), candidate.nutrition.get("FAT")
        if fa is not None and fb is not None and abs(fa - fb) > Decimal("0.3"):
            found.setdefault("fat", Deviation(attribute="fat", requested=str(fa), proposed=str(fb)))
        hard = set(line.spec.required_attributes)
        for attr in sorted((reference.claims - hard) - candidate.claims):
            found.setdefault(f"claim:{attr}", Deviation(attribute=f"claim:{attr}", requested=True, proposed=False))
        for attr in sorted(reference.soft_labels - candidate.labels):
            found.setdefault(f"label:{attr}", Deviation(attribute=f"label:{attr}", requested=True, proposed=False))
    return list(found.values())


def _proposed(product: Product, key: str):
    return {
        "brand": product.brand,
        "fat": str(product.nutrition["FAT"]) if "FAT" in product.nutrition else None,
        "origin": product.country_of_origin,
    }.get(key, False)
