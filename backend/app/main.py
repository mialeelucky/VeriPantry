"""Production entry point: ``uvicorn app.main:app``.

Wires the real components: static catalog, live Valio APIs, SQLite in var/,
gateway keys, registry and per-customer policies.
"""

from __future__ import annotations

from app.api.app import create_app
from app.audit.log import AuditLog
from app.audit.store import AuditStore, connect
from app.catalog.catalog import get_catalog
from app.config import settings
from app.core.clock import SystemClock
from app.gateway.service import GatewayService
from app.gateway.store import GatewayStore
from app.trust.keys import GatewayKeys
from app.trust.registry import Registry
from app.upstream.client import ValioClient


def build_service() -> GatewayService:
    clock = SystemClock()
    keys = GatewayKeys.load(settings.keys_dir)
    conn = connect(settings.db_path)
    audit = AuditLog(
        AuditStore(conn), clock, keys.audit,
        checkpoint_every_events=settings.checkpoint_every_events,
        checkpoint_every_minutes=settings.checkpoint_every_minutes,
    )
    upstream = ValioClient(settings.valio_api_base_url, settings.valio_api_key, cache_ttl_seconds=settings.upstream_cache_ttl_seconds)
    return GatewayService(
        settings=settings,
        catalog=get_catalog(settings.data_dir),
        upstream=upstream,
        clock=clock,
        audit=audit,
        keys=keys,
        registry=Registry.load(settings.registry_path),
        store=GatewayStore(conn),
    )


app = create_app(build_service())
