"""Plan selection and order decision (guardrails §6.2, §7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.core.contracts import FulfilmentResult, LineResult, Plan, PurchaseRequest, Rationale
from app.guardrails.engine import combine, evaluate
from app.guardrails.models import ROLE_RANK, Context, Decision, MandateInfo, Policy, Role


@dataclass
class PlanEvaluation:
    plan: Plan
    decision: Decision


@dataclass
class LineSelection:
    line_id: str
    evaluations: list[PlanEvaluation]
    step: int  # §7 step that resolved the line (2, 3, 4 or 5)
    selected: Plan | None = None  # set when the agent may order autonomously
    recommended: Plan | None = None  # what a human is advised to approve
    required_role: Role | None = None
    rationale: list[Rationale] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return self.rationale[0].code if self.rationale else ""

    def evaluation_for(self, rank: int | None) -> PlanEvaluation | None:
        return next((e for e in self.evaluations if e.plan.rank == rank), None)


OrderOutcome = Literal["AUTO", "APPROVAL", "DENIED", "UNFULFILLABLE"]


@dataclass
class OrderDecision:
    outcome: OrderOutcome
    lines: list[LineSelection]
    order_decision: Decision | None
    combined: Decision | None
    required_role: Role | None = None
    requote: bool = False

    def chosen_plans(self) -> dict[str, Plan]:
        return {ls.line_id: (ls.selected or ls.recommended) for ls in self.lines if (ls.selected or ls.recommended)}


def select_line(
    line_result: LineResult,
    request: PurchaseRequest,
    mandate: MandateInfo | None,
    policy: Policy,
    context: Context,
) -> LineSelection:
    refs = {line_result.line_id: line_result.reference_unit_cost}
    evaluations = [
        PlanEvaluation(
            plan=p,
            decision=evaluate(request, {line_result.line_id: p}, mandate, policy, context, refs, scopes=("line", "item")),
        )
        for p in line_result.plans
    ]
    if not evaluations:
        return LineSelection(line_id=line_result.line_id, evaluations=[], step=5, rationale=[Rationale(code="all_denied")])
    top = evaluations[0]
    # Step 2: top-ranked plan within authority.
    if top.decision.outcome == "ALLOW":
        return LineSelection(line_result.line_id, evaluations, 2, selected=top.plan, rationale=[Rationale(code="top_plan_allowed")])
    # Step 3: a lower-ranked plan within authority and within score tolerance.
    tolerance = policy.selection.tolerance_score
    for e in evaluations[1:]:
        if e.decision.outcome == "ALLOW" and e.plan.scores.total >= top.plan.scores.total - tolerance:
            return LineSelection(
                line_result.line_id, evaluations, 3, selected=e.plan,
                rationale=[Rationale(code="equivalent_plan_within_tolerance", params={"tolerance": tolerance})],
            )
    # Step 4: approval with every non-DENY plan.
    open_plans = [e for e in evaluations if e.decision.outcome != "DENY"]
    if open_plans:
        roles = [e.decision.required_role for e in open_plans if e.decision.required_role]
        role = max(roles, key=lambda r: ROLE_RANK[r]) if roles else None
        return LineSelection(
            line_result.line_id, evaluations, 4, recommended=open_plans[0].plan, required_role=role,
            rationale=[Rationale(code="approval_required", params={"role": role})],
        )
    # Step 5: every plan denied.
    return LineSelection(line_result.line_id, evaluations, 5, rationale=[Rationale(code="all_denied")])


def decide_order(
    fulfilment: FulfilmentResult,
    request: PurchaseRequest,
    mandate: MandateInfo | None,
    policy: Policy,
    context: Context,
) -> OrderDecision:
    selections = [select_line(lr, request, mandate, policy, context) for lr in fulfilment.lines]
    if any(not lr.plans for lr in fulfilment.lines):
        return OrderDecision("UNFULFILLABLE", selections, None, None)
    if any(ls.step == 5 for ls in selections):
        requote = any(r.remedy == "requote" for ls in selections for e in ls.evaluations for r in e.decision.triggered)
        line_decisions = [e.decision for ls in selections for e in ls.evaluations]
        return OrderDecision("DENIED", selections, None, combine(line_decisions, request.request_id), requote=requote)

    chosen = {ls.line_id: (ls.selected or ls.recommended) for ls in selections}
    order_decision = evaluate(request, chosen, mandate, policy, context, scopes=("order",))
    chosen_decisions = [
        next(e.decision for e in ls.evaluations if e.plan is chosen[ls.line_id]) for ls in selections
    ]
    combined = combine(chosen_decisions + [order_decision], request.request_id)
    if order_decision.outcome == "DENY":
        return OrderDecision("DENIED", selections, order_decision, combined)
    if all(ls.selected is not None for ls in selections) and order_decision.outcome == "ALLOW":
        return OrderDecision("AUTO", selections, order_decision, combined)
    roles = [ls.required_role for ls in selections if ls.required_role] + (
        [order_decision.required_role] if order_decision.required_role else []
    )
    role = max(roles, key=lambda r: ROLE_RANK[r]) if roles else "approver"
    return OrderDecision("APPROVAL", selections, order_decision, combined, required_role=role)


def reevaluate_approved(
    choices: dict[str, Plan],
    request: PurchaseRequest,
    mandate: MandateInfo | None,
    policy: Policy,
    context: Context,
    reference_costs: dict,
) -> Decision:
    """Re-evaluate approved plans with the approver's role in context (§8.3)."""
    return evaluate(request, choices, mandate, policy, context, reference_costs)
