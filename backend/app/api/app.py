"""HTTP interface of the VeriPantry gateway. Thin: all logic lives in GatewayService."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from app.audit.pdf import render_report_pdf
from app.audit.render import render_report
from app.audit.verify import verify_range
from app.audit.views import view_events
from app.core.jcs import to_jsonable
from app.gateway.errors import ApiError
from app.gateway.service import BUDGETS, SEARCH_LIMIT, GatewayService
from app.trust.mandates import AgentPrincipal, TrustError, verify_access_token
from app.trust.registry import HumanEntry
from app.trust.tiers import WITHHELD_FIELDS


def create_app(service: GatewayService) -> FastAPI:
    app = FastAPI(
        title="VeriPantry Agent Gateway",
        version="0.1.0",
        description="Open, verifiable interface for external purchasing agents (see docs/trust-protocol.md).",
    )
    app.state.service = service

    @app.exception_handler(ApiError)
    async def _problem(_: Request, exc: ApiError):
        return JSONResponse(exc.problem(), status_code=exc.status, media_type="application/problem+json")

    # ------------------------------------------------------------------ authentication

    def _bearer(authorization: str | None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise ApiError(401, "token_missing", "Bearer token required")
        return authorization.split(" ", 1)[1].strip()

    def caller(authorization: str | None = Header(default=None)) -> AgentPrincipal | HumanEntry:
        token = _bearer(authorization)
        human = service.registry.human_by_token(token)
        if human:
            return human
        try:
            return verify_access_token(token, service.keys.jwks, service.issuer, service.registry, service.clock.now())
        except TrustError as exc:
            raise ApiError(exc.status, exc.code, "Authentication failed", exc.detail)

    def agent(c=Depends(caller)) -> AgentPrincipal:
        if not isinstance(c, AgentPrincipal):
            raise ApiError(403, "agent_required", "This operation is for purchasing agents")
        return c

    def approver(c=Depends(caller)) -> HumanEntry:
        if not isinstance(c, HumanEntry) or c.kind != "approver":
            raise ApiError(403, "approver_required", "This operation is for the buyer's approvers")
        return c

    def audit_scope(c, tx_id: str | None = None) -> tuple[str, str | None]:
        """Return (view, customer) the caller is entitled to."""
        if isinstance(c, HumanEntry) and c.kind == "staff":
            return "valio", None
        customer = c.customer
        if tx_id is not None:
            row = service.store.get_transaction(tx_id)
            if row is None or row["customer"] != customer:
                raise ApiError(404, "not_found", "Transaction not found")
        return "buyer", customer

    # ------------------------------------------------------------------ discovery (trust-protocol §8)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "products": len(service.catalog.products), "customers": len(service.registry.customers)}

    @app.get("/.well-known/jwks.json")
    def jwks() -> dict:
        return {"keys": service.keys.jwks}

    @app.get("/.well-known/agent-interface.json")
    def agent_interface() -> dict:
        base = service.issuer
        return {
            "issuer": base,
            "openapi": f"{base}/openapi.json",
            "jwks_uri": f"{base}/.well-known/jwks.json",
            "token_endpoint": f"{base}/oauth/token",
            "grant_types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            "token_binding": "cnf.jkt (DPoP proof per request: planned, see trust-protocol §12)",
            "authorization_details_types": ["veripantry_procurement"],
            "actions": ["catalog.search", "offer.request", "order.place"],
            "data_tiers": {"T0": "catalog", "T1": "customer", "T2": "internal"},
            "withheld_fields": WITHHELD_FIELDS,
            "limits": {"search_results_max": SEARCH_LIMIT, "offer_lines_per_request_max": 50, "budgets_per_hour": BUDGETS},
            "offer_signing": {"format": "JWS", "alg": "EdDSA"},
            "audit": {"chain": "sha256+jcs", "receipts": True},
            "documentation": ["docs/trust-protocol.md", "docs/fulfilment-and-substitution.md", "docs/guardrails.md", "docs/audit-log.md"],
        }

    @app.post("/oauth/token")
    def token(grant_type: str = Form(...), assertion: str = Form(...), client_assertion: str = Form(...)) -> dict:
        return service.issue_token(grant_type, assertion, client_assertion)

    # ------------------------------------------------------------------ agent operations

    @app.post("/v1/catalog/search")
    def search(body: dict[str, Any], p: AgentPrincipal = Depends(agent)) -> dict:
        return service.search(p, body)

    @app.post("/v1/availability-check")
    def availability_check(body: dict[str, Any], p: AgentPrincipal = Depends(agent)) -> dict:
        return service.availability_check(p, body)

    @app.post("/v1/purchase-requests")
    def submit(body: dict[str, Any], p: AgentPrincipal = Depends(agent)) -> dict:
        return service.submit(p, body)

    @app.get("/v1/purchase-requests/{tx_id}")
    def get_purchase(tx_id: str, c=Depends(caller)) -> dict:
        service.expire_due()
        audit_scope(c, tx_id)
        return service.transaction_view(tx_id)

    # ------------------------------------------------------------------ approvals (guardrails §8)

    @app.get("/v1/approvals")
    def approvals(state: str | None = Query(default=None), h: HumanEntry = Depends(approver)) -> list:
        return service.approvals_for(h, state)

    @app.get("/v1/approvals/{approval_id}")
    def approval(approval_id: str, h: HumanEntry = Depends(approver)) -> dict:
        return service.get_approval(h, approval_id)

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide(approval_id: str, body: dict[str, Any], h: HumanEntry = Depends(approver)) -> dict:
        return service.decide(h, approval_id, body)

    # ------------------------------------------------------------------ audit (audit-log §9)

    @app.get("/v1/audit/transactions")
    def list_transactions(outcome: str | None = None, c=Depends(caller)) -> list:
        _, customer = audit_scope(c)
        rows = service.store.transactions(customer)
        return [{"transactionId": r["id"], "customer": r["customer"], "state": r["state"], "createdAt": r["created_at"]}
                for r in rows if outcome is None or r["state"] == outcome]

    @app.get("/v1/audit/transactions/{tx_id}")
    def transaction_events(tx_id: str, c=Depends(caller)) -> dict:
        view, customer = audit_scope(c, tx_id)
        items, checkpoint = view_events(service.audit.store, tx_id, view, customer)
        return {"transactionId": tx_id, "view": view, "events": to_jsonable(items), "checkpoint": to_jsonable(checkpoint)}

    @app.get("/v1/audit/transactions/{tx_id}/report")
    def report(tx_id: str, view: str = "buyer", format: str = "md", c=Depends(caller)):
        if view not in ("buyer", "valio"):
            raise ApiError(400, "invalid_view", "view must be buyer or valio")
        if format not in ("md", "html", "pdf"):
            raise ApiError(400, "invalid_format", "format must be md, html or pdf")
        allowed_view, customer = audit_scope(c, tx_id)
        if view == "valio" and allowed_view != "valio":
            raise ApiError(403, "valio_view_restricted", "The Valio view is for Valio Aimo staff")
        if format == "pdf":
            pdf = render_report_pdf(service.audit.store, tx_id, view, customer, service.keys.jwks)
            filename = "audit-report-" + re.sub(r"[^A-Za-z0-9_.-]", "_", tx_id) + f"-{view}.pdf"
            return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        body = render_report(service.audit.store, tx_id, view, customer, service.keys.jwks, fmt=format)
        return HTMLResponse(body) if format == "html" else PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @app.get("/v1/audit/verify")
    def verify(fromSeq: int, toSeq: int, c=Depends(caller)) -> dict:
        return to_jsonable(verify_range(service.audit.store, fromSeq, toSeq, service.keys.jwks))

    return app
