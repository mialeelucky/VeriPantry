"""Record live availability and price responses as offline test fixtures.

Usage (from backend/):  python -m scripts.record_fixtures 2026-11-16

Records every lactose-free product in the milk family (category 104xx): the
products the worked examples in docs/ use. Fixtures are written to
tests/fixtures/milk_<date>.json together with the server time of the call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from app.catalog.catalog import get_catalog
from app.config import settings


def main(requested_date: str) -> None:
    catalog = get_catalog(settings.data_dir)
    ids = sorted(p.id for p in catalog.in_category("104") if "FREE_FROM_LACTOSE" in p.claims)
    headers = {"X-API-Key": settings.valio_api_key}
    body = {"customer": "veripantry", "requestedDate": requested_date, "products": ids}
    base = settings.valio_api_base_url.rstrip("/")
    with httpx.Client(timeout=60) as http:
        availability = http.post(f"{base}/api/availability", json=body, headers=headers)
        price = http.post(f"{base}/api/price", json=body, headers=headers)
    availability.raise_for_status()
    price.raise_for_status()
    out = {
        "requestedDate": requested_date,
        "timeNow": availability.json()["timeNow"],
        "availability": availability.json()["products"],
        "price": price.json()["products"],
    }
    target = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / f"milk_{requested_date}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"recorded {len(ids)} products at {out['timeNow']} -> {target}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-11-16")
