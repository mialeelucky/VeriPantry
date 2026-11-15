// Types mirroring the gateway's JSON (frontend.md §4.5). Money and quantities
// arrive as decimal strings; the UI formats them and never computes with them.

export type Unit = "L" | "KG" | "PCS";
export type Outcome = "ALLOW" | "ESCALATE" | "DENY";
export type Role = "approver" | "admin";
export type TxStatus =
  | "OPEN"
  | "PENDING_APPROVAL"
  | "ORDERED"
  | "DENIED"
  | "REJECTED"
  | "EXPIRED"
  | "UNFULFILLABLE"
  | "SUPERSEDED"
  | "FAILED";

export interface Quantity {
  value: string | number;
  unit: Unit;
}

export interface Spec {
  query?: string | null;
  category?: string | null;
  requiredAttributes?: string[];
  excludedAllergens?: string[];
  preferredAttributes?: string[];
}

export interface RequestLine {
  lineId: string;
  productId?: string | null;
  spec: Spec;
  quantity: Quantity | null;
}

export interface DraftRequest {
  requestId?: string;
  deliverBy: string;
  lines: RequestLine[];
}

export interface Understanding {
  draft: DraftRequest;
  ambiguities: string[];
  source: "scenario" | "rules";
}

export interface Scenario {
  id: string;
  title: string;
  text: string;
  draft: DraftRequest;
}

export interface Deviation {
  attribute: string;
  requested: unknown;
  proposed: unknown;
  share: string | null;
}

export interface PlanItem {
  productId: string;
  name: string;
  brand: string | null;
  tier: "exact" | "S0" | "S1" | "S2" | "S3";
  status: string;
  salesUnits: string;
  salesUnit: string;
  quantity: Quantity;
  availableDate: string | null;
  unitPrice: string;
  lineTotal: string;
  unitCost: string;
  allergens: Record<string, string>;
  claims: string[];
  labels: string[];
  flags: string[];
  deviations: Deviation[];
  offerId: string | null;
  offerValidUntil: string | null;
  reliabilityBand: "high" | "medium" | "low" | "no_data";
  stockBasis: "warehouse" | "supplier-direct";
}

export interface GuardrailReason {
  rule: string;
  code: string;
  message: string;
  observed?: unknown;
  limit?: unknown;
}

export interface GuardrailSummary {
  outcome: Outcome;
  requiredRole: Role | null;
  decisionId: string;
  reasons: GuardrailReason[];
}

export interface Plan {
  lineId: string;
  rank: number | null;
  label: "best" | "second" | "third" | "optimal" | null;
  strategy: string;
  items: PlanItem[];
  total: string;
  covered: Quantity;
  coverage: string;
  complete: boolean;
  onTime: boolean;
  scores: { fit: number; cost: number; reliability: number; sustainability: number; total: number };
  flags: string[];
  deviations: Deviation[];
  rationaleText: string;
  guardrail: GuardrailSummary | null;
}

export interface CandidateCounts {
  retrieved: number;
  afterHardFilter: number;
  shortlisted: number;
  feasible: number;
  substitutePool: number;
}

export interface LineView {
  lineId: string;
  status: "fulfilled" | "substitution_proposed" | "unfulfillable";
  reason: { code: string; requested: string | null; availableOnTime: string | null; unit: Unit | null } | null;
  plans: Plan[];
  candidateCounts: CandidateCounts;
  notPresented: { strategy: string; productIds: string[]; total: string; score: number; reason: string }[];
  selectedRank: number | null;
  recommendedRank: number | null;
  selectionText: string;
}

export interface OrderView {
  orderId: string;
  total: string;
  approval: string;
  lines: { lineId: string; productId: string; salesUnits: string; salesUnit: string; unitPrice: string; lineTotal: string; offerId: string }[];
}

export interface TransactionView {
  transactionId: string;
  status: TxStatus;
  customer: string;
  createdAt: string;
  title?: string;
  request?: DraftRequest & { requestId: string; customer: string };
  lines?: LineView[];
  orderDecision?: GuardrailSummary | null;
  closed?: { outcome: TxStatus; reasonCode: string; summary: string; at: string };
  approval?: { approvalId: string; state: string; requiredRole: Role; deadline: string };
  order?: OrderView;
  offers: Record<string, string>;
  auditRef?: { seq: number; hash: string };
}

export interface ApprovalPlanSummary {
  rank: number;
  label: string;
  strategy: string;
  total: string;
  guardrail: GuardrailSummary;
}

export interface Approval {
  approvalId: string;
  orderDraftId: string;
  title: string;
  total: string;
  requiredRole: Role;
  deadline: string;
  state: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "SUPERSEDED";
  lines: { lineId: string; recommendedRank: number; plans: ApprovalPlanSummary[] }[];
  orderReasons: GuardrailReason[];
  createdAt: string;
}

export interface Person {
  id: string;
  displayName: string;
  kind: "approver" | "staff";
  role: Role | null;
  customer: string | null;
  customerName?: string | null;
  channels?: { webPush: number; webhook: boolean };
  pushAvailable?: boolean;
}

export interface TransactionSummary {
  transactionId: string;
  title: string;
  customer: string;
  state: TxStatus;
  outcome: TxStatus;
  reasonCode: string | null;
  decidedBy: string | null;
  requiredRole: Role | null;
  total: string | null;
  createdAt: string;
  closedAt: string | null;
}

export interface AuditEvent {
  seq: number;
  eventId?: string;
  time?: string;
  type?: string;
  transactionId?: string | null;
  actor?: { kind: string; id: string; role: string | null };
  visibility?: "both" | "valio";
  payload?: Record<string, any> | null;
  prevHash: string;
  hash: string;
}

export interface VerifyResponse {
  transactionId: string;
  view: "buyer" | "valio";
  tamperedSeq: number | null;
  result: {
    ok: boolean;
    fromSeq: number | null;
    toSeq: number | null;
    checked: number;
    errorSeq: number | null;
    error: string | null;
    checkpointSeq: number | null;
    checkpointKid: string | null;
  };
  steps: { seq: number; type: string; ok: boolean }[];
}
