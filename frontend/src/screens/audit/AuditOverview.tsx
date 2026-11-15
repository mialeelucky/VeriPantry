// Audit overview (frontend.md §5.3, tab 1).

import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { gatewayApi } from "../../api/gateway";
import { useSession } from "../../auth/session";
import { MetricTile, Notice, Spinner, StatusBadge } from "../../components/ui";
import { day, money, time } from "../../lib/format";
import { problemMessage } from "../../lib/problems";
import { summaryPill } from "../../lib/status";

export default function AuditOverview() {
  const { token, person } = useSession();
  const list = useQuery({ queryKey: ["audit-list", token], queryFn: () => gatewayApi.auditList(token!), enabled: !!token, refetchInterval: 5000 });
  const rows = [...(list.data ?? [])].reverse();
  const ordered = rows.filter((r) => r.outcome === "ORDERED");
  const byAgent = ordered.filter((r) => r.decidedBy === "agent").length;
  const blocked = rows.filter((r) => r.outcome === "DENIED").length;

  return (
    <div className="vp-step mx-auto w-full max-w-[1080px]">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-[22px] font-medium">Audit</h1>
          <p className="text-ink-2">
            {person?.kind === "staff" ? "Every customer's transactions, as Valio Aimo sees them." : "Every purchase your agent handled, and why."}
          </p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <MetricTile label="Orders" value={ordered.length} />
        <MetricTile label="Decided by the agent" value={byAgent} sub={`of ${ordered.length}`} />
        <MetricTile label="Blocked by a rule" value={blocked} />
      </div>

      <div className="mt-6 rounded-[16px] border border-line bg-surface">
        <div className="border-b border-line px-5 py-3 text-[12px] text-ink-3">Transactions</div>
        {list.isLoading && (
          <div className="p-5">
            <Spinner label="Loading" />
          </div>
        )}
        {list.isError && (
          <div className="p-5">
            <Notice tone="stop">{problemMessage(list.error)}</Notice>
          </div>
        )}
        {list.data && rows.length === 0 && <p className="p-5 text-ink-2">No transactions yet. Start one from Buy.</p>}
        <ul className="divide-y divide-line">
          {rows.map((r) => {
            const pill = summaryPill(r);
            return (
              <li key={r.transactionId}>
                <Link to={`/audit/${encodeURIComponent(r.transactionId)}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-muted/60">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{r.title}</p>
                    <p className="text-[12px] text-ink-3">
                      {r.transactionId} · {day(r.createdAt)} {time(r.createdAt)}
                      {person?.kind === "staff" ? ` · ${r.customer}` : ""}
                    </p>
                  </div>
                  <span className="tabular hidden w-28 text-right sm:block">{money(r.total)}</span>
                  <StatusBadge tone={pill.tone} className="shrink-0">
                    {pill.text}
                  </StatusBadge>
                  <ChevronRight className="size-4 shrink-0 text-ink-3" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
