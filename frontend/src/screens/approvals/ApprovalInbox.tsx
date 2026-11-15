// Approval inbox (frontend.md §5.2, step 1). Phone first.

import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCircle2, ChevronRight, Clock, Lock } from "lucide-react";
import { Link } from "react-router-dom";
import { gatewayApi } from "../../api/gateway";
import type { Approval } from "../../api/types";
import { useSession } from "../../auth/session";
import { useNow } from "../../components/misc";
import { Notice, Spinner, cx } from "../../components/ui";
import { duration, moneyShort, shortName } from "../../lib/format";
import { useGatewayOffset } from "../../lib/clock";
import { problemMessage } from "../../lib/problems";
import { roleName } from "../../lib/status";
import { canDecide, shortReason } from "./shared";

export default function ApprovalInbox({ onOpen, showSettingsLink = true }: { onOpen: (id: string) => void; showSettingsLink?: boolean }) {
  const { token, person } = useSession();
  const now = useNow(1000) + useGatewayOffset();
  const q = useQuery({
    queryKey: ["approvals", token],
    queryFn: () => gatewayApi.approvals(token!),
    enabled: !!token,
    refetchInterval: 3000,
  });
  const pending = (q.data ?? []).filter((a) => a.state === "PENDING").sort((a, b) => a.deadline.localeCompare(b.deadline));
  const handled = (q.data ?? []).filter((a) => a.state !== "PENDING").slice(-4).reverse();
  const mine = pending.filter((a) => canDecide(person, a.requiredRole)).length;

  return (
    <div className="vp-step px-4 pb-6 pt-4">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-[22px] font-medium leading-7">Approvals</h1>
          <p className="text-ink-2">{mine === 0 ? "Nothing needs you right now" : `${mine} request${mine > 1 ? "s" : ""} need${mine > 1 ? "" : "s"} you`}</p>
        </div>
        {showSettingsLink && (
          <Link to="/settings/notifications" className="rounded-full p-2 text-ink-2 hover:bg-muted" aria-label="Notification settings">
            <Bell className="size-5" />
          </Link>
        )}
      </div>

      {q.isLoading && (
        <div className="mt-6">
          <Spinner label="Loading requests" />
        </div>
      )}
      {q.isError && (
        <div className="mt-4">
          <Notice tone="stop">{problemMessage(q.error)}</Notice>
        </div>
      )}

      <ul className="mt-5 space-y-2.5">
        {pending.map((a) => (
          <InboxRow key={a.approvalId} a={a} now={now} allowed={canDecide(person, a.requiredRole)} onOpen={onOpen} />
        ))}
      </ul>

      {handled.length > 0 && (
        <>
          <p className="mt-7 text-[12px] text-ink-3">Handled recently</p>
          <ul className="mt-1 divide-y divide-line">
            {handled.map((a) => (
              <li key={a.approvalId} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                <span className="truncate text-ink-2">{shortName(a.title, 34)}</span>
                <span className={cx("inline-flex shrink-0 items-center gap-1", a.state === "APPROVED" ? "text-ok-fg" : "text-ink-3")}>
                  {a.state === "APPROVED" && <CheckCircle2 className="size-3.5" aria-hidden />}
                  {a.state.charAt(0) + a.state.slice(1).toLowerCase()}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function InboxRow({ a, now, allowed, onOpen }: { a: Approval; now: number; allowed: boolean; onOpen: (id: string) => void }) {
  const left = new Date(a.deadline).getTime() - now;
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span className="font-medium leading-5">{shortName(a.title, 40)}</span>
        <span className="tabular shrink-0 font-medium">{moneyShort(a.total)}</span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        {allowed ? (
          <span className="rounded-full bg-attn px-2.5 py-0.5 text-[12px] text-attn-fg">{shortReason(a)}</span>
        ) : (
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-[12px] text-ink-2">Needs {roleName(a.requiredRole)}</span>
        )}
        <span className={cx("inline-flex items-center gap-1 text-[12px]", allowed ? "text-attn-fg" : "text-ink-3")}>
          {allowed ? <Clock className="size-3.5" aria-hidden /> : <Lock className="size-3.5" aria-hidden />}
          {allowed ? (left > 0 ? duration(left) : "Expired") : "Not your role"}
        </span>
      </div>
    </>
  );
  if (!allowed) return <li className="rounded-[14px] border border-line p-3.5 opacity-70">{body}</li>;
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(a.approvalId)}
        className="group block w-full rounded-[14px] border-2 border-attn-fg/40 bg-surface p-3.5 text-left hover:border-attn-fg"
      >
        {body}
        <span className="mt-2 flex items-center justify-end text-[12px] text-ink-3 group-hover:text-ink">
          Review <ChevronRight className="size-3.5" aria-hidden />
        </span>
      </button>
    </li>
  );
}
