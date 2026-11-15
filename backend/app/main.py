"""Production entry point: ``uvicorn app.main:app``.

Wires the real components: static catalog, the Valio APIs (live, or recorded
with ``UPSTREAM_MODE=fixture``), SQLite in var/, gateway keys, registry,
per-customer policies and web push.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.api.app import create_app
from app.audit.log import AuditLog
from app.audit.store import AuditStore, connect
from app.catalog.catalog import get_catalog
from app.config import settings
from app.core.clock import Clock, OffsetClock, SystemClock
from app.gateway.notify import WebPushSender
from app.gateway.service import GatewayService
from app.gateway.store import GatewayStore
from app.trust.keys import GatewayKeys
from app.trust.registry import Registry
from app.upstream.client import FixtureUpstream, Upstream, ValioClient


def build_upstream_and_clock() -> tuple[Upstream, Clock]:
    if settings.upstream_mode == "fixture":  # B6: recorded API answers, clock starts at the recording time
        fixture = json.loads(settings.fixture_file.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(settings.clock_start or fixture["timeNow"])
        return FixtureUpstream(fixture["availability"], fixture["price"]), OffsetClock(start)
    upstream = ValioClient(settings.valio_api_base_url, settings.valio_api_key, cache_ttl_seconds=settings.upstream_cache_ttl_seconds)
    clock: Clock = OffsetClock(datetime.fromisoformat(settings.clock_start)) if settings.clock_start else SystemClock()
    return upstream, clock


def build_service() -> GatewayService:
    upstream, clock = build_upstream_and_clock()
    keys = GatewayKeys.load(settings.keys_dir)
    conn = connect(settings.db_path)
    audit = AuditLog(
        AuditStore(conn), clock, keys.audit,
        checkpoint_every_events=settings.checkpoint_every_events,
        checkpoint_every_minutes=settings.checkpoint_every_minutes,
    )
    return GatewayService(
        settings=settings,
        catalog=get_catalog(settings.data_dir),
        upstream=upstream,
        clock=clock,
        audit=audit,
        keys=keys,
        registry=Registry.load(settings.registry_path),
        store=GatewayStore(conn),
        push_sender=WebPushSender(settings.keys_dir / "vapid.pem", settings.vapid_subject),
    )


app = create_app(build_service(), housekeeping_seconds=30)
