// Gateway endpoints used directly by people (frontend.md §4.2).

import { GATEWAY_URL, download, request } from "./client";
import type { Approval, AuditEvent, Person, TransactionSummary, TransactionView, VerifyResponse } from "./types";

const id = encodeURIComponent;

export const gatewayApi = {
  personas: () => request<Person[]>(GATEWAY_URL, "/dev/personas"),
  session: (persona: string) =>
    request<{ token: string; expiresAt: string; person: Person }>(GATEWAY_URL, "/dev/session", { method: "POST", body: { persona } }),
  me: (token: string) => request<Person>(GATEWAY_URL, "/v1/me", { token }),
  jwks: () => request<{ keys: JsonWebKey[] }>(GATEWAY_URL, "/.well-known/jwks.json"),
  pushKey: () => request<{ publicKey: string }>(GATEWAY_URL, "/.well-known/push-key"),
  subscribe: (token: string, sub: PushSubscriptionJSON) =>
    request<{ subscribed: boolean; devices: number }>(GATEWAY_URL, "/v1/me/push-subscriptions", { method: "POST", body: sub, token }),

  approvals: (token: string, state?: string) =>
    request<Approval[]>(GATEWAY_URL, `/v1/approvals${state ? `?state=${state}` : ""}`, { token }),
  approval: (token: string, approvalId: string) => request<Approval>(GATEWAY_URL, `/v1/approvals/${id(approvalId)}`, { token }),
  decide: (token: string, approvalId: string, body: Record<string, unknown>) =>
    request<TransactionView>(GATEWAY_URL, `/v1/approvals/${id(approvalId)}/decision`, { method: "POST", body, token }),
  transaction: (token: string, txId: string) => request<TransactionView>(GATEWAY_URL, `/v1/purchase-requests/${id(txId)}`, { token }),

  auditList: (token: string) => request<TransactionSummary[]>(GATEWAY_URL, "/v1/audit/transactions", { token }),
  auditEvents: (token: string, txId: string, view?: "buyer" | "valio") =>
    request<{ events: AuditEvent[]; view: string }>(GATEWAY_URL, `/v1/audit/transactions/${id(txId)}${view ? `?view=${view}` : ""}`, { token }),
  verify: (token: string, txId: string) => request<VerifyResponse>(GATEWAY_URL, `/v1/audit/transactions/${id(txId)}/verify`, { token }),
  tamperPreview: (token: string, txId: string, seq: number) =>
    request<VerifyResponse>(GATEWAY_URL, "/v1/audit/tamper-preview", { method: "POST", body: { transactionId: txId, seq }, token }),
  downloadPdf: (token: string, txId: string, view: "buyer" | "valio") =>
    download(GATEWAY_URL, `/v1/audit/transactions/${id(txId)}/report?format=pdf&view=${view}`, token, `audit-report-${txId}.pdf`),
};
