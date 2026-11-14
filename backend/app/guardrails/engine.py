"""Guardrail evaluation (guardrails §6)."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from app.core.contracts import FLAG_RELIABILITY_NO_DATA, Plan, PurchaseRequest
from app.core.jcs import digest
from app.guardrails.models import ROLE_RANK, Context, Decision, MandateInfo, PlanRef, Policy, RuleResult
from app.guardrails.rules import RULES, EvalInput, Skip

ALL_SCOPES = ("order", "line", "item")


def evaluate(
    request: PurchaseRequest,
    plans: dict[str, Plan],
    mandate: MandateInfo | None,
    policy: Policy,
    context: Context,
    reference_costs: dict[str, Decimal | None] | None = None,
    scopes: Iterable[str] = ALL_SCOPES,
) -> Decision:
    scopes = tuple(scopes)
    effective = policy.with_mandate_limits(mandate.limits if mandate else {})
    inp = EvalInput(
        request=request,
        plans=plans,
        mandate=mandate,
        policy=effective,
        context=context,
        reference_costs=reference_costs or {},
    )
    triggered: list[RuleResult] = []
    skipped: list[str] = []
    for rule_id, scope, fn in RULES:  # G3: every rule, no short-circuit
        if scope not in scopes:
            continue
        try:
            triggered += fn(inp)
        except Skip:
            skipped.append(rule_id)

    approver_rank = ROLE_RANK.get(context.approver_role or "", 0)
    for r in triggered:
        if r.outcome == "ESCALATE" and r.role and ROLE_RANK[r.role] <= approver_rank:
            r.satisfied_by_approval = True

    if any(r.outcome == "DENY" for r in triggered):  # G2: deny dominates
        outcome, role = "DENY", None
    else:
        open_escalations = [r for r in triggered if r.outcome == "ESCALATE" and not r.satisfied_by_approval]
        if open_escalations:
            outcome = "ESCALATE"
            role = max((r.role for r in open_escalations), key=lambda x: ROLE_RANK[x])
        else:
            outcome, role = "ALLOW", None

    informational = sorted(
        {FLAG_RELIABILITY_NO_DATA for p in plans.values() for i in p.items if FLAG_RELIABILITY_NO_DATA in i.flags}
    )
    inputs_digest = digest(
        {
            "request": request,
            "plans": plans,
            "policy": effective,
            "context": context,
            "referenceCosts": reference_costs or {},
            "mandate": mandate.id if mandate else None,
            "scopes": scopes,
        }
    )
    line_id = next(iter(plans)) if len(plans) == 1 else None
    rank = plans[line_id].rank if line_id else None
    return Decision(
        decision_id="dec_" + inputs_digest.split(":")[1][:16],
        plan_ref=PlanRef(request_id=request.request_id, line_id=line_id, rank=rank),
        outcome=outcome,
        required_role=role,
        scopes=list(scopes),
        approver_role=context.approver_role,
        triggered=triggered,
        skipped=skipped,
        informational=informational,
        policy={"policyId": policy.policy_id, "version": policy.version},
        mandate=mandate.id if mandate else None,
        inputs_digest=inputs_digest,
        evaluated_at=context.now,
    )


def combine(decisions: list[Decision], request_id: str) -> Decision:
    """Aggregate line and order decisions into one (G2)."""
    triggered = [r for d in decisions for r in d.triggered]
    if any(d.outcome == "DENY" for d in decisions):
        outcome, role = "DENY", None
    elif any(d.outcome == "ESCALATE" for d in decisions):
        outcome = "ESCALATE"
        role = max((d.required_role for d in decisions if d.outcome == "ESCALATE"), key=lambda x: ROLE_RANK[x])
    else:
        outcome, role = "ALLOW", None
    combined = digest([d.inputs_digest for d in decisions])
    first = decisions[0]
    return Decision(
        decision_id="dec_" + combined.split(":")[1][:16],
        plan_ref=PlanRef(request_id=request_id),
        outcome=outcome,
        required_role=role,
        scopes=sorted({s for d in decisions for s in d.scopes}),
        triggered=triggered,
        skipped=sorted({s for d in decisions for s in d.skipped}),
        informational=sorted({s for d in decisions for s in d.informational}),
        policy=first.policy,
        mandate=first.mandate,
        inputs_digest=combined,
        evaluated_at=first.evaluated_at,
    )
