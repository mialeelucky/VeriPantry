// One transaction's audit: Story, Timeline, Integrity, and PDF export (frontend.md §5.3).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bug, Download, RotateCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { gatewayApi } from "../../api/gateway";
import type { TransactionView, VerifyResponse } from "../../api/types";
import { useSession } from "../../auth/session";
import { ChainStrip, Timeline } from "../../components/audit";
import { Button, Notice, Spinner, StatusBadge, cx } from "../../components/ui";
import { amount, capitalize, day, money, planName, shortName } from "../../lib/format";
import { problemMessage } from "../../lib/problems";
import { roleName, statusTone } from "../../lib/status";

const TABS = ["Story", "Timeline", "Integrity"] as const;
type Tab = (typeof TABS)[number];

export default function TransactionAudit() {
  const { transactionId = "" } = useParams();
  const { token, person } = useSession();
  const staff = person?.kind === "staff";
  const [tab, setTab] = useState<Tab>("Story");
  const [view, setView] = useState<"buyer" | "valio">(staff ? "valio" : "buyer");
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const tx = useQuery({ queryKey: ["audit-tx", transactionId, token], queryFn: () => gatewayApi.transaction(token!, transactionId), enabled: !!token });

  async function exportPdf() {
    setExporting(true);
    setExportError(null);
    try {
      await gatewayApi.downloadPdf(token!, transactionId, view);
    } catch (e) {
      setExportError(problemMessage(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="vp-step mx-auto w-full max-w-[1080px]">
      <Link to="/audit" className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 py-1 text-[13px] text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Audit
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[12px] text-ink-3">{transactionId}</p>
          <h1 className="text-[22px] font-medium leading-7">{tx.data?.title ?? "Transaction"}</h1>
        </div>
        <div className="flex items-center gap-2">
          {tx.data && <StatusBadge tone={statusTone(tx.data.status)}>{capitalize(tx.data.status.toLowerCase().replace(/_/g, " "))}</StatusBadge>}
          <Button onClick={exportPdf} busy={exporting}>
            <Download className="size-4" aria-hidden /> Export PDF
          </Button>
        </div>
      </div>
      {exportError && (
        <div className="mt-3">
          <Notice tone="stop">{exportError}</Notice>
        </div>
      )}

      <div className="mt-5 flex items-center justify-between gap-3">
        <div className="flex gap-1 rounded-full bg-muted p-1" role="tablist">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx("rounded-full px-4 py-1.5 text-[13px]", tab === t ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink")}
            >
              {t}
            </button>
          ))}
        </div>
        {staff && tab === "Timeline" && (
          <div className="flex overflow-hidden rounded-full border border-line-strong text-[12px]" role="group" aria-label="View">
            {(["buyer", "valio"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} className={cx("px-3.5 py-1.5", view === v ? "bg-primary text-on-primary" : "text-ink-2")}>
                {v === "buyer" ? "Buyer view" : "Valio view"}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 rounded-[16px] border border-line bg-surface p-6">
        {tx.isLoading && <Spinner label="Loading" />}
        {tx.isError && <Notice tone="stop">{problemMessage(tx.error)}</Notice>}
        {tx.data && tab === "Story" && <Story tx={tx.data} />}
        {tab === "Timeline" && <TimelineTab txId={transactionId} token={token!} view={staff ? view : undefined} />}
        {tab === "Integrity" && <Integrity txId={transactionId} token={token!} staff={staff} />}
      </div>
    </div>
  );
}

function Story({ tx }: { tx: TransactionView }) {
  const line = tx.lines?.[0];
  const reqLine = tx.request?.lines[0];
  const chosenRank = tx.status === "ORDERED" ? line?.selectedRank : line?.recommendedRank;
  const plan = line?.plans.find((p) => p.rank === chosenRank) ?? line?.plans[0];
  const g = plan?.guardrail;
  // Order-level rules (spend, velocity) first, then the plan's own rules.
  const reasons =
    tx.status !== "ORDERED" || tx.order?.approval !== "auto" ? [...(tx.orderDecision?.reasons ?? []), ...(plan?.guardrail?.reasons ?? [])] : [];
  const steps: { tone: "neutral" | "ok" | "attention" | "stop"; title: string; text: string }[] = [
    {
      tone: "neutral",
      title: "Asked for",
      text: `${tx.title ?? ""} by ${day(tx.request?.deliverBy)}${reqLine?.spec?.excludedAllergens?.length ? ", allergy-safe" : ""}.`,
    },
    {
      tone: "neutral",
      title: "Found",
      text:
        line?.status === "fulfilled"
          ? `Available as asked: ${plan ? shortName(planName(plan.items), 60) : ""} for ${money(plan?.total)}.`
          : line?.reason?.code === "insufficient_quantity"
            ? `Only ${amount(line.reason.availableOnTime ?? 0)} ${line.reason.unit} of the requested product in time. ${line.plans.length} plans proposed; ${capitalize(plan?.label ?? "")} was ${shortName(planName(plan?.items ?? []), 50)} at ${money(plan?.total)}.`
            : line && line.plans.length
              ? `${line.plans.length} plans proposed; ${capitalize(plan?.label ?? "")} was ${shortName(planName(plan?.items ?? []), 50)} at ${money(plan?.total)}.`
              : tx.closed?.summary ?? "No acceptable plan.",
    },
    {
      tone: !g ? "neutral" : g.outcome === "ALLOW" && tx.order?.approval === "auto" ? "ok" : g.outcome === "DENY" ? "stop" : "attention",
      title: "Guardrails",
      text: !g
        ? "Not evaluated."
        : g.outcome === "ALLOW" && tx.order?.approval === "auto"
          ? "Every rule passed: within the agent's authority."
          : reasons.length
            ? `${reasons.map((r) => `${r.rule}: ${r.message}`).join(" ")}`
            : `Needed ${roleName(tx.approval?.requiredRole)}'s sign-off.`,
    },
    {
      tone: tx.status === "ORDERED" ? "ok" : tx.status === "PENDING_APPROVAL" ? "attention" : tx.status === "DENIED" || tx.status === "REJECTED" ? "stop" : "neutral",
      title: "Decided",
      text:
        tx.status === "PENDING_APPROVAL"
          ? `Waiting for ${roleName(tx.approval?.requiredRole)}.`
          : tx.order
            ? `${tx.closed?.summary ?? ""} Ordered ${money(tx.order.total)} under signed offer ${tx.order.lines[0]?.offerId}.`
            : tx.closed?.summary ?? "",
    },
  ];
  return (
    <div>
      <h2 className="text-[18px] font-medium">How this order was decided</h2>
      <ol className="mt-4 space-y-4">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span
              className={cx(
                "flex size-7 shrink-0 items-center justify-center rounded-full text-[12px]",
                s.tone === "ok" && "bg-ok text-ok-fg",
                s.tone === "attention" && "bg-attn text-attn-fg",
                s.tone === "stop" && "bg-stop text-stop-fg",
                s.tone === "neutral" && "bg-muted text-ink-2",
              )}
            >
              {i + 1}
            </span>
            <div>
              <p className="font-medium">{s.title}</p>
              <p className="text-ink-2">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function TimelineTab({ txId, token, view }: { txId: string; token: string; view?: "buyer" | "valio" }) {
  const q = useQuery({ queryKey: ["audit-events", txId, view, token], queryFn: () => gatewayApi.auditEvents(token, txId, view) });
  if (q.isLoading) return <Spinner label="Loading timeline" />;
  if (q.isError) return <Notice tone="stop">{problemMessage(q.error)}</Notice>;
  // Other customers' events arrive as opaque links (no transaction id): not part of this story.
  const own = q.data!.events.filter((e) => e.transactionId === txId);
  return (
    <div>
      <h2 className="mb-4 text-[18px] font-medium">Every step, in order</h2>
      <Timeline events={own} />
    </div>
  );
}

function Integrity({ txId, token, staff }: { txId: string; token: string; staff: boolean }) {
  const real = useQuery({ queryKey: ["audit-verify", txId, token], queryFn: () => gatewayApi.verify(token, txId) });
  const [tampered, setTampered] = useState<VerifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = tampered ?? real.data;

  async function tamper() {
    if (!real.data) return;
    const target = real.data.steps[Math.min(3, real.data.steps.length - 1)];
    setBusy(true);
    setError(null);
    try {
      setTampered(await gatewayApi.tamperPreview(token, txId, target.seq));
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (real.isLoading) return <Spinner label="Verifying" />;
  if (real.isError) return <Notice tone="stop">{problemMessage(real.error)}</Notice>;
  const r = shown!.result;
  const failedIndex = shown!.steps.findIndex((s) => !s.ok);
  return (
    <div>
      <h2 className="text-[18px] font-medium">Can this record be trusted?</h2>
      <p className="mt-1 text-ink-2">Each step is chained to the one before it and sealed with Valio Aimo's published key.</p>
      <div className="mt-5">
        <ChainStrip steps={shown!.steps} />
      </div>
      <div className="mt-5">
        {r.ok ? (
          <Notice tone="ok" title={`All ${shown!.steps.length} steps verified`}>
            Nothing has been changed since it was recorded.
          </Notice>
        ) : (
          <Notice tone="stop" title={`Verification failed at step ${failedIndex + 1}`}>
            {tampered ? "One recorded step was changed after the fact. " : ""}
            {capitalize(r.error ?? "")}. Every later link no longer matches.
          </Notice>
        )}
      </div>
      {error && (
        <div className="mt-3">
          <Notice tone="stop">{error}</Notice>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <span className="font-mono text-[12px] text-ink-3">
          {real.data?.result.checkpointSeq
            ? `Checkpoint #${real.data.result.checkpointSeq} · key ${real.data.result.checkpointKid}`
            : "Not sealed by a checkpoint yet"}
        </span>
        {staff &&
          (tampered ? (
            <Button onClick={() => setTampered(null)}>
              <RotateCcw className="size-4" aria-hidden /> Restore original
            </Button>
          ) : (
            <Button variant="danger" onClick={tamper} busy={busy}>
              <Bug className="size-4" aria-hidden /> Tamper with step {Math.min(4, shown!.steps.length)}
            </Button>
          ))}
      </div>
      {tampered && <p className="mt-2 text-[12px] text-ink-3">Demo only: the change was made to an in-memory copy. The stored record is untouched.</p>}
    </div>
  );
}
