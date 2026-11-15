// Review → Decide → Result for one approval request (frontend.md §5.2).

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, Clock, SlidersHorizontal, X } from "lucide-react";
import { gatewayApi } from "../../api/gateway";
import type { Approval, Plan, TransactionView } from "../../api/types";
import { useSession } from "../../auth/session";
import { CompareRow, Countdown } from "../../components/misc";
import { PlanDetailSheet } from "../../components/plans";
import { Button, Notice, Pill, Spinner, cx } from "../../components/ui";
import { allergenLabel, attributeLabel, day, deviationLabel, deviationValue, money, preferenceLabel, qty, shortName } from "../../lib/format";
import { problemMessage } from "../../lib/problems";
import { roleName } from "../../lib/status";
import { canDecide, reasonsOf } from "./shared";

type Stage = "review" | "decide" | "result";

export default function ApprovalFlow({ approvalId, onBack }: { approvalId: string; onBack: () => void }) {
  const { token, person } = useSession();
  const qc = useQueryClient();
  const [stage, setStage] = useState<Stage>("review");
  const [result, setResult] = useState<{ kind: "approved" | "rejected" | "modified"; tx: TransactionView; reason?: string } | null>(null);

  const approval = useQuery({
    queryKey: ["approval", approvalId, token],
    queryFn: () => gatewayApi.approval(token!, approvalId),
    enabled: !!token,
    refetchOnWindowFocus: true,
  });
  const tx = useQuery({
    queryKey: ["approval-tx", approval.data?.orderDraftId, token],
    queryFn: () => gatewayApi.transaction(token!, approval.data!.orderDraftId),
    enabled: !!token && !!approval.data,
  });

  if (approval.isLoading || (approval.data && tx.isLoading)) return <Shell onBack={onBack}><Spinner label="Loading request" /></Shell>;
  if (approval.isError) return <Shell onBack={onBack}><Notice tone="stop">{problemMessage(approval.error)}</Notice></Shell>;
  const a = approval.data!;
  const view = tx.data;
  const line = view?.lines?.[0];
  const plan = line?.plans.find((p) => p.rank === a.lines[0]?.recommendedRank);

  if (stage === "result" && result) return <Result result={result} onBack={onBack} />;

  if (a.state !== "PENDING") {
    return (
      <Shell onBack={onBack}>
        <Notice tone="neutral" title="Nothing to do">
          This request was already {a.state.toLowerCase()}. Nothing more is needed from you.
        </Notice>
      </Shell>
    );
  }

  const done = (kind: "approved" | "rejected" | "modified", t: TransactionView, reason?: string) => {
    setResult({ kind, tx: t, reason });
    setStage("result");
    qc.invalidateQueries({ queryKey: ["approvals"] });
  };

  return stage === "review" ? (
    <Review a={a} view={view} plan={plan} onBack={onBack} onNext={() => setStage("decide")} />
  ) : (
    <Decide a={a} plan={plan} allowed={canDecide(person, a.requiredRole)} token={token!} onBack={() => setStage("review")} onDone={done} />
  );
}

function Shell({ children, onBack, title }: { children: React.ReactNode; onBack: () => void; title?: string }) {
  return (
    <div className="vp-step px-4 pb-6 pt-3">
      <button type="button" onClick={onBack} className="-ml-1 mb-3 inline-flex items-center gap-1 rounded-md px-1 py-1 text-[13px] text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> {title ?? "Approvals"}
      </button>
      {children}
    </div>
  );
}

