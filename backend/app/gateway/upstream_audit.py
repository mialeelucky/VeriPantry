"""An Upstream wrapper that records every call as a Valio-only audit event."""

from __future__ import annotations

import time
from datetime import date

from app.audit import events as ev
from app.audit.log import AuditLog
from app.upstream.client import Upstream, UpstreamError


class AuditedUpstream:
    def __init__(self, inner: Upstream, audit: AuditLog, transaction_id: str, customer: str, mandate: str | None):
        self._inner, self._audit = inner, audit
        self._tx, self._customer, self._mandate = transaction_id, customer, mandate

    def _call(self, endpoint: str, product_ids: list[str], requested_date: date):
        t0 = time.monotonic()
        status = 200
        try:
            return getattr(self._inner, endpoint)(product_ids, requested_date)
        except UpstreamError:
            status = 500
            raise
        finally:
            self._audit.append(
                ev.UPSTREAM_QUERIED,
                transaction_id=self._tx,
                actor=ev.GATEWAY,
                customer=self._customer,
                mandate=self._mandate,
                payload={
                    "endpoint": endpoint,
                    "requestedDate": requested_date,
                    "productCount": len(product_ids),
                    "httpStatus": status,
                    "latencyMs": int((time.monotonic() - t0) * 1000),
                },
            )

    def availability(self, product_ids, requested_date):
        return self._call("availability", product_ids, requested_date)

    def price(self, product_ids, requested_date):
        return self._call("price", product_ids, requested_date)
