"""Client for the Valio Aimo mock price and availability APIs.

* Batches up to 1,000 products per call (the API's limit).
* Caches answers per (product, date) for a few minutes (fulfilment §7.1), so
  repeated plan generation never re-queries.
* Only ever called with a short, pre-filtered product list, never the catalog.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.clock import parse_api_time

MAX_PRODUCTS_PER_CALL = 1000


@dataclass(frozen=True, slots=True)
class Availability:
    product_id: str
    closing_time: datetime | None
    sales_block: bool
    logistic_model: str | None
    has_line: bool
    available_amount: Decimal | None
    available_date: date | None
    sales_unit: str | None
    line_sales_block: bool


@dataclass(frozen=True, slots=True)
class Price:
    product_id: str
    error: bool
    unit_price: Decimal | None  # catalogPrice.value, VAT excluded, per sales unit
    unit_price_with_tax: Decimal | None
    comparison_price: Decimal | None
    comparison_unit: str | None
    tax_rate: Decimal | None
    net_price_found: bool
    valid_to: datetime | None


class UpstreamError(RuntimeError):
    pass


class Upstream(Protocol):
    def availability(self, product_ids: list[str], requested_date: date) -> dict[str, Availability]: ...

    def price(self, product_ids: list[str], requested_date: date) -> dict[str, Price]: ...


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def parse_availability(item: dict) -> Availability:
    lines = item.get("scheduleLines") or []
    line = lines[0] if lines else {}
    return Availability(
        product_id=item["productId"],
        closing_time=parse_api_time(item.get("closingTime")),
        sales_block=bool(item.get("salesBlock")),
        logistic_model=item.get("logisticModel"),
        has_line=bool(lines),
        available_amount=_dec(line.get("availableAmount")),
        available_date=date.fromisoformat(line["availableDate"]) if line.get("availableDate") else None,
        sales_unit=line.get("salesUnit"),
        line_sales_block=bool(line.get("salesBlock")),
    )


def parse_price(item: dict) -> Price:
    catalog = item.get("catalogPrice") or {}
    comparison = item.get("comparisonPrice") or {}
    tax = item.get("tax") or {}
    return Price(
        product_id=item["productId"],
        error=bool(item.get("error")),
        unit_price=_dec(catalog.get("value")),
        unit_price_with_tax=_dec(catalog.get("valueWithTax")),
        comparison_price=_dec(comparison.get("value")),
        comparison_unit=item.get("comparisonUnit"),
        tax_rate=_dec(tax.get("taxRate")),
        net_price_found=bool(item.get("netPriceFound")),
        valid_to=parse_api_time(catalog.get("validTo")),
    )


class ValioClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        customer: str = "veripantry",
        cache_ttl_seconds: int = 300,
        http: httpx.Client | None = None,
        on_call=None,
    ):
        if not base_url or not api_key:
            raise UpstreamError("Upstream API is not configured (VALIO_API_BASE_URL / VALIO_API_KEY)")
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._customer = customer
        self._ttl = cache_ttl_seconds
        # IPv4 only: on networks without working IPv6 the first connection otherwise
        # waits ~40 s for the IPv6 attempt to time out before falling back.
        self._http = http or httpx.Client(timeout=30, transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=1))
        self._cache: dict[tuple[str, str, date], tuple[float, object]] = {}
        self._lock = threading.Lock()
        self.on_call = on_call  # callback(endpoint, requested_date, product_count, status, latency_ms, from_cache)

    def _fetch(self, endpoint: str, product_ids: list[str], requested_date: date, parse) -> dict:
        now = time.monotonic()
        result: dict = {}
        missing: list[str] = []
        with self._lock:
            for pid in dict.fromkeys(product_ids):
                hit = self._cache.get((endpoint, pid, requested_date))
                if hit and now - hit[0] < self._ttl:
                    result[pid] = hit[1]
                else:
                    missing.append(pid)
        if not missing:
            if self.on_call:
                self.on_call(endpoint, requested_date, len(product_ids), 200, 0, True)
            return result
        for start in range(0, len(missing), MAX_PRODUCTS_PER_CALL):
            batch = missing[start : start + MAX_PRODUCTS_PER_CALL]
            body = {"customer": self._customer, "requestedDate": requested_date.isoformat(), "products": batch}
            t0 = time.monotonic()
            try:
                resp = self._http.post(f"{self._base}/api/{endpoint}", json=body, headers=self._headers)
            except httpx.HTTPError as exc:
                if self.on_call:
                    self.on_call(endpoint, requested_date, len(batch), 0, int((time.monotonic() - t0) * 1000), False)
                raise UpstreamError(f"{endpoint} request failed: {exc}") from exc
            latency = int((time.monotonic() - t0) * 1000)
            if self.on_call:
                self.on_call(endpoint, requested_date, len(batch), resp.status_code, latency, False)
            if resp.status_code != 200:
                raise UpstreamError(f"{endpoint} returned HTTP {resp.status_code}")
            fetched_at = time.monotonic()
            with self._lock:
                for item in resp.json()["products"]:
                    parsed = parse(item)
                    result[parsed.product_id] = parsed
                    self._cache[(endpoint, parsed.product_id, requested_date)] = (fetched_at, parsed)
        return result

    def availability(self, product_ids: list[str], requested_date: date) -> dict[str, Availability]:
        return self._fetch("availability", product_ids, requested_date, parse_availability)

    def price(self, product_ids: list[str], requested_date: date) -> dict[str, Price]:
        return self._fetch("price", product_ids, requested_date, parse_price)


class FixtureUpstream:
    """Replays recorded API responses: deterministic tests without network access."""

    def __init__(self, availability_items: list[dict], price_items: list[dict]):
        self._availability = {i["productId"]: parse_availability(i) for i in availability_items}
        self._price = {i["productId"]: parse_price(i) for i in price_items}
        self.calls: list[tuple[str, int]] = []
        self.fail = False

    def availability(self, product_ids: list[str], requested_date: date) -> dict[str, Availability]:
        if self.fail:
            raise UpstreamError("availability returned HTTP 500")
        self.calls.append(("availability", len(product_ids)))
        return {p: self._availability[p] for p in product_ids if p in self._availability}

    def price(self, product_ids: list[str], requested_date: date) -> dict[str, Price]:
        if self.fail:
            raise UpstreamError("price returned HTTP 500")
        self.calls.append(("price", len(product_ids)))
        return {p: self._price[p] for p in product_ids if p in self._price}
