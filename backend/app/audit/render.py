"""Transaction reports rendered from audit events only (audit-log §7).

Deterministic (L5): no clock, no LLM, no lookups outside the events.
"""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.audit import events as ev
from app.audit.events import AuditEvent
from app.audit.rationale import PLAN_TEMPLATES, SELECTION_TEMPLATES, render_codes
from app.audit.store import AuditStore
from app.audit.verify import verify_links
from app.audit.views import View, view_events

TEMPLATE_VERSION = "report-v1"
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
)


def _eur(v: Any) -> str:
    return "—" if v is None else f"€{Decimal(str(v)):,.2f}"


def _num(v: Any) -> str:
    d = Decimal(str(v))
    return f"{d.normalize():f}" if d == d.to_integral() else f"{d.normalize():f}"


def _t(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


REASONS = {
    "insufficient_quantity": "the requested product can deliver only {avail} of {req} {unit} on time, so substitution was required",
    "no_exact_match": "no product matched the request within its hard constraints, so substitutes were searched",
    "not_available_on_time": "the requested product cannot arrive on time, so substitution was required",
    "not_deliverable": "the requested product cannot currently be delivered, so substitution was required",
}

NEXT_STEPS = {
    "DENIED": "Every option broke a rule that no approver can override (see Decision). Adjust the request, e.g. its constraints.",
    "UNFULFILLABLE": "No acceptable option exists. Relax a constraint or choose a later delivery date.",
    "REJECTED": "The approver rejected the proposal. Submit a revised request if still needed.",
    "EXPIRED": "No approval arrived before the deadline. Submit the request again to receive fresh offers.",
    "FAILED": "The transaction failed for a technical reason. Retry later.",
    "SUPERSEDED": "The request was modified and continues as a new transaction.",
}


def _rule_text(r: dict) -> str:
    text = f"{r['rule']} {r['code']}: {r['message']}"
    return text + " (satisfied by approval)" if r.get("satisfiedByApproval") else text


def _plan_desc(p: dict) -> str:
    return " + ".join(f"{_num(i['quantity']['value'])} {i['quantity']['unit']} of {i['productId']} {i['name']}" for i in p["items"])


def _deviation_text(p: dict) -> str:
    out = []
    for d in p.get("deviations", []):
        share = Decimal(str(d["share"])) if d.get("share") is not None else None
        txt = f"{d['attribute']}: {d.get('requested')} → {d.get('proposed')}"
        if share is not None and share < 1:
            txt += f" ({int(share * 100)} %)"
        out.append(txt)
    return "; ".join(out) or "—"


def _timeline_text(e: AuditEvent) -> str:
    p = e.payload
    if p is None:
        return "Internal step"
    t = e.type
    if t == ev.REQUEST_RECEIVED:
        return f"Request received (purpose: {p.get('purpose')})"
    if t == ev.UPSTREAM_QUERIED:
        return f"Supplier {p['endpoint']} queried for {p['productCount']} products (HTTP {p['httpStatus']})"
    if t == ev.DATA_DISCLOSED:
        return f"Data disclosed: tiers {', '.join(p.get('tiers', []))} for {len(p.get('productIds', []))} products"
    if t == ev.OFFER_ISSUED:
        return f"Signed offer {p['offerId']} for {p['productId']}, valid until {p['validUntil']}"
    if t == ev.FULFILMENT_COMPLETED:
        return "Plans produced: " + ", ".join(f"{l['lineId']} {l['status']} ({len(l['plans'])} plans)" for l in p["lines"])
    if t == ev.GUARDRAIL_EVALUATED:
        ref = p.get("planRef", {})
        if p.get("approverRole"):
            subject = f"approved plan(s), re-evaluated as {p['approverRole']}"
        elif "order" in p.get("scopes", []):
            subject = "order-level rules"
        else:
            subject = f"line {ref.get('lineId')} plan {ref.get('rank')}"
        return f"Guardrails on {subject}: {p['outcome']}" + (f" ({len(p['triggered'])} rules)" if p["triggered"] else "")
    if t == ev.PLAN_SELECTED:
        return f"Plan {p['rank']} selected for line {p['lineId']} ({p['reason']})"
    if t == ev.APPROVAL_REQUESTED:
        return f"Approval {p['approvalId']} requested from {p['requiredRole']}, deadline {p['deadline']}"
    if t == ev.APPROVAL_DECIDED:
        return f"Approval {p['approvalId']}: {p['action']} by {p['approver']['displayName']} ({p['approver']['role']})"
    if t == ev.APPROVAL_EXPIRED:
        return f"Approval {p['approvalId']} expired"
    if t == ev.APPROVAL_SUPERSEDED:
        return f"Approval {p['approvalId']} superseded by {p['newRequestId']}"
    if t == ev.REQUOTE_STARTED:
        return f"Re-quote started (attempt {p['attempt']} of {p['maxAttempts']})"
    if t == ev.ORDER_SUBMITTED:
        return f"Order {p['orderId']} submitted, total {_eur(p['total'])}"
    if t == ev.TRANSACTION_CLOSED:
        return f"Transaction closed: {p['outcome']} ({p['reasonCode']})"
    if t == ev.AUTH_DENIED:
        return f"Refused: {p.get('reason')}"
    return t


def build_context(store: AuditStore, transaction_id: str, view: View, customer: str | None, jwks: list[dict]) -> dict[str, Any]:
    items, checkpoint = view_events(store, transaction_id, view, customer)
    own = [e for e in items if isinstance(e, AuditEvent) and e.transaction_id == transaction_id]
    if not own:
        raise KeyError(transaction_id)
    by_type = lambda t: [e for e in own if e.type == t and e.payload is not None]  # noqa: E731
    received = by_type(ev.REQUEST_RECEIVED)[0]
    req = received.payload["request"]
    closed = (by_type(ev.TRANSACTION_CLOSED) or [None])[-1]
    pending = by_type(ev.APPROVAL_REQUESTED) and not closed

    summary = {
        "transaction_id": transaction_id,
        "outcome": closed.payload["outcome"] if closed else ("PENDING_APPROVAL" if pending else "OPEN"),
        "reason_code": closed.payload["reasonCode"] if closed else None,
        "summary": closed.payload.get("summary") if closed else None,
        "customer": received.customer,
        "agent": received.actor.id,
        "mandate": received.mandate,
        "started": _dt(received.time),
        "closed": _dt(closed.time) if closed else None,
        "duration": f"{(closed.time - received.time).total_seconds():.1f} s" if closed else None,
        "total": _eur(closed.payload.get("total")) + " (VAT excluded)" if closed and closed.payload.get("total") is not None else None,
    }

    lines = []
    for l in req["lines"]:
        spec = l.get("spec") or {}
        what = f"product {l['productId']}" if l.get("productId") else f"\"{spec.get('query') or ''}\" in category {spec.get('category') or 'any'}"
        constraints = []
        if spec.get("requiredAttributes"):
            constraints.append("required: " + ", ".join(spec["requiredAttributes"]))
        if spec.get("excludedAllergens"):
            constraints.append("excluded allergens: " + ", ".join(spec["excludedAllergens"]))
        if spec.get("preferredAttributes"):
            constraints.append("preferred: " + ", ".join(spec["preferredAttributes"]))
        lines.append({"line_id": l["lineId"], "what": what, "quantity": f"{_num(l['quantity']['value'])} {l['quantity']['unit']}",
                      "constraints": "; ".join(constraints) or "—"})
    request = {"original_text": received.payload.get("originalText"), "deliver_by": req["deliverBy"],
               "purpose": received.payload.get("purpose"), "lines": lines}

    fulfilments = by_type(ev.FULFILMENT_COMPLETED)
    latest = fulfilments[-1] if fulfilments else None
    latest_seq = latest.seq if latest else 0
    weights = (req.get("preferences") or {}).get("weights") or {"fit": 0.45, "cost": 0.30, "reliability": 0.15, "sustainability": 0.10}
    weights_txt = " / ".join(f"{weights[k]}" for k in ("fit", "cost", "reliability", "sustainability"))

    checked, options, labels = [], [], {}
    for line in (latest.payload["lines"] if latest else []):
        r = line.get("reason")
        if line["status"] == "fulfilled":
            reason = "the request can be met as asked"
        elif r:
            reason = REASONS.get(r["code"], r["code"]).format(avail=_num(r.get("availableOnTime") or 0), req=_num(r.get("requested") or 0), unit=r.get("unit") or "")
        else:
            reason = line["status"]
        c = line["candidateCounts"]
        checked.append({"line_id": line["lineId"], "reason": reason[0].upper() + reason[1:],
                        "counts": f"{c['retrieved']} retrieved → {c['afterHardFilter']} after hard filters → {c['shortlisted']} shortlisted; "
                                  f"{c['substitutePool']} substitutes considered; {c['feasible']} feasible on time"})
        plans = []
        for p in line["plans"]:
            label = (p.get("label") or "").capitalize()
            labels[(line["lineId"], p.get("rank"))] = label
            plans.append({"label": label, "description": _plan_desc(p), "total": _eur(p["total"]),
                          "score": f"{float(p['scores']['total']):.2f}", "deviations": _deviation_text(p),
                          "flags": ", ".join(p.get("flags", [])) or "—", "rationale": render_codes(p.get("rationale", []), PLAN_TEMPLATES)})
        not_presented = [
            f"{n['strategy']} of {' + '.join(n['productIds'])} ({_eur(n['total'])}, score {float(n['score']):.2f}): "
            + {"strategy_diversity": "not shown because two plans of the same strategy are already listed (strategy-diversity rule)",
               "duplicate_products": "same products as a listed plan",
               "ranked_below_third": "ranked below third"}.get(n["reason"], n["reason"])
            for n in line.get("notPresented", [])[:5]
        ]
        options.append({"line_id": line["lineId"], "plans": plans, "weights": weights_txt, "not_presented": not_presented})

    decided = by_type(ev.APPROVAL_DECIDED)
    decided_seq = decided[-1].seq if decided else None
    decisions = []
    for line in (latest.payload["lines"] if latest else []):
        lid = line["lineId"]
        sel = [e for e in by_type(ev.PLAN_SELECTED) if e.payload["lineId"] == lid]
        req_ap = [e for e in by_type(ev.APPROVAL_REQUESTED) if e.seq > latest_seq]
        if sel:
            s = sel[-1].payload
            selection = f"Selected: {labels.get((lid, s['rank']), 'plan ' + str(s['rank']))} plan. Why: {render_codes(s.get('rationale', []), SELECTION_TEMPLATES)}."
        elif req_ap:
            selection = f"Sent for approval. Why: {render_codes(req_ap[-1].payload.get('rationale', []), SELECTION_TEMPLATES)}."
        else:
            selection = None
        guardrails = []
        for e in by_type(ev.GUARDRAIL_EVALUATED):
            ref = e.payload.get("planRef", {})
            if e.seq < latest_seq or "order" in e.payload.get("scopes", []) or ref.get("lineId") != lid:
                continue
            subject = f"{labels.get((lid, ref.get('rank')), 'Plan ' + str(ref.get('rank')))} plan"
            guardrails.append({"subject": subject, "outcome": e.payload["outcome"], "role": e.payload.get("requiredRole"),
                               "reasons": [_rule_text(r) for r in e.payload["triggered"]]})
        decisions.append({"line_id": lid, "selection": selection, "guardrails": guardrails})
    order_level = []
    for e in by_type(ev.GUARDRAIL_EVALUATED):
        if e.seq < latest_seq or "order" not in e.payload.get("scopes", []):
            continue
        if e.payload.get("approverRole"):
            subject = f"Approved plan(s), re-evaluated with the approver's role ({e.payload['approverRole']})"
        else:
            subject = "Order-level rules (mandate, spend, velocity)"
        order_level.append({"subject": subject, "outcome": e.payload["outcome"], "role": e.payload.get("requiredRole"),
                            "reasons": [_rule_text(r) for r in e.payload["triggered"]]})
    if order_level:
        decisions.append({"line_id": "order", "selection": None, "guardrails": order_level})

    approvals = []
    for e in own:
        p = e.payload
        if p is None:
            continue
        if e.type == ev.APPROVAL_REQUESTED:
            approvals.append(f"{_dt(e.time)}: approval {p['approvalId']} requested from **{p['requiredRole']}**, deadline {p['deadline']}.")
        elif e.type == ev.APPROVAL_DECIDED:
            a = p["approver"]
            what = f"approved plan(s) {p.get('planRanks')}" if p["action"] == "approve" else f"rejected: {p.get('reason')}"
            approvals.append(f"{_dt(e.time)}: **{a['displayName']}** ({a['role']}) {what}.")
        elif e.type == ev.APPROVAL_EXPIRED:
            approvals.append(f"{_dt(e.time)}: approval {p['approvalId']} expired without a decision (never approved by silence).")
        elif e.type == ev.APPROVAL_SUPERSEDED:
            approvals.append(f"{_dt(e.time)}: **{p['approver']['displayName']}** modified the request; continued as {p['newRequestId']}.")

    order = None
    submitted = by_type(ev.ORDER_SUBMITTED)
    if submitted:
        o = submitted[-1].payload
        order = {"orderId": o["orderId"], "total": _eur(o["total"]), "approval": o["approval"],
                 "lines": [{"productId": l["productId"], "qty": f"{_num(l['salesUnits'])} {l['salesUnit']}", "unitPrice": _eur(l["unitPrice"]),
                            "lineTotal": _eur(l["lineTotal"]), "offerId": l["offerId"]} for l in o["lines"]]}
    next_step = NEXT_STEPS.get(summary["outcome"], "The transaction is still open.")

    timeline = [{"time": _t(e.time), "actor": e.actor.kind if isinstance(e, AuditEvent) else "—", "text": _timeline_text(e)}
                for e in own if e.type != ev.CHAIN_CHECKPOINT]

    disclosure = []
    if view == "valio":
        for e in own:
            if e.type == ev.DATA_DISCLOSED:
                disclosure.append(f"{_t(e.time)} disclosed tiers {', '.join(e.payload['tiers'])} for {len(e.payload['productIds'])} products; withheld: {', '.join(e.payload.get('withheld', []))}")
            elif e.type == ev.UPSTREAM_QUERIED:
                disclosure.append(f"{_t(e.time)} upstream {e.payload['endpoint']} for {e.payload['productCount']} products, "
                                  f"HTTP {e.payload['httpStatus']}, {e.payload.get('latencyMs', 0)} ms")

    result = verify_links(items, jwks, checkpoint=checkpoint)
    if result.ok:
        integrity = f"Events seq {result.from_seq}–{result.to_seq} verified ({result.checked} links)."
        integrity += (f" Chain head sealed by checkpoint seq {result.checkpoint_seq} (key kid `{result.checkpoint_kid}`)."
                      if result.checkpoint_seq else " No checkpoint covers this range yet.")
    else:
        integrity = f"**Verification FAILED** at seq {result.error_seq}: {result.error}."

    return {
        "s": summary, "request": request, "checked": checked, "options": options, "decisions": decisions,
        "approvals": approvals, "order": order, "next_step": next_step, "timeline": timeline, "disclosure": disclosure,
        "integrity": integrity, "view": view, "template_version": TEMPLATE_VERSION,
        "offers_issued": len(by_type(ev.OFFER_ISSUED)) or sum(1 for e in own if e.type == ev.OFFER_ISSUED),
        "attempts": len(fulfilments),
    }


def _escape(value: Any) -> Any:
    """Neutralise HTML in every string taken from events.

    Event payloads include free text from agents (e.g. ``originalText``) and
    supplier data (product names). Markdown passes raw HTML through, so without
    this an agent could inject markup into the HTML and PDF reports.
    """
    if isinstance(value, str):
        return html.escape(value, quote=False)
    if isinstance(value, dict):
        return {k: _escape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_escape(v) for v in value]
    return value


def render_markdown(store: AuditStore, transaction_id: str, view: View, customer: str | None, jwks: list[dict]) -> str:
    ctx = _escape(build_context(store, transaction_id, view, customer, jwks))
    return _env.get_template("report.md.j2").render(**ctx)


def markdown_to_html_body(md: str) -> str:
    return markdown.markdown(md, extensions=["tables"])


def render_report(store: AuditStore, transaction_id: str, view: View, customer: str | None, jwks: list[dict], fmt: str = "md") -> str:
    md = render_markdown(store, transaction_id, view, customer, jwks)
    if fmt == "md":
        return md
    body = markdown_to_html_body(md)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Transaction report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "table{border-collapse:collapse;margin:.5rem 0}td,th{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}"
        "blockquote{color:#555;border-left:3px solid #ccc;margin:0;padding-left:1rem}</style></head><body>"
        + body + "</body></html>"
    )
