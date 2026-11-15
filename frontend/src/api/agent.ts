// The buyer agent service (frontend.md §4.1). The browser never talks to the
// gateway's agent endpoints itself.

import { AGENT_URL, request } from "./client";
import type { DraftRequest, Scenario, TransactionView, Understanding, VerifyResponse } from "./types";

export const agentApi = {
  scenarios: () => request<Scenario[]>(AGENT_URL, "/agent/scenarios"),
  understand: (text: string) => request<Understanding>(AGENT_URL, "/agent/understand", { method: "POST", body: { text } }),
  submit: (draft: DraftRequest, originalText: string) =>
    request<TransactionView>(AGENT_URL, "/agent/submit", { method: "POST", body: { request: draft, originalText } }),
  transaction: (id: string) => request<TransactionView>(AGENT_URL, `/agent/transactions/${encodeURIComponent(id)}`),
  verify: (id: string) => request<VerifyResponse>(AGENT_URL, `/agent/transactions/${encodeURIComponent(id)}/verify`),
};
