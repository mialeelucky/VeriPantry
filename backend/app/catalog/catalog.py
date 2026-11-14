"""The static catalog: lookup and bounded text search (fulfilment §5, trust-protocol R2)."""

from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path

from app.catalog.loader import load_products, tokenize
from app.catalog.models import Product

# Small multilingual vocabulary so English queries also match Finnish/Swedish-only names.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "milk": ("maito", "mjölk"),
    "cream": ("kerma", "grädde"),
    "butter": ("voi", "smör"),
    "cheese": ("juusto", "ost"),
    "yoghurt": ("jogurtti", "yoghurt"),
    "yogurt": ("jogurtti", "yoghurt"),
    "potato": ("peruna", "potatis"),
    "tomato": ("tomaatti", "tomat"),
    "egg": ("kananmuna", "ägg"),
    "salmon": ("lohi", "lax"),
    "chicken": ("kana", "broiler", "kyckling"),
    "bread": ("leipä", "bröd"),
    "flour": ("jauho", "mjöl"),
}


def _token_matches(query_token: str, name_tokens: frozenset[str]) -> bool:
    candidates = (query_token, *_SYNONYMS.get(query_token, ()))
    for q in candidates:
        if q in name_tokens:
            return True
        if len(q) >= 4 and any(t.startswith(q) for t in name_tokens):
            return True  # "milk" matches "milkdrink", "maito" matches "maitojuoma"
    return False


class Catalog:
    def __init__(self, products: dict[str, Product]):
        self.products = products
        self.by_category: dict[str, list[Product]] = defaultdict(list)
        for p in products.values():
            self.by_category[p.category].append(p)

    def get(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def in_category(self, prefix: str) -> list[Product]:
        if len(prefix) == 5:
            return list(self.by_category.get(prefix, []))
        return [p for cat, items in self.by_category.items() if cat.startswith(prefix) for p in items]

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        required_attributes: list[str] | None = None,
        limit: int | None = None,
    ) -> list[Product]:
        """Products matching every query token, in the category, with every required attribute.

        Results are ordered by how specific the match is (fewer extra tokens first),
        then by product id, so the order is deterministic.
        """
        pool = self.in_category(category) if category else list(self.products.values())
        required = required_attributes or []
        q_tokens = [t for t in tokenize(query or "") if t not in {"x"}]
        hits: list[tuple[int, str, Product]] = []
        for p in pool:
            if any(not p.has_attribute(a) for a in required):
                continue
            if q_tokens and not all(_token_matches(t, p.tokens) for t in q_tokens):
                continue
            extra = len(set(tokenize(p.name_en))) - len(q_tokens)
            hits.append((extra, p.id, p))
        hits.sort(key=lambda h: (h[0], h[1]))
        result = [h[2] for h in hits]
        return result[:limit] if limit else result


_lock = threading.Lock()
_cache: dict[Path, Catalog] = {}


def get_catalog(data_dir: Path) -> Catalog:
    """Load the catalog once per process (the product file is ~87 MB)."""
    with _lock:
        if data_dir not in _cache:
            _cache[data_dir] = Catalog(load_products(data_dir))
        return _cache[data_dir]
