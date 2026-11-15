"""Backend additions for the frontend (frontend.md §4.6, B1–B7)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.audit import events as ev
from app.audit.verify import verify_range
from tests.test_gateway import ARLA, CUSTOMER, SPEC, FakePush, World

ARLA_3000 = {**ARLA, "quantity": {"value": 3000, "unit": "L"}}
SUB = {"endpoint": "https://push.example/sub/chef", "keys": {"p256dh": "BPk", "auth": "a1"}}


@pytest.fixture
def world(catalog, upstream, clock, conn, keys):
    return World(catalog, upstream, clock, conn, keys, push=FakePush())


def session(w, persona: str) -> str:
    return w.client.post("/dev/session", json={"persona": persona}).json()["token"]


# --------------------------------------------------------------------------- B1, B2


def test_B1_cors_allows_the_frontend_origin(world):
    r = world.client.options("/v1/approvals", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
                                                        "Access-Control-Request-Headers": "authorization"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = world.client.options("/v1/approvals", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in other.headers


def test_B2_demo_session_signs_in_a_persona(world):
    personas = world.client.get("/dev/personas").json()
    assert {p["id"] for p in personas} == {"u_chef", "u_fin", "u_valio"}
    r = world.client.post("/dev/session", json={"persona": "u_chef"}).json()
    assert r["person"]["displayName"] == "Head Chef" and r["person"]["role"] == "approver"
    assert world.client.get("/v1/approvals", headers=world.h(r["token"])).status_code == 200
    world.clock.advance(hours=13)  # sessions are short-lived
    assert world.client.get("/v1/approvals", headers=world.h(r["token"])).status_code == 401


def test_B2_demo_endpoints_do_not_exist_outside_demo_mode(world):
    world.service.settings.demo_mode = False
    assert world.client.get("/dev/personas").status_code == 404
    assert world.client.post("/dev/session", json={"persona": "u_chef"}).status_code == 404


# --------------------------------------------------------------------------- B3, B4


def test_B3_view_carries_ready_made_texts(world):
    r = world.buy(ARLA).json()
    line = r["lines"][0]
    assert line["plans"][0]["rationaleText"].startswith("cheapest complete plan")
    assert line["selectionText"] == "the highest-ranked plan, and every guardrail rule passed"
    assert line["candidateCounts"]["substitutePool"] == 30
    assert r["title"].startswith("1,000 L Arla") and r["request"]["lines"][0]["productId"] == "469363"
    assert r["closed"]["outcome"] == "ORDERED"


def test_B4_summaries_for_the_audit_overview(world):
    world.buy(SPEC)
    world.buy(ARLA_3000, request_id="req_002")
    rows = {r["transactionId"]: r for r in world.client.get("/v1/audit/transactions", headers=world.h(world.approver_token)).json()}
    assert rows["req_001"]["outcome"] == "ORDERED" and rows["req_001"]["decidedBy"] == "agent"
    assert rows["req_001"]["title"] == "1,000 L lactose-free semi skimmed milk" and rows["req_001"]["total"] == "1010.00"
    assert rows["req_002"]["outcome"] == "PENDING_APPROVAL" and rows["req_002"]["requiredRole"] == "approver"
    assert rows["req_002"]["total"] == "3030.00"


# --------------------------------------------------------------------------- B5 and transaction verification


def test_transaction_verify_in_buyer_view(world):
    world.buy(SPEC)
    v = world.client.get("/v1/audit/transactions/req_001/verify", headers=world.h(world.approver_token)).json()
    assert v["result"]["ok"] is True and v["result"]["checkpointSeq"] is not None
    assert v["steps"] and all(s["ok"] for s in v["steps"])


def test_B5_tamper_preview_fails_without_touching_the_database(world):
    world.buy(SPEC)
    staff = world.h(world.staff_token)
    steps = world.client.get("/v1/audit/transactions/req_001/verify", headers=staff).json()["steps"]
    target = steps[3]["seq"]
    r = world.client.post("/v1/audit/tamper-preview", json={"transactionId": "req_001", "seq": target}, headers=staff).json()
    assert r["result"]["ok"] is False and r["result"]["errorSeq"] == target
    assert [s["ok"] for s in r["steps"]][3:] == [False] * (len(steps) - 3)
    assert verify_range(world.audit.store, 1, world.audit.store.head().seq, world.service.keys.jwks).ok  # unchanged
    assert world.client.post("/v1/audit/tamper-preview", json={"transactionId": "req_001", "seq": target},
                             headers=world.h(world.approver_token)).status_code == 403


# --------------------------------------------------------------------------- B6


def test_B6_offset_clock_runs_from_its_start():
    from datetime import datetime

    from app.core.clock import OffsetClock

    start = datetime.fromisoformat("2026-11-15T00:17:00+02:00")
    clock = OffsetClock(start)
    assert timedelta(0) <= clock.now() - start < timedelta(seconds=5)


# --------------------------------------------------------------------------- B7 notifications


def subscribe(w, persona: str, endpoint: str) -> None:
    r = w.client.post("/v1/me/push-subscriptions", json={**SUB, "endpoint": endpoint}, headers=w.h(session(w, persona)))
    assert r.status_code == 200, r.text


def notifications(w) -> list[dict]:
    return [e.payload for e in w.audit.store.of_type(ev.NOTIFICATION_SENT)]


def test_B7_request_is_pushed_to_everyone_with_a_sufficient_role(world):
    subscribe(world, "u_chef", "https://push.example/chef")
    subscribe(world, "u_fin", "https://push.example/fin")
    world.buy(ARLA_3000)  # €3,030 > €2,000: needs an approver; finance lead (admin) also qualifies
    endpoints = sorted(s["endpoint"] for s, _ in world.push.sent)
    assert endpoints == ["https://push.example/chef", "https://push.example/fin"]
    _, msg = world.push.sent[0]
    assert msg["title"] == "Approval needed · €3,030.00"
    assert "above your agent's €2,000 limit" in msg["body"] and msg["url"].startswith("/approvals/apr_")
    assert world.approver_token not in str(msg) and "token" not in str(msg).lower()
    assert notifications(world)[0] | {"recipients": None} == {"approvalId": msg["approvalId"], "kind": "request",
                                                              "channel": "web_push", "recipients": None, "outcome": "sent"}


def test_B7_admin_requests_skip_the_kitchen_manager(world):
    subscribe(world, "u_chef", "https://push.example/chef")
    subscribe(world, "u_fin", "https://push.example/fin")
    world.buy({**SPEC, "quantity": {"value": 6000, "unit": "L"}})  # needs admin
    assert [s["endpoint"] for s, _ in world.push.sent] == ["https://push.example/fin"]


def test_B7_decided_notice_goes_to_the_others_only(world):
    subscribe(world, "u_chef", "https://push.example/chef")
    subscribe(world, "u_fin", "https://push.example/fin")
    ap = world.buy(ARLA_3000).json()["approval"]
    world.push.sent.clear()
    world.decide(ap["approvalId"], {"action": "approve"})
    assert [(s["endpoint"], m["kind"]) for s, m in world.push.sent] == [("https://push.example/fin", "decided")]
    assert world.push.sent[0][1]["title"] == "Approval approved by Head Chef"


def test_B7_nobody_reachable_is_recorded(world):
    world.buy(ARLA_3000)
    assert notifications(world)[-1]["outcome"] == "no_recipient"


def test_B7_reminder_once_before_the_deadline(world):
    subscribe(world, "u_chef", "https://push.example/chef")
    ap = world.buy(ARLA_3000).json()["approval"]
    from datetime import datetime

    world.clock.set(datetime.fromisoformat(ap["deadline"]) - timedelta(minutes=59))
    world.service.expire_due()
    world.service.expire_due()
    kinds = [m["kind"] for _, m in world.push.sent]
    assert kinds == ["request", "reminder"]


def test_B7_failed_push_is_logged_as_failed(world):
    subscribe(world, "u_chef", "https://push.example/chef")
    world.push.fail = True
    world.buy(ARLA_3000)
    assert [n["outcome"] for n in notifications(world)] == ["failed"]


def test_B7_webhook_channel(catalog, upstream, clock, conn, keys):
    calls = []
    w = World(catalog, upstream, clock, conn, keys, push=FakePush(), webhook=lambda url, payload: calls.append((url, payload)))
    w.registry.customers[0].webhook_url = "https://hooks.example/procurement"
    w.buy(ARLA_3000)
    assert calls and calls[0][0] == "https://hooks.example/procurement" and calls[0][1]["customer"] == CUSTOMER
    assert notifications(w)[-1]["channel"] == "webhook" and notifications(w)[-1]["outcome"] == "sent"


def test_B7_subscription_validation_and_me(world):
    token = session(world, "u_chef")
    bad = world.client.post("/v1/me/push-subscriptions", json={**SUB, "endpoint": "http://insecure.example"}, headers=world.h(token))
    assert bad.status_code == 400
    staff = session(world, "u_valio")
    assert world.client.post("/v1/me/push-subscriptions", json=SUB, headers=world.h(staff)).status_code == 403
    world.client.post("/v1/me/push-subscriptions", json=SUB, headers=world.h(token))
    me = world.client.get("/v1/me", headers=world.h(token)).json()
    assert me["channels"]["webPush"] == 1 and me["pushAvailable"] is True
    assert world.client.get("/.well-known/push-key").json() == {"publicKey": "test-vapid-public-key"}
