"""Compact in-memory product record derived from the static data set."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.contracts import AllergenState

# Labels that count as eco / organic for the sustainability bonus (fulfilment §9.2).
ECO_LABELS = frozenset(
    {
        "EU_ORGANIC_FARMING",
        "EU_ECO_LABEL",
        "SVANEN",
        "KRAV_MARK",
        "OFFICIAL_ECO_LABEL_SUN",
        "SOIL_ASSOCIATION_ORGANIC_SYMBOL",
        "MARINE_STEWARDSHIP_COUNCIL_LABEL",
        "AQUACULTURE_STEWARDSHIP_COUNCIL",
        "RAINFOREST_ALLIANCE",
        "FAIR_TRADE_MARK",
        "UTZ_CERTIFIED",
    }
)
TEMPERATURE_LABELS = frozenset({"warmTemperature", "coolTemperature", "freezeTemperature"})


@dataclass(frozen=True, slots=True)
class Content:
    """How much one unit contains, in litres or kilograms."""

    litres: Decimal | None = None
    kilograms: Decimal | None = None
    source: str = "unknown"  # "static" | "name"

    def get(self, unit: str) -> Decimal | None:
        return {"L": self.litres, "KG": self.kilograms}.get(unit)


@dataclass(slots=True)
class Product:
    id: str
    names: dict[str, str]
    brand: str | None
    category: str
    sales_unit: str
    base_unit: str
    allowed_lot_size: Decimal
    unit_sizes: dict[str, Decimal]  # unitId -> size in base units
    base_content: Content  # per base unit (consumer unit)
    sales_content: Content  # per sales unit
    pcs_per_sales_unit: Decimal | None
    claims: frozenset[str]
    labels: frozenset[str]
    allergens: dict[str, AllergenState]
    nutrition: dict[str, Decimal]  # per 100 g/ml
    temperature_condition: int | None
    country_of_origin: str | None
    substitutes: tuple[str, ...]
    gtin: str | None
    key_ingredients_en: str | None
    synkka_last_updated: str | None
    reliability: float | None = None
    carbon_kg_per_kg: Decimal | None = None
    # Tier T2: internal only, never exposed to agents (trust-protocol §5.1).
    vendor_name: str | None = None
    tokens: frozenset[str] = field(default_factory=frozenset)

    @property
    def family(self) -> str:
        return self.category[:3]

    @property
    def name_en(self) -> str:
        return self.names.get("en") or self.names.get("fi") or next(iter(self.names.values()), self.id)

    def has_attribute(self, attribute: str) -> bool:
        """A required/preferred attribute may be a claim or a label id."""
        return attribute in self.claims or attribute in self.labels

    @property
    def soft_labels(self) -> frozenset[str]:
        return self.labels - TEMPERATURE_LABELS

    @property
    def has_eco_label(self) -> bool:
        return bool(self.labels & ECO_LABELS)

    def allergen_state(self, code: str) -> AllergenState:
        return self.allergens.get(code, "not_declared")
