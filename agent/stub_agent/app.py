"""Stub buyer agent: the four endpoints the frontend needs (frontend.md §4.1).

    uvicorn stub_agent.app:app --port 8100      (from the agent/ folder)

It understands sentences without an LLM (scenarios + rules) and submits
confirmed requests to the gateway with its own key and mandate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from stub_agent.config import AgentSettings, settings
from stub_agent.gateway_client import GatewayClient, GatewayError, load_key
from stub_agent.understand import scenarios, understand


def create_app(cfg: AgentSettings, client: GatewayClient | None = None) -> FastAPI:
    app = FastAPI(title="VeriPantry stub buyer agent", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    state: dict[str, GatewayClient] = {}

    def gateway() -> GatewayClient:
        if client is not None:
            return client
        if "client" not in state:
            if not cfg.mandate_file.exists() or not cfg.key_file.exists():
                raise GatewayError(503, {"title": "Agent is not set up", "detail": "Run backend/scripts/dev_setup.py first.", "status": 503})
            state["client"] = GatewayClient(cfg.gateway_url, cfg.gateway_audience, load_key(cfg.key_file), cfg.mandate_file.read_text().strip())
        return state["client"]

    def today() -> date:
        """Relative dates follow the gateway's clock, which may run on recorded time."""
        if cfg.today:
            return cfg.today
        try:
            return datetime.fromtimestamp(gateway()._gateway_now()).date()
        except Exception:
            return date.today()

    @app.exception_handler(GatewayError)
    async def _gateway_error(_: Request, exc: GatewayError):
        return JSONResponse(exc.problem, status_code=exc.status, media_type="application/problem+json")

    @app.get("/agent/health")
    def health() -> dict:
        g = gateway()
        return {"status": "ok", "agent": g.agent_id, "customer": g.customer}

    @app.get("/agent/scenarios")
    def list_scenarios() -> list[dict[str, Any]]:
        return scenarios(today())

    @app.post("/agent/understand")
    def understand_text(body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"title": "Describe what you need", "status": 400}, status_code=400, media_type="application/problem+json")
        return understand(text, today())

    @app.post("/agent/submit")
    def submit(body: dict[str, Any]) -> dict[str, Any]:
        g = gateway()
        request = dict(body.get("request") or {})
        request.setdefault("requestId", "req_" + datetime.now().strftime("%m%d%H%M%S%f")[:-3])
        request["customer"] = g.customer
        return g.call("POST", "/v1/purchase-requests", json={
            "request": request, "purpose": "quote_for_order", "originalText": body.get("originalText"),
        })

    @app.get("/agent/transactions/{tx_id}")
    def transaction(tx_id: str) -> dict[str, Any]:
        return gateway().call("GET", f"/v1/purchase-requests/{tx_id}")

    @app.get("/agent/transactions/{tx_id}/verify")
    def verify(tx_id: str) -> dict[str, Any]:
        return gateway().call("GET", f"/v1/audit/transactions/{tx_id}/verify")

    return app


app = create_app(settings)
