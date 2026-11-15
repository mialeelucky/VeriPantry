// One mapping from gateway states to the three status colours (principle F2).

import type { Outcome, Role, TransactionSummary, TxStatus } from "../api/types";

export type Tone = "ok" | "attention" | "stop" | "neutral";

export const roleName = (role: Role | null | undefined) => (role === "admin" ? "Finance Lead" : "Head Chef");

export function outcomeBadge(outcome: Outcome | undefined, role?: Role | null): { tone: Tone; text: string } {
  switch (outcome) {
    case "ALLOW":
      return { tone: "ok", text: "Within your agent's authority" };
    case "ESCALATE":
      return { tone: "attention", text: `Needs ${roleName(role)}` };
    case "DENY":
      return { tone: "stop", text: "Not allowed" };
    default:
      return { tone: "neutral", text: "Not checked" };
  }
}

export function statusTone(status: TxStatus): Tone {
  if (status === "ORDERED") return "ok";
  if (status === "PENDING_APPROVAL") return "attention";
  if (status === "DENIED" || status === "REJECTED") return "stop";
  return "neutral";
}

export function summaryPill(t: TransactionSummary): { tone: Tone; text: string } {
  switch (t.outcome) {
    case "ORDERED":
      return { tone: "ok", text: t.decidedBy && t.decidedBy !== "agent" ? `Approved by ${t.decidedBy}` : "Ordered by agent" };
    case "PENDING_APPROVAL":
      return { tone: "attention", text: `Waiting for ${roleName(t.requiredRole)}` };
    case "DENIED":
      return { tone: "stop", text: "Blocked by rule" };
    case "REJECTED":
      return { tone: "stop", text: "Rejected" };
    case "EXPIRED":
      return { tone: "neutral", text: "Expired" };
    case "UNFULFILLABLE":
      return { tone: "neutral", text: "Not available" };
    case "SUPERSEDED":
      return { tone: "neutral", text: "Changed" };
    case "FAILED":
      return { tone: "neutral", text: "Failed" };
    default:
      return { tone: "neutral", text: t.outcome };
  }
}
