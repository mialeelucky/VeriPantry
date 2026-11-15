// Timeline and ChainStrip for the audit screens (frontend.md §5.3).

import { Bell, CheckCircle2, Eye, FileSignature, Lock, Package, Search, ShieldCheck, ShieldAlert, Truck, UserCheck, Workflow, XCircle, Link2 } from "lucide-react";
import type { AuditEvent } from "../api/types";
import { money, preciseTime } from "../lib/format";
import { cx } from "./ui";

const ICONS: Record<string, typeof Bell> = {
  "request.received": Package,
  "catalog.searched": Search,
  "upstream.queried": Search,
  "data.disclosed": Eye,
  "offer.issued": FileSignature,
  "fulfilment.completed": Workflow,
  "guardrail.evaluated": ShieldCheck,
  "plan.selected": CheckCircle2,
  "approval.requested": ShieldAlert,
  "approval.decided": UserCheck,
  "approval.expired": XCircle,
  "approval.superseded": Workflow,
  "notification.sent": Bell,
  "requote.started": Workflow,
  "order.submitted": Truck,
  "transaction.closed": CheckCircle2,
  "auth.denied": XCircle,
};

export function describe(e: AuditEvent): string {
  const p = e.payload;
  if (!p) return "Internal step · visible to Valio only";
  switch (e.type) {
    case "request.received":
      return `Request received${p.originalText ? `: "${p.originalText}"` : ""}`;
    case "upstream.queried":
      return `Supplier ${p.endpoint} queried for ${p.productCount} products · HTTP ${p.httpStatus} · ${p.latencyMs} ms`;
    case "data.disclosed":
      return `Disclosed ${(p.tiers ?? []).join(", ")} for ${(p.productIds ?? []).length} products · withheld ${(p.withheld ?? []).join(", ")}`;
    case "offer.issued":
      return `Signed offer ${p.offerId} for ${p.productId}`;
    case "fulfilment.completed":
      return `Plans produced: ${(p.lines ?? []).map((l: any) => `${l.plans.length} for ${l.lineId}`).join(", ")}`;
    case "guardrail.evaluated": {
      const subject = p.approverRole ? "approved plan, re-checked" : (p.scopes ?? []).includes("order") ? "order-level rules" : `plan ${p.planRef?.rank}`;
      return `Guardrails on ${subject}: ${p.outcome}${p.triggered?.length ? ` (${p.triggered.map((r: any) => r.rule).join(", ")})` : ""}`;
    }
    case "plan.selected":
      return `Plan ${p.rank} selected (${String(p.reason).replace(/_/g, " ")})`;
    case "approval.requested":
      return `Approval requested from ${p.requiredRole === "admin" ? "the finance lead" : "the kitchen manager"}`;
    case "notification.sent":
      return p.outcome === "no_recipient"
        ? "Nobody with that role could be notified"
        : `${p.kind === "request" ? "Approver notified" : p.kind === "reminder" ? "Reminder sent" : "Others told it's decided"} via ${p.channel === "web_push" ? "phone" : "webhook"}${p.outcome === "failed" ? " (delivery failed)" : ""}`;
    case "approval.decided":
      return `${p.approver?.displayName} ${p.action === "approve" ? "approved" : `rejected: ${p.reason}`}`;
    case "approval.expired":
      return "Approval expired without a decision";
    case "approval.superseded":
      return `${p.approver?.displayName} changed the request`;
    case "requote.started":
      return `Fresh offers requested (attempt ${p.attempt})`;
    case "order.submitted":
      return `Order ${p.orderId} submitted · ${money(p.total)}`;
    case "transaction.closed":
      return `Closed: ${p.outcome}`;
    case "auth.denied":
      return `Refused: ${String(p.reason).replace(/_/g, " ")}`;
    default:
      return e.type ?? "Step";
  }
}

export function Timeline({ events }: { events: AuditEvent[] }) {
  const own = events.filter((e) => e.type && e.type !== "chain.checkpoint");
  return (
    <ol className="relative">
      {own.map((e, i) => {
        const hidden = !e.payload;
        const Icon = hidden ? Lock : ICONS[e.type!] ?? CheckCircle2;
        return (
          <li key={e.seq} className="flex gap-3 pb-4">
            <div className="flex flex-col items-center">
              <span className={cx("flex size-7 items-center justify-center rounded-full", hidden ? "bg-muted text-ink-3" : "bg-ok text-ok-fg")}>
                <Icon className="size-3.5" aria-hidden />
              </span>
              {i < own.length - 1 && <span className="mt-1 w-px flex-1 bg-line-strong" />}
            </div>
            <div className="pt-0.5">
              <span className="font-mono text-[11px] text-ink-3">{preciseTime(e.time)} · #{e.seq}</span>
              <p className={cx("text-[13px]", hidden ? "text-ink-3" : "text-ink")}>{describe(e)}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function ChainStrip({ steps }: { steps: { seq: number; ok: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Chain of steps">
      {steps.map((s, i) => (
        <div key={s.seq} className="flex items-center gap-1.5">
          <span
            className={cx("flex size-10 items-center justify-center rounded-[10px] text-[12px] tabular transition-colors", s.ok ? "bg-ok text-ok-fg" : "bg-stop text-stop-fg")}
            title={`Step ${i + 1} · #${s.seq}`}
          >
            {i + 1}
          </span>
          {i < steps.length - 1 && <Link2 className={cx("size-3.5", s.ok ? "text-ink-3" : "text-stop-fg")} aria-hidden />}
        </div>
      ))}
    </div>
  );
}