function Review({ a, view, plan, onBack, onNext }: { a: Approval; view?: TransactionView; plan?: Plan; onBack: () => void; onNext: () => void }) {
  const [details, setDetails] = useState(false);
  const reasons = reasonsOf(a);
  const reqLine = view?.request?.lines[0];
  const spec = reqLine?.spec ?? {};
  const deviated = new Set(plan?.deviations.map((d) => d.attribute) ?? []);
  const unchanged = [
    ...(spec.requiredAttributes ?? []).map(attributeLabel),
    ...(spec.excludedAllergens ?? []).map((x) => `No ${allergenLabel(x)}`),
    ...(spec.preferredAttributes ?? []).filter((p) => !deviated.has(p.split(":")[0])).map(preferenceLabel),
    ...(plan?.onTime ? [`Arrives ${day(plan.items[0]?.availableDate)}`] : []),
    ...(plan?.complete ? [`Full ${qty(plan.covered)}`] : []),
  ];
  return (
    <Shell onBack={onBack}>
      <p className="text-[12px] text-ink-3">Requested by your procurement agent</p>
      <h1 className="mt-0.5 text-[20px] font-medium leading-7">{shortName(a.title, 60)}</h1>
      <p className="tabular mt-0.5 text-ink-2">
        {money(a.total)} · <Countdown deadline={a.deadline} />
      </p>

      <div className="mt-4 rounded-[14px] bg-attn p-3.5 text-attn-fg">
        <p className="flex items-center gap-1.5 font-medium">
          <AlertTriangle className="size-4" aria-hidden /> Why you're asked
        </p>
        <ul className="mt-1.5 space-y-1 text-[13px] leading-5">
          {reasons.map((r) => (
            <li key={r.message}>{r.message}</li>
          ))}
        </ul>
      </div>

      {plan && plan.deviations.length > 0 && (
        <div className="mt-4 space-y-3">
          {plan.deviations.map((d) => (
            <CompareRow
              key={d.attribute}
              label={deviationLabel(d.attribute)}
              asked={deviationValue(d.attribute, d.requested)}
              proposed={deviationValue(d.attribute, d.proposed)}
              note={d.share && Number(d.share) < 1 ? `For ${Math.round(Number(d.share) * 100)} % of the quantity` : undefined}
            />
          ))}
        </div>
      )}
      {plan && !plan.complete && <div className="mt-3"><CompareRow label="Quantity" asked={qty(reqLine?.quantity)} proposed={qty(plan.covered)} /></div>}

      {unchanged.length > 0 && (
        <>
          <p className="mt-4 mb-2 text-[12px] text-ink-3">Unchanged</p>
          <div className="flex flex-wrap gap-1.5">
            {unchanged.map((u) => (
              <Pill key={u} kind="unchanged">
                {u}
              </Pill>
            ))}
          </div>
        </>
      )}

      {plan && (
        <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[13px]">
          <span className="text-ink-2">Proposed</span>
          <button type="button" onClick={() => setDetails(true)} className="text-right underline-offset-4 hover:underline">
            {shortName(plan.items.map((i) => i.name).join(" + "), 34)} · {money(plan.items[0]?.unitCost)}/{plan.covered.unit}
          </button>
        </div>
      )}

      <Button variant="primary" className="mt-5 w-full" onClick={onNext}>
        Make a decision
      </Button>
      <PlanDetailSheet plan={plan ?? null} line={view?.lines?.[0]} open={details} onOpenChange={setDetails} />
    </Shell>
  );
}

