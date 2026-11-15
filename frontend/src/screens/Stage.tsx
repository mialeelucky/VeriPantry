// Recording layout (frontend.md §9): buyer flow left, the Head Chef's phone right,
// live status below. The phone here is a phone-sized window, and says so.

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { gatewayApi } from "../api/gateway";
import type { Approval, TransactionView } from "../api/types";
import { SessionProvider, useSession } from "../auth/session";
import { PhoneFrame } from "../components/misc";
import { Mark, StatusBadge } from "../components/ui";
import { money, time } from "../lib/format";
import { roleName, statusTone } from "../lib/status";
import ApprovalFlow from "./approvals/ApprovalFlow";
import ApprovalInbox from "./approvals/ApprovalInbox";
import BuyFlow from "./buy/BuyFlow";

export default function Stage() {
  const [tx, setTx] = useState<TransactionView | null>(null);
  const onTx = useCallback((t: TransactionView | null) => setTx(t), []);
  return (
    <div className="min-h-screen bg-bg px-8 py-6">
      <div className="mb-5 flex items-center gap-2">
        <Mark />
        <span className="font-medium">VeriPantry</span>
        <span className="text-ink-3">· Hotel 123 procurement</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-8">
        <div>
          <p className="mb-3 text-[12px] text-ink-3">The chef asks the purchasing agent</p>
          <BuyFlow embedded onTransaction={onTx} />
        </div>
        <div>
          <p className="mb-3 text-[12px] text-ink-3">Head Chef's phone</p>
          <SessionProvider storageKey="vp.session.stage-phone" autoPersona="u_chef">
            <Phone />
          </SessionProvider>
        </div>
      </div>
      <StatusStrip tx={tx} />
    </div>
  );
}

function Phone() {
  const { token, ready } = useSession();
  const [open, setOpen] = useState<string | null>(null);
  const [banner, setBanner] = useState<Approval | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const approvals = useQuery({
    queryKey: ["stage-approvals", token],
    queryFn: () => gatewayApi.approvals(token!, "PENDING"),
    enabled: !!token,
    refetchInterval: 1500,
  });

  // An in-app banner stands in for the system notification in this window.
  useEffect(() => {
    if (!approvals.data) return;
    const ids = new Set(approvals.data.map((a) => a.approvalId));
    if (seen.current === null) {
      seen.current = ids;
      return;
    }
    const fresh = approvals.data.find((a) => !seen.current!.has(a.approvalId) && a.requiredRole === "approver");
    seen.current = ids;
    if (fresh) setBanner(fresh);
  }, [approvals.data]);

  return (
    <PhoneFrame caption="Phone-sized window · the notification is shown in-app here">
      <div className="relative min-h-full">
        {banner && !open && (
          <button
            type="button"
            onClick={() => {
              setOpen(banner.approvalId);
              setBanner(null);
            }}
            className="vp-step absolute inset-x-2 top-2 z-10 flex gap-3 rounded-[16px] border border-line bg-surface/95 p-3 text-left shadow-lg backdrop-blur"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-ok text-ok-fg">
              <Bell className="size-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-[12px] text-ink-3">VeriPantry · now</span>
              <span className="block font-medium leading-5">Approval needed · {money(banner.total)}</span>
              <span className="block truncate text-[13px] text-ink-2">
                {banner.title} · expires {time(banner.deadline)}
              </span>
            </span>
          </button>
        )}
        {!ready || !token ? (
          <p className="p-6 text-ink-3">Signing in…</p>
        ) : open ? (
          <ApprovalFlow approvalId={open} onBack={() => setOpen(null)} />
        ) : (
          <ApprovalInbox onOpen={setOpen} showSettingsLink={false} />
        )}
      </div>
    </PhoneFrame>
  );
}

function StatusStrip({ tx }: { tx: TransactionView | null }) {
  if (!tx) return <div className="mt-6 rounded-[14px] border border-line bg-surface px-5 py-3 text-ink-3">No transaction yet.</div>;
  const text =
    tx.status === "PENDING_APPROVAL"
      ? `Waiting for ${roleName(tx.approval?.requiredRole)} · expires ${time(tx.approval?.deadline)}`
      : tx.status === "ORDERED"
        ? `${tx.order?.approval === "auto" ? "Ordered by the agent" : `Approved by ${roleName(tx.approval?.requiredRole)} · ordered`} · ${money(tx.order?.total)}`
        : tx.closed?.summary ?? tx.status;
  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-line bg-surface px-5 py-3">
      <span className="flex items-center gap-3">
        <StatusBadge tone={statusTone(tx.status)}>{tx.status.replace(/_/g, " ").toLowerCase()}</StatusBadge>
        <span>
          {tx.transactionId} · {text}
        </span>
      </span>
      {tx.auditRef && <span className="font-mono text-[12px] text-ink-3">audit receipt #{tx.auditRef.seq} · {tx.auditRef.hash.slice(7, 19)}…</span>}
    </div>
  );
}
