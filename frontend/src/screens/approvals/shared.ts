import type { Approval, GuardrailReason, Person, Role } from "../../api/types";

const RANK: Record<Role, number> = { approver: 1, admin: 2 };

export const canDecide = (person: Person | null, required: Role) => !!person?.role && RANK[person.role] >= RANK[required];

/** Every reason behind the request: order-level rules first, then the recommended plan's. */
export function reasonsOf(a: Approval): GuardrailReason[] {
  const all = [...(a.orderReasons ?? [])];
  for (const line of a.lines) {
    const rec = line.plans.find((p) => p.rank === line.recommendedRank);
    if (rec) all.push(...rec.guardrail.reasons);
  }
  const seen = new Set<string>();
  return all.filter((r) => (seen.has(r.message) ? false : (seen.add(r.message), true)));
}

const SHORT: Record<string, (r: GuardrailReason) => string> = {
  spend_over_auto_limit: () => "Over agent's limit",
  spend_over_approver_limit: () => "Over approver limit",
  inflexible_deviation: (r) => `${String(r.observed ?? "Spec")} change`.replace(/^./, (c) => c.toUpperCase()),
  low_similarity: () => "Less similar product",
  substitution_tier: () => "Other category",
  quantity_over_mandate: () => "Large quantity",
  partial_fulfilment: () => "Partial delivery",
  later_delivery: () => "Arrives later",
  cutoff_passed: () => "Cut-off passed",
  unit_price_increase: () => "Price above reference",
};

export const shortReason = (a: Approval) => {
  const r = reasonsOf(a)[0];
  return r ? (SHORT[r.code]?.(r) ?? r.code.replace(/_/g, " ")) : "Needs a decision";
};
