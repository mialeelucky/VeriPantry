"""Data tiers and disclosure (trust-protocol §5).

T0 catalog: any registered agent.  T1 customer: mandate holders.
T2 internal: never leaves the gateway (vendor, producer ids, exact stock,
raw reliability scores).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.catalog.models import Product
from app.core.bands import reliability_band
from app.core.contracts import Plan
from app.core.jcs import to_jsonable

T0_FIELDS = [
    "id", "names", "brand", "category", "salesUnit", "baseUnit", "unitSizes", "allowedLotSize", "gtin",
    "allergens", "claims", "labels", "nutritionPer100", "keyIngredients", "temperatureCondition",
    "countryOfOrigin", "contentPerSalesUnit", "carbonKgPerKg", "provenance",
]
WITHHELD_FIELDS = ["vendorName", "producers", "exactStock", "reliabilityScore"]


def catalog_view(p: Product) -> dict[str, Any]:
    """T0 view with provenance labels (trust-protocol §6.2)."""
    return to_jsonable(
        {
            "id": p.id,
            "names": p.names,
            "brand": p.brand,
            "category": p.category,
            "salesUnit": p.sales_unit,
            "baseUnit": p.base_unit,
            "unitSizes": p.unit_sizes,
            "allowedLotSize": p.allowed_lot_size,
            "gtin": p.gtin,
            "allergens": dict(sorted(p.allergens.items())),
            "claims": sorted(p.claims),
            "labels": sorted(p.labels),
            "nutritionPer100": p.nutrition,
            "keyIngredients": {"text": p.key_ingredients_en, "untrusted": True} if p.key_ingredients_en else None,
            "temperatureCondition": p.temperature_condition,
            "countryOfOrigin": p.country_of_origin,
            "contentPerSalesUnit": {"L": p.sales_content.litres, "KG": p.sales_content.kilograms, "source": p.sales_content.source},
            "carbonKgPerKg": p.carbon_kg_per_kg,
            "provenance": {
                "valio-master-data": ["category", "salesUnit", "baseUnit", "unitSizes", "allowedLotSize", "temperatureCondition"],
                "gs1-synkka": {
                    "fields": ["names", "brand", "allergens", "claims", "labels", "nutritionPer100", "keyIngredients", "countryOfOrigin"],
                    "asOf": p.synkka_last_updated,
                    "declaredBy": "manufacturer",
                },
                "carbon-dataset": ["carbonKgPerKg"],
            },
        }
    )


def plan_view(plan: Plan, requested: Decimal) -> dict[str, Any]:
    """Customer-facing (T1) view of a plan: exact stock and raw scores are removed.

    Confirmed quantities are disclosed only up to the requested quantity (R1).
    """
    data = to_jsonable(plan)
    for item, raw in zip(data["items"], plan.items):
        confirmed = item.pop("confirmedSalesUnits", None)
        reliability = item.pop("reliability", None)
        item["reliabilityBand"] = reliability_band(reliability)
        basis = item.pop("quantityBasis")
        item["stockBasis"] = {"known": "warehouse", "ample": "warehouse", "unconfirmed": "supplier-direct"}[basis]
        if confirmed is not None and raw.content_per_sales_unit:
            cap = Decimal(confirmed) * raw.content_per_sales_unit
            item["confirmedUpTo"] = {"value": to_jsonable(min(cap, requested)), "unit": raw.quantity.unit}
    return data
