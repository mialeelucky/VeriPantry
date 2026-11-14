"""The gateway: one purchase transaction from request to close.

trust-protocol (identity, tiers, signed offers) + fulfilment + guardrails
(selection, approval state machine §8) + audit (every step, §3).
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.audit import events as ev
from app.audit.events import Actor, AuditRef
from app.audit.log import AuditLog
from app.catalog.catalog import Catalog
from app.config import Settings
from app.core.clock import Clock
from app.core.contracts import FulfilmentResult, Plan, PurchaseRequest, Quantity, Rationale
from app.core.jcs import to_jsonable
from app.fulfilment.engine import FulfilmentEngine, RequestError
from app.fulfilment.feasibility import assess
from app.gateway.errors import ApiError
from app.gateway.store import TERMINAL_STATES, GatewayStore
from app.gateway.upstream_audit import AuditedUpstream
from app.guardrails.engine import evaluate
from app.guardrails.models import ROLE_RANK, Context, Decision, MandateInfo, Policy
from app.guardrails.selection import OrderDecision, decide_order
from app.trust.keys import GatewayKeys
from app.trust.mandates import AgentPrincipal, TrustError, issue_access_token, verify_client_assertion, verify_mandate
from app.trust.offers import build_offer, offer_valid_until, sign_offer
from app.trust.registry import HumanEntry, Registry
from app.trust.tiers import WITHHELD_FIELDS, catalog_view, plan_view
from app.upstream.client import Upstream, UpstreamError

SEARCH_LIMIT = 25  # R2
SEARCH_SESSION_TTL = timedelta(hours=1)  # R3
OFFER_LINES_PER_REQUEST = 50
BUDGETS = {"search": 120, "availability": 120, "purchase": 30}  # per mandate per hour (R4)
MIN_APPROVAL_WINDOW = timedelta(minutes=5)


@dataclass
class TxCtx:
    id: str
    customer: str
    agent: str
    mandate: MandateInfo


class GatewayService:
    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        upstream: Upstream,
        clock: Clock,
        audit: AuditLog,
        keys: GatewayKeys,
        registry: Registry,
        store: GatewayStore,
        policies: dict[str, Policy] | None = None,
    ):
        self.settings, self.catalog, self.upstream, self.clock = settings, catalog, upstream, clock
        self.audit, self.keys, self.registry, self.store = audit, keys, registry, store
        self.policies = policies or {}
        self._budget: dict[tuple[str, str], deque] = defaultdict(deque)

    @property
    def issuer(self) -> str:
        return self.settings.public_base_url

    def policy_for(self, customer: str) -> Policy:
        if customer in self.policies:
            return self.policies[customer]
        path = self.settings.policies_dir / f"{customer.replace(':', '_')}.json"
        if path.exists():
            self.policies[customer] = Policy.model_validate_json(path.read_text(encoding="utf-8"))
            return self.policies[customer]
        return Policy()

    # ================================================================== tokens (trust-protocol §4.3)

    def issue_token(self, grant_type: str, assertion: str, client_assertion: str) -> dict[str, Any]:
        now = self.clock.now()
        if grant_type != "urn:ietf:params:oauth:grant-type:jwt-bearer":
            raise ApiError(400, "unsupported_grant_type", "Unsupported grant type")
        try:
            mandate, jkt = verify_mandate(assertion, self.registry, self.issuer, now)
            verify_client_assertion(client_assertion, jkt, self.issuer, now)
        except TrustError as exc:
            self.audit.append(ev.AUTH_DENIED, transaction_id=None, actor=ev.GATEWAY, payload={"reason": exc.code, "detail": exc.detail})
            raise ApiError(exc.status, exc.code, "Authentication failed", exc.detail)
        token, exp = issue_access_token(self.keys.gateway, mandate, jkt, self.issuer, now, self.settings.access_token_ttl_seconds)
        ref = self.audit.append(
            ev.AUTH_TOKEN_ISSUED,
            transaction_id=None,
            actor=ev.GATEWAY,
            customer=mandate.customer,
            mandate=mandate.id,
            payload={"agent": mandate.agent, "mandate": mandate.id, "actions": mandate.actions, "limits": mandate.limits, "tokenExpiresAt": exp},
        )
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": self.settings.access_token_ttl_seconds,
            "auditRef": to_jsonable(ref),
        }

    # ================================================================== budgets (R4)

    def _spend_budget(self, principal: AgentPrincipal, kind: str) -> None:
        window = self._budget[(principal.mandate.id, kind)]
        now = time.monotonic()
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= BUDGETS[kind]:
            raise ApiError(429, "budget_exceeded", "Query budget exceeded", f"At most {BUDGETS[kind]} {kind} calls per hour per mandate.")
        window.append(now)

    @staticmethod
    def _require_action(principal: AgentPrincipal, action: str) -> None:
        if action not in principal.mandate.actions:
            raise ApiError(403, "action_not_permitted", "Action not permitted by mandate", f"The mandate does not grant {action}.")

    # ================================================================== catalog (R2, R3)

    def search(self, principal: AgentPrincipal, body: dict[str, Any]) -> dict[str, Any]:
        self._require_action(principal, "catalog.search")
        self._spend_budget(principal, "search")
        query, category = body.get("query"), body.get("category")
        if not query and not category:
            raise ApiError(400, "query_required", "A query or a category is required", "There is no 'list everything' operation (R2).")
        limit = min(int(body.get("limit", SEARCH_LIMIT)), SEARCH_LIMIT)
        results = self.catalog.search(query, category, body.get("requiredAttributes") or [], limit=limit)
        now = self.clock.now()
        search_id = f"srch_{uuid.uuid4().hex[:12]}"
        ids = [p.id for p in results]
        self.store.save_search(search_id, principal.mandate.id, ids, now + SEARCH_SESSION_TTL)
        common = {"customer": principal.customer, "mandate": principal.mandate.id, "transaction_id": None}
        ref = self.audit.append(
            ev.CATALOG_SEARCHED, actor=Actor(kind="agent", id=principal.agent), **common,
            payload={"searchId": search_id, "query": query, "filters": {"category": category, "requiredAttributes": body.get("requiredAttributes") or []},
                     "resultCount": len(ids), "productIds": ids},
        )
        self.audit.append(ev.DATA_DISCLOSED, actor=ev.GATEWAY, **common, payload={"productIds": ids, "tiers": ["T0"], "withheld": WITHHELD_FIELDS})
        return {"searchId": search_id, "expiresAt": to_jsonable(now + SEARCH_SESSION_TTL), "results": [catalog_view(p) for p in results], "auditRef": to_jsonable(ref)}

    def availability_check(self, principal: AgentPrincipal, body: dict[str, Any]) -> dict[str, Any]:
        """Question-shaped availability (R1), only for products from a search session (R3)."""
        self._require_action(principal, "offer.request")
        self._spend_budget(principal, "availability")
        now = self.clock.now()
        session = self.store.get_search(body.get("searchId", ""))
        if not session or session["mandate_id"] != principal.mandate.id or session["expires_at"] < now:
            raise ApiError(403, "search_session_required", "Unknown or expired search session", "Prices and availability are only given for products from a recent search (R3).")
        items = body.get("items") or []
        if not items or len(items) > OFFER_LINES_PER_REQUEST:
            raise ApiError(400, "invalid_items", f"Give 1–{OFFER_LINES_PER_REQUEST} items")
        deliver_by = datetime.fromisoformat(body["deliverBy"]).date()
        limit = principal.mandate.limits.get("maxQtyPerLine")
        for it in items:
            if it["productId"] not in session["product_ids"]:
                raise ApiError(403, "product_not_in_search", "Product not in search session", it["productId"])
            if limit is not None and Decimal(str(it["quantity"]["value"])) > Decimal(str(limit)):
                raise ApiError(403, "mandate_limit_exceeded", "Request exceeds mandate limit", limit="maxQtyPerLine",
                               allowed=limit, requested=it["quantity"]["value"], mandate=principal.mandate.id)
        ids = [it["productId"] for it in items]
        audited = AuditedUpstream(self.upstream, self.audit, None, principal.customer, principal.mandate.id)
        avail, prices = audited.availability(ids, deliver_by), audited.price(ids, deliver_by)
        answers = []
        for it in items:
            q = Quantity.model_validate(it["quantity"])
            a = assess(self.catalog.get(it["productId"]), avail.get(it["productId"]), prices.get(it["productId"]), q.unit, q.value, deliver_by, now, self.settings.cutoff_policy)
            fulfilment = {"on_time": "full", "on_time_partial": "partial", "quantity_unconfirmed": "unconfirmed"}.get(a.status, "none" if a.status in ("not_deliverable", "blocked", "no_price") else a.status)
            confirmed = q.value if a.confirmed_sales_units is None or not a.content else min(q.value, a.confirmed_sales_units * a.content)
            answers.append(to_jsonable({
                "productId": it["productId"], "fulfilment": fulfilment, "requested": q,
                "confirmed": {"value": confirmed, "unit": q.unit} if fulfilment in ("full", "partial") else None,
                "availableDate": a.available_date,
                "stockBasis": {"known": "warehouse", "ample": "warehouse", "unconfirmed": "supplier-direct"}[a.basis],
            }))
        ref = self.audit.append(ev.DATA_DISCLOSED, transaction_id=None, actor=ev.GATEWAY, customer=principal.customer, mandate=principal.mandate.id,
                                payload={"productIds": ids, "tiers": ["T1"], "withheld": WITHHELD_FIELDS, "disclosure": "capped_at_requested"})
        return {"items": answers, "auditRef": to_jsonable(ref)}

    # ================================================================== purchase transaction

    def submit(self, principal: AgentPrincipal, body: dict[str, Any]) -> dict[str, Any]:
        self._require_action(principal, "offer.request")
        self._spend_budget(principal, "purchase")
        try:
            request = PurchaseRequest.model_validate(body.get("request"))
        except Exception as exc:
            raise ApiError(400, "invalid_request", "Invalid purchase request", str(exc))
        if request.customer != principal.customer:
            raise ApiError(403, "customer_mismatch", "Request customer does not match the mandate")
        if self.store.get_transaction(request.request_id):
            raise ApiError(409, "duplicate_request", "A transaction with this requestId already exists")
        tx = TxCtx(request.request_id, principal.customer, principal.agent, principal.mandate)
        now = self.clock.now()
        self.store.create_transaction(tx.id, tx.customer, tx.agent, now, {"request": request, "mandate": tx.mandate, "attempt": 0})
        self._log(tx, ev.REQUEST_RECEIVED, Actor(kind="agent", id=tx.agent),
                  {"purpose": body.get("purpose", "quote_for_order"), "request": request, "originalText": body.get("originalText")})
        return self._run(tx, request, attempt=0)

    def _run(self, tx: TxCtx, request: PurchaseRequest, attempt: int) -> dict[str, Any]:
        try:
            self._process(tx, request, attempt)
        except UpstreamError as exc:
            self._close(tx, "FAILED", "upstream_unavailable", f"The supplier system did not answer: {exc}")
            raise ApiError(502, "upstream_unavailable", "Supplier system unavailable", str(exc),
                           transactionId=tx.id, auditRef=to_jsonable(self.audit.store.head().ref))
        except RequestError as exc:
            self._close(tx, "FAILED", "invalid_request", str(exc))
            raise ApiError(400, "invalid_request", "Invalid purchase request", str(exc), transactionId=tx.id)
        except ApiError:
            raise
        except Exception as exc:  # audit-log §6.2: every transaction is closed
            self._close(tx, "FAILED", "internal_error", type(exc).__name__)
            raise
        return self.transaction_view(tx.id)

    def _process(self, tx: TxCtx, request: PurchaseRequest, attempt: int) -> None:
        upstream = AuditedUpstream(self.upstream, self.audit, tx.id, tx.customer, tx.mandate.id)
        result = FulfilmentEngine(self.catalog, upstream, self.clock, self.settings.cutoff_policy).run(request)
        self._issue_offers(tx, result)
        self._log(tx, ev.FULFILMENT_COMPLETED, ev.SYSTEM, {"attempt": attempt, "lines": [self._line_payload(lr, request) for lr in result.lines]})
        self._log(tx, ev.DATA_DISCLOSED, ev.GATEWAY, {"productIds": sorted({i.product_id for lr in result.lines for p in lr.plans for i in p.items}),
                                                      "tiers": ["T0", "T1"], "withheld": WITHHELD_FIELDS})
        policy = self.policy_for(tx.customer)
        od = decide_order(result, request, tx.mandate, policy, self._context(tx.customer))
        for ls in od.lines:
            for e in ls.evaluations:
                self._log(tx, ev.GUARDRAIL_EVALUATED, ev.SYSTEM, e.decision)
        if od.order_decision:
            self._log(tx, ev.GUARDRAIL_EVALUATED, ev.SYSTEM, od.order_decision)
        self._save_state(tx, request, result, od, attempt)

        if od.outcome == "AUTO":
            for ls in od.lines:
                self._log(tx, ev.PLAN_SELECTED, ev.SYSTEM, {"lineId": ls.line_id, "rank": ls.selected.rank, "selectionStep": ls.step,
                                                             "reason": ls.reason, "rationale": ls.rationale})
            order = self._submit_order(tx, od.chosen_plans(), approval="auto")
            self._close(tx, "ORDERED", "auto_approved", "Ordered autonomously within the agent's authority.", total=order["total"])
        elif od.outcome == "APPROVAL":
            self._request_approval(tx, od, attempt)
        elif od.outcome == "DENIED":
            if od.requote and attempt < policy.approval.max_requote_attempts:
                self._log(tx, ev.REQUOTE_STARTED, ev.SYSTEM, {"attempt": attempt + 1, "maxAttempts": policy.approval.max_requote_attempts})
                self._process(tx, request, attempt + 1)
                return
            first = next((r for r in od.combined.triggered if r.outcome == "DENY"), None) if od.combined else None
            self._close(tx, "DENIED", first.code if first else "denied", first.message if first else "Every plan breaks a rule.")
        else:
            reasons = [lr.reason.code for lr in result.lines if lr.reason and not lr.plans]
            self._close(tx, "UNFULFILLABLE", reasons[0] if reasons else "no_candidates", "No acceptable plan exists within the hard constraints.")

    # ------------------------------------------------------------------ helpers

    def _log(self, tx: TxCtx, type: str, actor: Actor, payload: Any) -> AuditRef:
        if not isinstance(payload, dict):
            payload = to_jsonable(payload)
        return self.audit.append(type, transaction_id=tx.id, actor=actor, customer=tx.customer, mandate=tx.mandate.id, payload=payload)

    def _context(self, customer: str, approver_role: str | None = None) -> Context:
        now = self.clock.now()
        recent = self.store.orders_since(customer, now - timedelta(hours=24))
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        week = self.store.orders_since(customer, week_start)
        return Context(
            now=now,
            auto_orders_last_24h=sum(1 for o in recent if o["approval"] == "auto"),
            period_spend_eur=sum((o["total"] for o in week), Decimal(0)),
            approver_role=approver_role,
        )

    def _issue_offers(self, tx: TxCtx, result: FulfilmentResult) -> None:
        now = self.clock.now()
        for lr in result.lines:
            for plan in lr.plans:
                for item in plan.items:
                    until = offer_valid_until(item, now, self.settings.offer_fallback_ttl_minutes, self.settings.offer_max_ttl_hours)
                    offer = build_offer(item, issuer=self.issuer, customer=tx.customer, agent=tx.agent, mandate_id=tx.mandate.id, valid_until=until)
                    jws, jws_digest = sign_offer(self.keys.gateway, offer)
                    self.store.save_offer(offer["offerId"], tx.id, until, jws, offer)
                    item.offer_id, item.offer_valid_until = offer["offerId"], until
                    self._log(tx, ev.OFFER_ISSUED, ev.GATEWAY, {"offerId": offer["offerId"], "productId": item.product_id,
                                                                 "quantity": offer["quantity"], "unitPrice": item.unit_price,
                                                                 "validUntil": until, "jwsDigest": jws_digest})

    @staticmethod
    def _line_payload(lr, request: PurchaseRequest) -> dict[str, Any]:
        line = next(line for line in request.lines if line.line_id == lr.line_id)
        return to_jsonable({
            "lineId": lr.line_id, "status": lr.status, "reason": lr.reason, "candidateCounts": lr.candidate_counts,
            "plans": [plan_view(p, line.quantity.value) for p in lr.plans], "notPresented": lr.not_presented,
        })

    def _save_state(self, tx: TxCtx, request: PurchaseRequest, result: FulfilmentResult, od: OrderDecision, attempt: int) -> None:
        tx_row = self.store.get_transaction(tx.id)
        data = tx_row["data"]
        data.update({
            "request": to_jsonable(request),
            "attempt": attempt,
            "fulfilment": to_jsonable(result),
            "orderOutcome": od.outcome,
            "selection": {
                ls.line_id: {
                    "step": ls.step,
                    "selectedRank": ls.selected.rank if ls.selected else None,
                    "recommendedRank": ls.recommended.rank if ls.recommended else None,
                    "requiredRole": ls.required_role,
                    "guardrails": {str(e.plan.rank): self._guardrail_summary(e.decision) for e in ls.evaluations},
                }
                for ls in od.lines
            },
            "orderDecision": self._guardrail_summary(od.order_decision) if od.order_decision else None,
        })
        self.store.update_transaction(tx.id, self.clock.now(), data=data)

    @staticmethod
    def _guardrail_summary(d: Decision) -> dict[str, Any]:
        return {"outcome": d.outcome, "requiredRole": d.required_role, "decisionId": d.decision_id,
                "reasons": [{"rule": r.rule, "code": r.code, "message": r.message} for r in d.triggered]}

    def _submit_order(self, tx: TxCtx, chosen: dict[str, Plan], approval: str) -> dict[str, Any]:
        now = self.clock.now()
        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        lines = [
            {"lineId": lid, "productId": i.product_id, "salesUnits": i.sales_units, "salesUnit": i.sales_unit,
             "unitPrice": i.unit_price, "lineTotal": i.line_total, "offerId": i.offer_id}
            for lid, plan in chosen.items() for i in plan.items
        ]
        total = sum((p.total for p in chosen.values()), Decimal(0))
        order = {"orderId": order_id, "lines": lines, "total": total, "currency": "EUR", "vatExcluded": True, "approval": approval}
        self.store.create_order(order_id, tx.id, tx.customer, total, approval, now, order)
        self._log(tx, ev.ORDER_SUBMITTED, ev.GATEWAY, order)
        return to_jsonable(order)

    def _close(self, tx: TxCtx, outcome: str, reason_code: str, summary: str, total: Any = None) -> None:
        row = self.store.get_transaction(tx.id)
        created = datetime.fromisoformat(row["created_at"]) if row else self.clock.now()
        self._log(tx, ev.TRANSACTION_CLOSED, ev.SYSTEM, {
            "outcome": outcome, "reasonCode": reason_code, "summary": summary,
            "durationMs": int((self.clock.now() - created).total_seconds() * 1000), "total": total,
        })
        if row:
            self.store.update_transaction(tx.id, self.clock.now(), state=outcome)
        try:  # audit-log §6.2: the report is rendered on close; failures are logged, never fatal
            from app.audit.render import render_report

            render_report(self.audit.store, tx.id, "valio", None, self.keys.jwks)
        except Exception as exc:  # pragma: no cover - defensive
            self._log(tx, ev.REPORT_FAILED, ev.SYSTEM, {"error": type(exc).__name__})

    def _tx(self, tx_id: str) -> TxCtx:
        row = self.store.get_transaction(tx_id)
        if row is None:
            raise ApiError(404, "not_found", "Transaction not found")
        return TxCtx(row["id"], row["customer"], row["agent"], MandateInfo.model_validate(row["data"]["mandate"]))

    # ================================================================== approvals (guardrails §8)

    def _request_approval(self, tx: TxCtx, od: OrderDecision, attempt: int) -> None:
        now = self.clock.now()
        policy = self.policy_for(tx.customer)
        lines, limits = [], []
        for ls in od.lines:
            open_plans = [e for e in ls.evaluations if e.decision.outcome != "DENY"]
            if ls.selected is not None:  # auto-selectable line inside an escalated order
                open_plans = [e for e in ls.evaluations if e.plan is ls.selected]
            for e in open_plans:
                for i in e.plan.items:
                    limits.append(i.offer_valid_until)
                    if i.closing_time and i.closing_time > now:
                        limits.append(i.closing_time)
            lines.append({
                "lineId": ls.line_id,
                "recommendedRank": (ls.selected or ls.recommended).rank,
                "plans": [{"rank": e.plan.rank, "label": e.plan.label, "strategy": e.plan.strategy, "total": e.plan.total,
                           "guardrail": self._guardrail_summary(e.decision)} for e in open_plans],
            })
        deadline = min(limits) - timedelta(minutes=policy.approval.deadline_buffer_minutes)
        deadline = max(deadline, now + MIN_APPROVAL_WINDOW)
        approval_id = f"apr_{uuid.uuid4().hex[:10]}"
        order_reasons = self._guardrail_summary(od.order_decision)["reasons"] if od.order_decision else []
        data = to_jsonable({"approvalId": approval_id, "orderDraftId": tx.id, "requiredRole": od.required_role, "deadline": deadline,
                            "lines": lines, "orderReasons": order_reasons, "attempt": attempt, "createdAt": now})
        self.store.create_approval(approval_id, tx.id, tx.customer, od.required_role, deadline, now, data)
        self._log(tx, ev.APPROVAL_REQUESTED, ev.SYSTEM, {**data, "rationale": [to_jsonable(Rationale(code="approval_required", params={"role": od.required_role}))]})
        self.store.update_transaction(tx.id, now, state="PENDING_APPROVAL")

    def _plans_by_rank(self, tx_id: str) -> tuple[PurchaseRequest, FulfilmentResult]:
        data = self.store.get_transaction(tx_id)["data"]
        return PurchaseRequest.model_validate(data["request"]), FulfilmentResult.model_validate(data["fulfilment"])

    def approvals_for(self, human: HumanEntry, state: str | None = None) -> list[dict[str, Any]]:
        self.expire_due()
        return [a["data"] | {"state": a["state"]} for a in self.store.approvals(customer=human.customer, state=state)]

    def get_approval(self, human: HumanEntry, approval_id: str) -> dict[str, Any]:
        self.expire_due()
        ap = self.store.get_approval(approval_id)
        if ap is None or ap["customer"] != human.customer:
            raise ApiError(404, "not_found", "Approval not found")
        return ap["data"] | {"state": ap["state"]}

    def decide(self, human: HumanEntry, approval_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.expire_due()
        ap = self.store.get_approval(approval_id)
        if ap is None or ap["customer"] != human.customer:
            raise ApiError(404, "not_found", "Approval not found")
        if ap["state"] != "PENDING":
            raise ApiError(409, "approval_not_pending", f"Approval is {ap['state']}")
        tx = self._tx(ap["transaction_id"])
        approver = Actor(kind="human", id=human.id, role=human.role)
        who = {"id": human.id, "displayName": human.display_name, "role": human.role}
        if ROLE_RANK.get(human.role or "", 0) < ROLE_RANK[ap["required_role"]]:  # T34
            self._log(tx, ev.AUTH_DENIED, approver, {"reason": "insufficient_role", "approvalId": approval_id, "requiredRole": ap["required_role"], "role": human.role})
            raise ApiError(403, "insufficient_role", "Your role cannot approve this request", f"Requires {ap['required_role']}.")
        action = body.get("action")
        if action == "reject":
            if not body.get("reason"):
                raise ApiError(400, "reason_required", "A reason is required to reject")
            self.store.set_approval_state(approval_id, "REJECTED")
            self._log(tx, ev.APPROVAL_DECIDED, approver, {"approvalId": approval_id, "action": "reject", "reason": body["reason"], "approver": who})
            self._close(tx, "REJECTED", "approver_rejected", f"Rejected by {human.display_name}: {body['reason']}")
            return self.transaction_view(tx.id)
        if action == "modify":
            return self._modify(tx, ap, approver, who, body.get("changes") or {})
        if action != "approve":
            raise ApiError(400, "invalid_action", "action must be approve, reject or modify")

        request, result = self._plans_by_rank(tx.id)
        ranks = {line["lineId"]: line["recommendedRank"] for line in ap["data"]["lines"]} | (body.get("planRanks") or {})
        allowed = {line["lineId"]: {p["rank"] for p in line["plans"]} for line in ap["data"]["lines"]}
        chosen: dict[str, Plan] = {}
        for lr in result.lines:
            rank = ranks.get(lr.line_id)
            if rank not in allowed.get(lr.line_id, set()):
                raise ApiError(400, "invalid_plan", f"Plan rank {rank} was not presented for line {lr.line_id}")
            chosen[lr.line_id] = next(p for p in lr.plans if p.rank == rank)
        refs = {lr.line_id: lr.reference_unit_cost for lr in result.lines}
        decision = evaluate(request, chosen, tx.mandate, self.policy_for(tx.customer), self._context(tx.customer, human.role), refs)
        if decision.outcome == "ESCALATE":
            self._log(tx, ev.AUTH_DENIED, approver, {"reason": "insufficient_role", "approvalId": approval_id, "requiredRole": decision.required_role})
            raise ApiError(403, "insufficient_role", "The chosen plan needs a higher role", f"Requires {decision.required_role}.")
        self._log(tx, ev.APPROVAL_DECIDED, approver, {"approvalId": approval_id, "action": "approve", "planRanks": ranks, "approver": who})
        self._log(tx, ev.GUARDRAIL_EVALUATED, ev.SYSTEM, decision)
        if decision.outcome == "ALLOW":
            self.store.set_approval_state(approval_id, "APPROVED")
            for lid, plan in chosen.items():
                self._log(tx, ev.PLAN_SELECTED, approver, {"lineId": lid, "rank": plan.rank, "selectionStep": 4, "reason": "approver_choice",
                                                           "rationale": [Rationale(code="approver_choice", params={"approver": human.display_name, "role": human.role})]})
            order = self._submit_order(tx, chosen, approval=approval_id)
            self._close(tx, "ORDERED", "human_approved", f"Approved by {human.display_name} ({human.role}).", total=order["total"])
        elif any(r.remedy == "requote" for r in decision.triggered):  # T35
            self.store.set_approval_state(approval_id, "EXPIRED")
            self._log(tx, ev.APPROVAL_EXPIRED, ev.SYSTEM, {"approvalId": approval_id, "deadline": ap["deadline"], "reason": "offer_expired"})
            self._requote_or_close(tx)
        else:
            self.store.set_approval_state(approval_id, "REJECTED")
            first = next(r for r in decision.triggered if r.outcome == "DENY")
            self._close(tx, "DENIED", first.code, first.message)
        return self.transaction_view(tx.id)

    def _modify(self, tx: TxCtx, ap: dict, approver: Actor, who: dict, changes: dict) -> dict[str, Any]:
        request, _ = self._plans_by_rank(tx.id)
        n = sum(1 for t in self.store.transactions(tx.customer) if t["id"].startswith(tx.id + "-m")) + 1
        new = request.model_copy(deep=True)
        new.request_id = f"{tx.id}-m{n}"
        if changes.get("deliverBy"):
            new.deliver_by = datetime.fromisoformat(changes["deliverBy"]).date()
        for change in changes.get("lines", []):
            line = next((line for line in new.lines if line.line_id == change.get("lineId")), None)
            if line is None:
                raise ApiError(400, "invalid_change", f"Unknown line {change.get('lineId')}")
            if "quantity" in change:
                line.quantity = Quantity.model_validate(change["quantity"])
        self.store.set_approval_state(ap["id"], "SUPERSEDED")
        self._log(tx, ev.APPROVAL_SUPERSEDED, approver, {"approvalId": ap["id"], "newRequestId": new.request_id, "changes": changes, "approver": who})
        self._close(tx, "SUPERSEDED", "modified_by_approver", f"Modified by {who['displayName']}; continued as {new.request_id}.")
        new_tx = TxCtx(new.request_id, tx.customer, tx.agent, tx.mandate)
        now = self.clock.now()
        self.store.create_transaction(new_tx.id, new_tx.customer, new_tx.agent, now, {"request": new, "mandate": tx.mandate, "attempt": 0})
        self._log(new_tx, ev.REQUEST_RECEIVED, approver, {"purpose": "quote_for_order", "request": new, "supersedes": tx.id})
        return self._run(new_tx, new, attempt=0)

    def _requote_or_close(self, tx: TxCtx) -> None:
        data = self.store.get_transaction(tx.id)["data"]
        attempt = data.get("attempt", 0)
        policy = self.policy_for(tx.customer)
        if attempt < policy.approval.max_requote_attempts:
            self._log(tx, ev.REQUOTE_STARTED, ev.SYSTEM, {"attempt": attempt + 1, "maxAttempts": policy.approval.max_requote_attempts})
            request = PurchaseRequest.model_validate(data["request"])
            try:
                self._process(tx, request, attempt + 1)
            except UpstreamError as exc:
                self._close(tx, "FAILED", "upstream_unavailable", str(exc))
        else:
            self._close(tx, "EXPIRED", "approval_expired", "No approval before the deadline and no re-quote attempts left.")

    def expire_due(self) -> int:
        """Expire pending approvals past their deadline (G4: never approved by silence)."""
        now = self.clock.now()
        expired = 0
        for ap in self.store.approvals(state="PENDING"):
            if ap["deadline"] <= now:
                tx = self._tx(ap["transaction_id"])
                self.store.set_approval_state(ap["id"], "EXPIRED")
                self._log(tx, ev.APPROVAL_EXPIRED, ev.SYSTEM, {"approvalId": ap["id"], "deadline": ap["deadline"]})
                self._requote_or_close(tx)
                expired += 1
        return expired

    def run_watchdog(self) -> int:
        """Close transactions abandoned mid-way (audit-log §6.2)."""
        self.expire_due()
        now = self.clock.now()
        closed = 0
        for row in self.store.transactions():
            if row["state"] in TERMINAL_STATES or row["state"] == "PENDING_APPROVAL":
                continue
            if now - datetime.fromisoformat(row["updated_at"]) > timedelta(hours=self.settings.abandoned_after_hours):
                self._close(self._tx(row["id"]), "FAILED", "abandoned", "Closed by the watchdog: no progress for 24 hours.")
                closed += 1
        return closed

    # ================================================================== views

    def transaction_view(self, tx_id: str) -> dict[str, Any]:
        row = self.store.get_transaction(tx_id)
        if row is None:
            raise ApiError(404, "not_found", "Transaction not found")
        data = row["data"]
        view: dict[str, Any] = {"transactionId": tx_id, "status": row["state"], "customer": row["customer"]}
        if "fulfilment" in data:
            request = PurchaseRequest.model_validate(data["request"])
            result = FulfilmentResult.model_validate(data["fulfilment"])
            lines = []
            for lr in result.lines:
                line = next(line for line in request.lines if line.line_id == lr.line_id)
                sel = data.get("selection", {}).get(lr.line_id, {})
                plans = []
                for p in lr.plans:
                    pv = plan_view(p, line.quantity.value)
                    pv["guardrail"] = sel.get("guardrails", {}).get(str(p.rank))
                    plans.append(pv)
                lines.append({"lineId": lr.line_id, "status": lr.status, "reason": to_jsonable(lr.reason), "plans": plans,
                              "selectedRank": sel.get("selectedRank"), "recommendedRank": sel.get("recommendedRank")})
            view["lines"] = lines
            view["orderDecision"] = data.get("orderDecision")
        pending = [a for a in self.store.approvals(customer=row["customer"]) if a["transaction_id"] == tx_id]
        if pending:
            last = pending[-1]
            view["approval"] = {"approvalId": last["id"], "state": last["state"], "requiredRole": last["required_role"], "deadline": last["deadline"].isoformat()}
        order = self.store.order_for_transaction(tx_id)
        if order:
            view["order"] = order
        view["offers"] = self.store.offers_for(tx_id)
        own = self.audit.store.for_transaction(tx_id)
        if own:
            view["auditRef"] = to_jsonable(own[-1].ref)
        view["reportUrl"] = f"/v1/audit/transactions/{tx_id}/report"
        return view
