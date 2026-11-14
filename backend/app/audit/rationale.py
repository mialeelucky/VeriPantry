"""Rationale code templates (audit-log §7.4).

Unknown codes render as the raw code; rendering never fails on them (AT16).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _eur(v: Any) -> str:
    return f"€{Decimal(str(v)):,.2f}"


def _qty(v: Any) -> str:
    d = Decimal(str(v))
    return f"{d.normalize():f}" if d == d.to_integral() else f"{d:f}"


PLAN_TEMPLATES = {
    "cheapest_complete": lambda p: "cheapest complete plan" + (f" ({_eur(p['marginEUR'])} below the next)" if p.get("marginEUR") is not None else ""),
    "cost_above_best": lambda p: f"{_eur(p['deltaEUR'])} more expensive than Best",
    "most_expensive": lambda p: "most expensive",
    "complete_on_time": lambda p: "full quantity on time",
    "single_product": lambda p: "from one product",
    "split": lambda p: f"split into {p.get('n', 2)} products",
    "keeps_requested_product": lambda p: f"keeps the requested product for {_qty(p['quantity'])} {p.get('unit', '')} ({int(Decimal(str(p['share'])) * 100)} %)",
    "only_deviation": lambda p: "only the " + ", ".join(p.get("attributes", [])) + (" differ" if len(p.get("attributes", [])) > 1 else " differs"),
    "highest_fit": lambda p: "closest match to the request",
    "closest_name": lambda p: "closest name match",
    "highest_reliability": lambda p: "most reliable delivery",
    "lowest_carbon": lambda p: "lowest carbon footprint",
    "later_delivery": lambda p: f"delivered {p.get('date') or 'on an unconfirmed date'}, after the requested date",
    "partial": lambda p: f"covers {_qty(p['quantity'])} of {_qty(p['requested'])} {p.get('unit', '')}",
    "diversity_rule_applied": lambda p: "shown as a different kind of option",
}

SELECTION_TEMPLATES = {
    "top_plan_allowed": lambda p: "the highest-ranked plan, and every guardrail rule passed",
    "equivalent_plan_within_tolerance": lambda p: f"the Best plan needed approval; this plan scores within {p.get('tolerance', 0.05)} of it and is within the agent's authority",
    "approval_required": lambda p: f"no plan within the agent's authority; sent to {p.get('role') or 'an approver'} for approval",
    "approver_choice": lambda p: f"chosen by {p.get('approver')} ({p.get('role')})",
    "all_denied": lambda p: "every plan breaks a rule that no approver can override",
}


def render_codes(codes: list[dict[str, Any]], templates: dict) -> str:
    parts = []
    for c in codes or []:
        fn = templates.get(c.get("code"))
        try:
            parts.append(fn(c.get("params") or {}) if fn else c.get("code", "?"))
        except Exception:
            parts.append(c.get("code", "?"))
    return "; ".join(parts)
