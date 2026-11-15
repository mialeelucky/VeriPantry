"""End-to-end tests through the HTTP API (trust protocol, guardrails §8 T34–T36, audit AT01–AT13).

Uses recorded upstream data, a fixed clock and an in-memory database.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.audit import events as ev
from app.audit.store import AuditStore
from app.audit.log import AuditLog
from app.config import Settings
from app.gateway.service import GatewayService
from app.gateway.store import GatewayStore
from app.guardrails.models import Policy
from app.trust.devkit import make_client_assertion, make_customer, make_human, make_mandate
from app.trust.keys import generate_key, verify_jws
from app.trust.registry import Registry

AUD = "http://testserver"
CUSTOMER = "customer:HOTEL-123"
AGENT = "agent:hotel-123-procurement-01"

ARLA = {"lineId": "L1", "productId": "469363",
        "spec": {"requiredAttributes": ["FREE_FROM_LACTOSE"], "preferredAttributes": ["brand:Arla", "fat:1.5"]},
        "quantity": {"value": 1000, "unit": "L"}}
SPEC = {"lineId": "L1", "spec": {"query": "semi skimmed milk", "category": "10400", "requiredAttributes": ["FREE_FROM_LACTOSE"]},
        "quantity": {"value": 1000, "unit": "L"}}


class FakePush:
    """Records what would be pushed to each subscribed device."""

    public_key = "test-vapid-public-key"

    def __init__(self):
        self.sent: list[tuple[dict, dict]] = []
        self.fail = False

    def __call__(self, subscription: dict, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("push service unavailable")
        self.sent.append((subscription, payload))


class World:
    def __init__(self, catalog, upstream, clock, conn, keys, policy: Policy | None = None, limits=None, push=None, webhook=None):
        self.clock = clock
        customer, self.org = make_customer(CUSTOMER, "Hotel 123")
        self.approver, self.approver_token = make_human("u_chef", "Head Chef", "approver", "approver", CUSTOMER)
        self.admin, self.admin_token = make_human("u_fin", "Finance Lead", "approver", "admin", CUSTOMER)
        self.staff, self.staff_token = make_human("u_valio", "Valio Auditor", "staff", None, None)
        self.registry = Registry(customers=[customer], humans=[self.approver, self.admin, self.staff])
        settings = Settings(public_base_url=AUD, valio_api_base_url="", valio_api_key="", demo_mode=True, notify_async=False)
        self.audit = AuditLog(AuditStore(conn), clock, keys.audit)
        self.push = push
        self.service = GatewayService(settings, catalog, upstream, clock, self.audit, keys, self.registry, GatewayStore(conn),
                                      policies={CUSTOMER: policy or Policy(scope={"categories": ["104"]})},
                                      push_sender=push, webhook_sender=webhook)
        self.client = TestClient(create_app(self.service))
        self.agent_key = generate_key()
        self.mandate = make_mandate(self.org, CUSTOMER, AGENT, self.agent_key, AUD, clock.now(), limits=limits)
        self.token = self.get_token()

    def get_token(self, mandate=None, agent_key=None):
        r = self.client.post("/oauth/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": mandate or self.mandate,
            "client_assertion": make_client_assertion(agent_key or self.agent_key, AGENT, AUD, self.clock.now()),
        })
        return r.json().get("access_token") if r.status_code == 200 else r

    def h(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def buy(self, line, request_id="req_001", text=None, **kw):
        body = {"request": {"requestId": request_id, "customer": CUSTOMER, "deliverBy": "2026-11-16", "lines": [line], **kw},
                "purpose": "quote_for_order", "originalText": text}
        return self.client.post("/v1/purchase-requests", json=body, headers=self.h())

    def report(self, tx="req_001", view="buyer", token=None):
        return self.client.get(f"/v1/audit/transactions/{tx}/report", params={"view": view}, headers=self.h(token or self.approver_token))

    def decide(self, approval_id, body, token=None):
        return self.client.post(f"/v1/approvals/{approval_id}/decision", json=body, headers=self.h(token or self.approver_token))


@pytest.fixture
def world(catalog, upstream, clock, conn, keys):
    return World(catalog, upstream, clock, conn, keys)


# --------------------------------------------------------------------------- trust protocol


def test_discovery_documents(world):
    doc = world.client.get("/.well-known/agent-interface.json").json()
    assert doc["token_endpoint"].endswith("/oauth/token")
    assert len(world.client.get("/.well-known/jwks.json").json()["keys"]) == 2


def test_token_requires_the_agent_key_bound_in_the_mandate(world):
    r = world.get_token(agent_key=generate_key())
    assert r.status_code == 401 and r.json()["type"].endswith("agent-key-invalid")


def test_revoked_mandate_is_refused(world):
    jti = jwt.decode(world.mandate, options={"verify_signature": False})["jti"]
    world.registry.revoked_mandates.append(jti)
    assert world.client.post("/v1/catalog/search", json={"query": "milk"}, headers=world.h()).status_code == 401


def test_search_is_bounded_and_tiered(world):
    assert world.client.post("/v1/catalog/search", json={}, headers=world.h()).status_code == 400  # R2
    r = world.client.post("/v1/catalog/search", json={"query": "milk", "limit": 500}, headers=world.h()).json()
    assert len(r["results"]) <= 25
    assert "vendorName" not in str(r) and "VALIO OY" not in str(r)  # T2 never leaves the gateway


def test_availability_is_question_shaped_and_session_bound(world):
    s = world.client.post("/v1/catalog/search", json={"query": "semi skimmed milk", "category": "10400",
                                                      "requiredAttributes": ["FREE_FROM_LACTOSE"]}, headers=world.h()).json()
    body = {"searchId": s["searchId"], "deliverBy": "2026-11-16", "items": [{"productId": "469363", "quantity": {"value": 1000, "unit": "L"}}]}
    a = world.client.post("/v1/availability-check", json=body, headers=world.h()).json()["items"][0]
    assert a["fulfilment"] == "partial" and Decimal(a["confirmed"]["value"]) == 384  # what can be confirmed, capped at the request
    too_much = {**body, "items": [{"productId": "469363", "quantity": {"value": 1600, "unit": "L"}}]}
    r = world.client.post("/v1/availability-check", json=too_much, headers=world.h())
    assert r.status_code == 403 and r.json()["limit"] == "maxQtyPerLine"  # trust-protocol §4.4
    other = {**body, "items": [{"productId": "460027", "quantity": {"value": 1, "unit": "KG"}}]}
    assert world.client.post("/v1/availability-check", json=other, headers=world.h()).status_code == 403  # R3


# --------------------------------------------------------------------------- autonomous orders


def test_AT01_spec_request_ordered_autonomously(world, keys):
    r = world.buy(SPEC, text="We need 1,000 litres of lactose-free semi-skimmed milk by Monday.").json()
    assert r["status"] == "ORDERED"
    assert r["order"]["approval"] == "auto" and r["order"]["total"] == "1010.00"
    # Every offer is a JWS verifiable with the published keys.
    for jws in r["offers"].values():
        assert verify_jws(jws, keys.jwks, audience=AGENT)["sub"] == CUSTOMER
    plan = r["lines"][0]["plans"][0]
    assert "confirmedSalesUnits" not in plan["items"][0] and "reliability" not in plan["items"][0]
    md = world.report().text
    assert "**ORDERED** (auto_approved)" in md and "Not required: within the agent's autonomous authority." in md
    assert "Verification FAILED" not in md and "verified" in md


def test_scenario2_specific_product_substituted_autonomously(world):
    r = world.buy(ARLA).json()
    assert r["status"] == "ORDERED"
    assert [l["productId"] for l in r["order"]["lines"]] == ["464306"]


def test_AT15_report_explains_ranking_and_selection(world):
    world.buy(ARLA)
    md = world.report().text
    assert "Why each plan holds its rank" in md
    assert "cheapest complete plan" in md and "keeps the requested product for 384 L (38 %)" in md
    assert "strategy-diversity rule" in md
    assert "Selected: Best plan. Why: the highest-ranked plan, and every guardrail rule passed." in md


def test_AT12_report_rendering_is_deterministic(world):
    world.buy(SPEC)
    assert world.report().text == world.report().text


# --------------------------------------------------------------------------- human approval


@pytest.fixture
def strict_world(catalog, upstream, clock, conn, keys):
    policy = Policy(scope={"categories": ["104"]}, substitution={"flexibleAttributes": []})
    return World(catalog, upstream, clock, conn, keys, policy=policy)


def test_AT02_inflexible_brand_goes_to_approval_then_human_approves(strict_world):
    w = strict_world
    r = w.buy(ARLA).json()
    assert r["status"] == "PENDING_APPROVAL" and r["approval"]["requiredRole"] == "approver"
    ap = w.client.get("/v1/approvals", headers=w.h(w.approver_token)).json()[0]
    assert ap["lines"][0]["recommendedRank"] == 1
    assert "GR-X4" in str(ap["lines"][0]["plans"][0]["guardrail"])
    done = w.decide(ap["approvalId"], {"action": "approve", "planRanks": {"L1": 1}}).json()
    assert done["status"] == "ORDERED" and done["order"]["approval"] == ap["approvalId"]
    md = w.report().text
    assert "**Head Chef** (approver) approved" in md and "satisfied by approval" in md


def test_AT04_rejection_is_reported(strict_world):
    w = strict_world
    ap = w.buy(ARLA).json()["approval"]
    assert w.decide(ap["approvalId"], {"action": "reject"}).status_code == 400  # reason required
    assert w.decide(ap["approvalId"], {"action": "reject", "reason": "We only buy Arla."}).json()["status"] == "REJECTED"
    assert "We only buy Arla." in w.report().text


def test_T34_role_too_low_is_refused(world):
    r = world.buy({**SPEC, "quantity": {"value": 6000, "unit": "L"}}).json()  # €6,060 > €5,000
    assert r["approval"]["requiredRole"] == "admin"
    refused = world.decide(r["approval"]["approvalId"], {"action": "approve"})
    assert refused.status_code == 403 and refused.json()["type"].endswith("insufficient-role")
    ok = world.decide(r["approval"]["approvalId"], {"action": "approve"}, token=world.admin_token).json()
    assert ok["status"] == "ORDERED"


def test_T35_T36_AT05_silence_expires_requotes_then_closes(strict_world):
    w = strict_world
    first = w.buy(ARLA).json()["approval"]
    w.clock.set(w.clock.now().replace(hour=17, minute=1))  # past cut-off, offers and deadline
    late = w.decide(first["approvalId"], {"action": "approve"})
    assert late.status_code == 409  # expired: never approved by silence or after the deadline
    tx = w.client.get("/v1/purchase-requests/req_001", headers=w.h(w.approver_token)).json()
    types = [e.type for e in w.audit.store.for_transaction("req_001")]
    assert ev.APPROVAL_EXPIRED in types and ev.REQUOTE_STARTED in types
    if tx["status"] == "PENDING_APPROVAL":  # re-quote produced a new approval request
        w.clock.advance(days=1)
        w.service.expire_due()
        tx = w.client.get("/v1/purchase-requests/req_001", headers=w.h(w.approver_token)).json()
    assert tx["status"] in ("EXPIRED", "DENIED", "UNFULFILLABLE")
    assert "APPROVED" not in [a["state"] for a in w.client.get("/v1/approvals", headers=w.h(w.approver_token)).json()]


def test_modify_supersedes_and_continues(strict_world):
    w = strict_world
    ap = w.buy(ARLA).json()["approval"]
    r = w.decide(ap["approvalId"], {"action": "modify", "changes": {"lines": [{"lineId": "L1", "quantity": {"value": 300, "unit": "L"}}]}}).json()
    assert r["transactionId"] == "req_001-m1"
    assert r["status"] == "ORDERED"  # 300 L of the requested Arla product is available: no substitution needed
    assert w.service.store.get_transaction("req_001")["state"] == "SUPERSEDED"


# --------------------------------------------------------------------------- failures and safety


def test_milk_allergy_never_receives_milk(world):
    r = world.buy({**SPEC, "spec": {**SPEC["spec"], "excludedAllergens": ["AM"]}}).json()
    items = [i for p in r["lines"][0]["plans"] for i in p["items"]]
    assert items and all(i["allergens"]["AM"] == "free_from" for i in items)
    assert r["status"] == "PENDING_APPROVAL"  # plant drinks are a different category (S2)


def test_AT06_unfulfillable(world):
    line = {**SPEC, "spec": {**SPEC["spec"], "requiredAttributes": ["FREE_FROM_LACTOSE", "MARINE_STEWARDSHIP_COUNCIL_LABEL"]}}
    assert world.buy(line).json()["status"] == "UNFULFILLABLE"
    assert "No acceptable option exists" in world.report().text


def test_AT07_upstream_failure_is_closed_and_reported(world, upstream):
    upstream.fail = True
    r = world.buy(SPEC)
    assert r.status_code == 502 and r.json()["transactionId"] == "req_001"
    assert world.service.store.get_transaction("req_001")["state"] == "FAILED"
    assert "**FAILED** (upstream_unavailable)" in world.report().text


def test_AT08_watchdog_closes_abandoned_transactions(world):
    from app.gateway.service import TxCtx
    from app.guardrails.models import MandateInfo

    m = MandateInfo(id="mdt_x", customer=CUSTOMER, agent=AGENT, expires_at=world.clock.now() + timedelta(days=1))
    world.service.store.create_transaction("req_crash", CUSTOMER, AGENT, world.clock.now(), {"mandate": m})
    world.service._log(TxCtx("req_crash", CUSTOMER, AGENT, m), ev.REQUEST_RECEIVED, ev.SYSTEM, {"request": {"lines": [], "deliverBy": "2026-11-16"}})
    world.clock.advance(hours=25)
    assert world.service.run_watchdog() == 1
    assert world.service.store.get_transaction("req_crash")["state"] == "FAILED"


def test_AT11_buyer_report_hides_valio_details_staff_sees_them(world):
    world.buy(SPEC)
    buyer = world.report().text
    assert "Internal step" in buyer and "Data disclosure" not in buyer
    assert world.report(view="valio").status_code == 403
    valio = world.report(view="valio", token=world.staff_token).text
    assert "Data disclosure (Valio view)" in valio and "upstream availability" in valio


def test_AT13_no_secrets_in_audit_log(world, conn):
    world.buy(SPEC)
    blob = " ".join(r[0] for r in conn.execute("SELECT payload FROM audit_events"))
    assert world.token not in blob and world.mandate not in blob
    assert world.approver_token not in blob and "-----BEGIN" not in blob


def test_whole_chain_verifies_after_a_session(world):
    world.buy(SPEC)
    world.buy(ARLA, request_id="req_002")
    head = world.audit.store.head().seq
    v = world.client.get("/v1/audit/verify", params={"fromSeq": 1, "toSeq": head}, headers=world.h(world.staff_token)).json()
    assert v["ok"] is True


# --------------------------------------------------------------------------- PDF export (audit-log §7.1)


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_pdf_report_one_click(world):
    world.buy(ARLA, text="We need 1,000 litres of Arla lactose-free milk by Monday.")
    r = world.client.get("/v1/audit/transactions/req_001/report", params={"format": "pdf"}, headers=world.h(world.approver_token))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="audit-report-req_001-buyer.pdf"'
    assert r.content.startswith(b"%PDF")
    text = _pdf_text(r.content)
    for expected in ("Transaction report: req_001", "ORDERED", "€1,010.00", "keeps the requested product", "verified"):
        assert expected in text, expected


def test_pdf_is_deterministic_and_access_controlled(world):
    world.buy(SPEC)
    get = lambda **p: world.client.get("/v1/audit/transactions/req_001/report", params={"format": "pdf", **p}, headers=world.h(world.approver_token))  # noqa: E731
    assert get().content == get().content  # same events, same bytes (AT12 for PDF)
    assert get(view="valio").status_code == 403
    assert world.client.get("/v1/audit/transactions/req_001/report", params={"format": "docx"}, headers=world.h(world.approver_token)).status_code == 400


def test_agent_text_cannot_inject_markup_into_reports(world):
    payload = "<img src='file:///C:/Windows/win.ini'><script>alert(1)</script>"
    world.buy(SPEC, text=payload)
    html_report = world.client.get("/v1/audit/transactions/req_001/report", params={"format": "html"}, headers=world.h(world.approver_token)).text
    assert "<script>" not in html_report and "<img" not in html_report
    assert "&lt;script&gt;" in html_report
    pdf = world.client.get("/v1/audit/transactions/req_001/report", params={"format": "pdf"}, headers=world.h(world.approver_token))
    assert pdf.status_code == 200 and "<script>alert(1)</script>" in _pdf_text(pdf.content)  # shown as text, not executed


def test_pdf_converter_refuses_external_resources():
    from app.audit.pdf import html_to_pdf

    # Even raw markup that bypassed escaping cannot make the converter read local files.
    pdf = html_to_pdf("<p>x</p><img src='file:///C:/Windows/win.ini'/>", footer="t")
    assert pdf.startswith(b"%PDF") and b"[fonts]" not in pdf


def test_buyers_cannot_read_other_customers_transactions(world, catalog, upstream, clock):
    world.buy(SPEC)
    other, _ = make_human("u_x", "Other", "approver", "admin", "customer:OTHER")
    world.registry.humans.append(other)
    _, token = other, None
    entry, tok = make_human("u_y", "Other2", "approver", "admin", "customer:OTHER")
    world.registry.humans.append(entry)
    assert world.client.get("/v1/purchase-requests/req_001", headers=world.h(tok)).status_code == 404
