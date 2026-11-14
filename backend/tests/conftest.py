from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.audit.log import AuditLog
from app.audit.store import AuditStore
from app.catalog.catalog import Catalog, get_catalog
from app.config import DATA_DIR
from app.core.clock import FixedClock
from app.trust.keys import GatewayKeys
from app.upstream.client import FixtureUpstream

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return get_catalog(DATA_DIR)


@pytest.fixture(scope="session")
def milk_fixture() -> dict:
    return json.loads((FIXTURES / "milk_2026-11-16.json").read_text(encoding="utf-8"))


@pytest.fixture
def upstream(milk_fixture) -> FixtureUpstream:
    return FixtureUpstream(milk_fixture["availability"], milk_fixture["price"])


@pytest.fixture
def clock(milk_fixture) -> FixedClock:
    """The server time at which the fixture was recorded."""
    return FixedClock(datetime.fromisoformat(milk_fixture["timeNow"]))


@pytest.fixture
def keys() -> GatewayKeys:
    return GatewayKeys.ephemeral()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    yield c
    c.close()


@pytest.fixture
def audit(conn, clock, keys) -> AuditLog:
    return AuditLog(AuditStore(conn), clock, keys.audit)
