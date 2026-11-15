"""Test-only wiring: put the backend on the path to run an in-process gateway."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))


@pytest.fixture
def world():
    from app.catalog.catalog import get_catalog
    from app.config import DATA_DIR
    from app.core.clock import FixedClock
    from app.trust.keys import GatewayKeys
    from app.upstream.client import FixtureUpstream

    # Load the backend's test world by path: this package is also called "tests".
    spec = importlib.util.spec_from_file_location("backend_test_gateway", BACKEND / "tests" / "test_gateway.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    World = module.World

    fx = json.loads((BACKEND / "tests" / "fixtures" / "milk_2026-11-16.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    return World(get_catalog(DATA_DIR), FixtureUpstream(fx["availability"], fx["price"]),
                 FixedClock(datetime.fromisoformat(fx["timeNow"])), conn, GatewayKeys.ephemeral())
