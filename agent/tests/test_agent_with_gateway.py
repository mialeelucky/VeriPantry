"""The stub agent end to end against an in-process gateway on recorded data.

Needs the backend on the import path (see conftest.py). The agent code itself
imports nothing from the backend: it uses HTTP only.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from stub_agent.app import create_app
from stub_agent.config import AgentSettings
from stub_agent.gateway_client import GatewayClient


@pytest.fixture
def agent(world):
    gw = GatewayClient("http://testserver", "http://testserver", world.agent_key, world.mandate, http=world.client)
    return TestClient(create_app(AgentSettings(today=date(2026, 11, 15)), client=gw))


def test_scenario_round_trip(agent):
    scenarios = agent.get("/agent/scenarios").json()
    s = next(x for x in scenarios if x["id"] == "arla-short")
    draft = agent.post("/agent/understand", json={"text": s["text"]}).json()["draft"]
    r = agent.post("/agent/submit", json={"request": draft, "originalText": s["text"]}).json()
    assert r["status"] == "ORDERED" and r["customer"] == "customer:HOTEL-123"
    tx = r["transactionId"]
    assert agent.get(f"/agent/transactions/{tx}").json()["order"]["total"] == "1010.00"
    assert agent.get(f"/agent/transactions/{tx}/verify").json()["result"]["ok"] is True


def test_gateway_problems_pass_through(agent):
    s = next(x for x in agent.get("/agent/scenarios").json() if x["id"] == "lactose-free")
    bad = {**s["draft"], "lines": [{**s["draft"]["lines"][0], "quantity": {"value": -5, "unit": "L"}}]}
    r = agent.post("/agent/submit", json={"request": bad})
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")


def test_empty_text_is_refused(agent):
    assert agent.post("/agent/understand", json={"text": "  "}).status_code == 400