function Decide({
  a,
  plan,
  allowed,
  token,
  onBack,
  onDone,
}: {
  a: Approval;
  plan?: Plan;
  allowed: boolean;
  token: string;
  onBack: () => void;
  onDone: (kind: "approved" | "rejected" | "modified", tx: TransactionView, reason?: string) => void;
}) {
  const [mode, setMode] = useState<"none" | "reject" | "modify">("none");
  const [reason, setReason] = useState("");
  const [quantity, setQuantity] = useState(plan ? String(Number(plan.covered.value)) : "");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function run(kind: "approve" | "reject" | "modify") {
    setError(null);
    if (kind === "reject" && !reason.trim()) return setFieldError("Enter a reason first");
    if (kind === "modify" && !(Number(quantity) > 0)) return setFieldError("Enter a quantity first");
    setBusy(kind);
    try {
      const body =
        kind === "approve"
          ? { action: "approve" }
          : kind === "reject"
            ? { action: "reject", reason: reason.trim() }
            : { action: "modify", changes: { lines: [{ lineId: a.lines[0].lineId, quantity: { value: Number(quantity), unit: plan?.covered.unit ?? "L" } }] } };
      const tx = await gatewayApi.decide(token, a.approvalId, body);
      onDone(kind === "approve" ? "approved" : kind === "reject" ? "rejected" : "modified", tx, reason.trim());
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Shell onBack={onBack} title="Review">
      <p className="text-[12px] text-ink-3">Your decision</p>
      <h1 className="mt-0.5 text-[20px] font-medium leading-7">Approve this order?</h1>
      <p className="tabular mt-0.5 text-ink-2">
        {money(a.total)} · {plan ? `${qty(plan.covered)} · arrives ${day(plan.items[0]?.availableDate)}` : ""}
      </p>

      {error && (
        <div className="mt-4">
          <Notice tone="stop">{error}</Notice>
        </div>
      )}

      {!allowed ? (
        <div className="mt-5">
          <Notice tone="neutral" title={`This needs ${roleName(a.requiredRole)}`}>
            Ask {roleName(a.requiredRole)} to approve it.
          </Notice>
        </div>
      ) : (
        <div className="mt-5 space-y-2.5">
          <Button variant="ok" className="h-12 w-full text-[15px]" onClick={() => run("approve")} busy={busy === "approve"}>
            <Check className="size-5" aria-hidden /> Approve
          </Button>

          <Button variant="danger" className="w-full" onClick={() => setMode(mode === "reject" ? "none" : "reject")}>
            <X className="size-4" aria-hidden /> Reject
          </Button>
          {mode === "reject" && (
            <div className="rounded-[12px] bg-muted p-3">
              <label htmlFor="reason" className="text-[12px] text-ink-3">
                Reason (sent to the agent)
              </label>
              <input
                id="reason"
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value);
                  setFieldError(null);
                }}
                placeholder="We only buy Arla"
                className="mt-1 h-10 w-full rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-ink"
              />
              {fieldError && <p className="mt-1 text-[13px] text-stop-fg">{fieldError}</p>}
              <Button variant="danger" className="mt-2 w-full" onClick={() => run("reject")} busy={busy === "reject"}>
                Send rejection
              </Button>
            </div>
          )}

          <Button variant="secondary" className="w-full" onClick={() => setMode(mode === "modify" ? "none" : "modify")}>
            <SlidersHorizontal className="size-4" aria-hidden /> Change quantity
          </Button>
          {mode === "modify" && (
            <div className="rounded-[12px] bg-muted p-3">
              <label htmlFor="qty" className="text-[12px] text-ink-3">
                New quantity ({plan?.covered.unit ?? "L"})
              </label>
              <input
                id="qty"
                type="number"
                min={0}
                value={quantity}
                onChange={(e) => {
                  setQuantity(e.target.value);
                  setFieldError(null);
                }}
                className="tabular mt-1 h-10 w-full rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-ink"
              />
              {fieldError && <p className="mt-1 text-[13px] text-stop-fg">{fieldError}</p>}
              <Button variant="secondary" className="mt-2 w-full" onClick={() => run("modify")} busy={busy === "modify"}>
                Send to the agent
              </Button>
            </div>
          )}
        </div>
      )}

      <p className="mt-5 flex items-center justify-center gap-1 text-center text-[12px] text-ink-3">
        <Clock className="size-3.5" aria-hidden /> Expires at {new Date(a.deadline).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · never auto-approved
      </p>
    </Shell>
  );
}

function Result({ result, onBack }: { result: { kind: "approved" | "rejected" | "modified"; tx: TransactionView; reason?: string }; onBack: () => void }) {
  const { kind, tx } = result;
  const ok = kind === "approved" && tx.status === "ORDERED";
  const title = kind === "approved" ? (ok ? "Approved and ordered" : "Approved") : kind === "rejected" ? "Rejected" : "Changed";
  const sentence =
    kind === "approved"
      ? ok
        ? `Your agent placed the order · ${money(tx.order?.total)}.`
        : tx.closed?.summary ?? "The approval was recorded."
      : kind === "rejected"
        ? `Reason sent to your agent: "${result.reason}". Nothing was ordered.`
        : `Continued as ${tx.transactionId} · ${tx.status === "ORDERED" ? `ordered, ${money(tx.order?.total)}` : tx.status.toLowerCase().replace(/_/g, " ")}.`;
  return (
    <div className="vp-step px-4 pb-6 pt-10 text-center">
      <div className={cx("mx-auto flex size-16 items-center justify-center rounded-full", kind === "rejected" ? "bg-stop text-stop-fg" : "bg-ok text-ok-fg")}>
        {kind === "rejected" ? <X className="size-8" aria-hidden /> : <Check className="size-8" aria-hidden />}
      </div>
      <h1 className="mt-4 text-[20px] font-medium" aria-live="polite">
        {title}
      </h1>
      <p className="mt-1.5 text-ink-2">{sentence}</p>
      <div className="mt-6 space-y-2 rounded-[12px] bg-muted p-3 text-left text-[13px]">
        <div className="flex justify-between">
          <span className="text-ink-2">Recorded in</span>
          <span className="font-medium">Audit trail · {tx.transactionId}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-ink-2">Status</span>
          <span className="font-medium">{tx.status.charAt(0) + tx.status.slice(1).toLowerCase().replace(/_/g, " ")}</span>
        </div>
      </div>
      <Button variant="primary" className="mt-6 w-full" onClick={onBack}>
        Back to approvals
      </Button>
    </div>
  );
}
