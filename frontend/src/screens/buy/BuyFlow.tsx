// Buyer flow, five steps (frontend.md §5.1).

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  FileSignature,
  Link2,
  MessageSquareText,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  UserCheck,
  XCircle,
  Clock,
} from "lucide-react";
import { agentApi } from "../../api/agent";
import { gatewayApi } from "../../api/gateway";
import type { DraftRequest, Plan, TransactionView } from "../../api/types";
import { PlanCard, PlanDetailSheet } from "../../components/plans";
import { ProgressList, type ProgressRow } from "../../components/misc";
import { StepIndicator, StepScreen } from "../../components/steps";
import { Button, Notice, Pill, StatusBadge, cx } from "../../components/ui";
import { allergenLabel, amount, attributeLabel, capitalize, day, money, preferenceLabel, qty, time } from "../../lib/format";
import { verifyOffer, type OfferCheck } from "../../lib/jws";
import { problemMessage } from "../../lib/problems";
import { roleName } from "../../lib/status";

const STEPS = ["Ask", "Confirm", "Working", "Choose", "Done"];
const TERMINAL = ["ORDERED", "DENIED", "REJECTED", "EXPIRED", "UNFULFILLABLE", "SUPERSEDED", "FAILED"];

export default function BuyFlow({ onTransaction, embedded }: { onTransaction?: (tx: TransactionView | null) => void; embedded?: boolean }) {
  const navigate = useNavigate();
  const params = useParams();
  const [step, setStep] = useState(0);
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<DraftRequest | null>(null);
  const [ambiguities, setAmbiguities] = useState<string[]>([]);
  const [txId, setTxId] = useState<string | null>(params.transactionId ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: agentApi.scenarios, staleTime: Infinity });

  const tx = useQuery({
    queryKey: ["agent-tx", txId],
    queryFn: () => agentApi.transaction(txId!),
    enabled: !!txId,
    refetchInterval: (q) => (q.state.data && !TERMINAL.includes(q.state.data.status) ? 2000 : false),
  });

  useEffect(() => onTransaction?.(tx.data ?? null), [tx.data, onTransaction]);

  // Resuming /buy/:id jumps straight to the plans.
  useEffect(() => {
    if (params.transactionId && step === 0) {
      setTxId(params.transactionId);
      setStep(3);
    }
  }, [params.transactionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => {
    setStep(0);
    setText("");
    setDraft(null);
    setAmbiguities([]);
    setTxId(null);
    setError(null);
    if (!embedded) navigate("/buy");
  };

  async function understand() {
    if (!text.trim()) {
      setFieldError("Describe what you need first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await agentApi.understand(text);
      setDraft(r.draft);
      setAmbiguities(r.ambiguities);
      setStep(1);
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!draft) return;
    if (draft.lines.some((l) => !l.quantity || Number(l.quantity.value) <= 0)) {
      setFieldError("Enter a quantity first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const view = await agentApi.submit(draft, text);
      setTxId(view.transactionId);
      if (!embedded) navigate(`/buy/${view.transactionId}`, { replace: true });
      setStep(2);
    } catch (e) {
      setError(problemMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cx("mx-auto w-full", embedded ? "max-w-none" : "max-w-[720px]")}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <StepIndicator steps={STEPS} current={step} />
      </div>
      {error && (
        <div className="mb-3">
          <Notice tone="stop">{error}</Notice>
        </div>
      )}

      {step === 0 && (
        <StepScreen
          eyebrow="Step 1 of 5"
          title="What does your kitchen need?"
          subtitle="Describe it in your own words. Your agent works out the details."
          primary={
            <Button variant="primary" onClick={understand} busy={busy}>
              Next <ArrowRight className="size-4" aria-hidden />
            </Button>
          }
        >
          <label htmlFor="need" className="sr-only">
            What you need
          </label>
          <textarea
            id="need"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setFieldError(null);
            }}
            rows={3}
            placeholder="We need 1,000 litres of lactose-free milk by Monday."
            className="w-full resize-none rounded-[14px] border border-line-strong bg-surface px-4 py-3 text-[15px] leading-6 outline-none placeholder:text-ink-3 focus:border-ink"
          />
          {fieldError && <p className="mt-1.5 text-[13px] text-stop-fg">{fieldError}</p>}
          {scenarios.data && (
            <div className="mt-4">
              <p className="mb-2 text-[12px] text-ink-3">Try a scenario</p>
              <div className="flex flex-wrap gap-2">
                {scenarios.data.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      setText(s.text);
                      setFieldError(null);
                    }}
                    className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-[13px] text-ink-2 hover:text-ink"
                  >
                    <Sparkles className="size-3.5" aria-hidden />
                    {s.title}
                  </button>
                ))}
              </div>
            </div>
          )}
          {scenarios.isError && <p className="mt-3 text-[13px] text-ink-3">Scenarios aren't available: {problemMessage(scenarios.error)}</p>}
        </StepScreen>
      )}

      {step === 1 && draft && (
        <ConfirmStep
          draft={draft}
          setDraft={(d) => {
            setDraft(d);
            setFieldError(null);
          }}
          ambiguities={ambiguities}
          fieldError={fieldError}
          busy={busy}
          onBack={() => setStep(0)}
          onStart={submit}
        />
      )}

      {step === 2 && (
        <WorkingStep tx={tx.data} onDone={() => setStep(3)} />
      )}

      {step === 3 && <ChooseStep tx={tx.data} loading={tx.isLoading} onNext={() => setStep(4)} onChange={() => setStep(draft ? 1 : 0)} />}

      {step === 4 && tx.data && <DoneStep tx={tx.data} onNew={reset} embedded={embedded} />}
    </div>
  );
}

// ---------------------------------------------------------------- step 2: confirm

function ConfirmStep({
  draft,
  setDraft,
  ambiguities,
  fieldError,
  busy,
  onBack,
  onStart,
}: {
  draft: DraftRequest;
  setDraft: (d: DraftRequest) => void;
  ambiguities: string[];
  fieldError: string | null;
  busy: boolean;
  onBack: () => void;
  onStart: () => void;
}) {
  const updateLine = (idx: number, patch: Partial<DraftRequest["lines"][number]>) =>
    setDraft({ ...draft, lines: draft.lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)) });

  return (
    <StepScreen
      eyebrow="Step 2 of 5"
      title="Is this right?"
      subtitle="Change anything before your agent starts."
      secondary={
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft className="size-4" aria-hidden /> Back
        </Button>
      }
      primary={
        <Button variant="primary" onClick={onStart} busy={busy}>
          Start <ArrowRight className="size-4" aria-hidden />
        </Button>
      }
    >
      {ambiguities.length > 0 && (
        <div className="mb-4 space-y-2">
          {ambiguities.map((a) => (
            <Notice key={a} tone="attention">
              {a}
            </Notice>
          ))}
        </div>
      )}
      {draft.lines.map((line, idx) => {
        const spec = line.spec ?? {};
        const must = [...(spec.requiredAttributes ?? []).map(attributeLabel), ...(spec.excludedAllergens ?? []).map((a) => `No ${allergenLabel(a)}`)];
        const nice = spec.preferredAttributes ?? [];
        return (
          <div key={line.lineId} className={cx(idx > 0 && "mt-6 border-t border-line pt-6")}>
            <p className="mb-3 text-[15px] font-medium">
              {line.productId ? (
                <>
                  A specific product <span className="font-normal text-ink-3">· {line.productId}</span>
                </>
              ) : (
                capitalize(spec.query ?? "Item")
              )}
            </p>
            <div className="mb-5 grid grid-cols-2 gap-3">
              <label className="rounded-[12px] bg-muted p-3.5">
                <span className="text-[12px] text-ink-3">Quantity</span>
                <span className="mt-1 flex items-baseline gap-2">
                  <input
                    type="number"
                    min={0}
                    inputMode="decimal"
                    value={line.quantity?.value ?? ""}
                    onChange={(e) => updateLine(idx, { quantity: { value: e.target.value, unit: line.quantity?.unit ?? "L" } })}
                    className="tabular w-full bg-transparent text-[22px] font-medium leading-7 outline-none"
                    aria-label="Quantity"
                  />
                  <select
                    value={line.quantity?.unit ?? "L"}
                    onChange={(e) => updateLine(idx, { quantity: { value: line.quantity?.value ?? "", unit: e.target.value as "L" } })}
                    className="bg-transparent text-[15px] text-ink-2 outline-none"
                    aria-label="Unit"
                  >
                    <option value="L">L</option>
                    <option value="KG">kg</option>
                    <option value="PCS">pcs</option>
                  </select>
                </span>
              </label>
              <label className="rounded-[12px] bg-muted p-3.5">
                <span className="text-[12px] text-ink-3">Deliver by</span>
                <input
                  type="date"
                  value={draft.deliverBy}
                  onChange={(e) => setDraft({ ...draft, deliverBy: e.target.value })}
                  className="tabular mt-1 block w-full bg-transparent text-[18px] font-medium leading-7 outline-none"
                  aria-label="Deliver by"
                />
              </label>
            </div>
            {must.length > 0 && (
              <>
                <p className="mb-2 text-[12px] text-ink-3">Must have</p>
                <div className="mb-4 flex flex-wrap gap-2">
                  {must.map((m) => (
                    <Pill key={m} kind="must">
                      {m}
                    </Pill>
                  ))}
                </div>
              </>
            )}
            {nice.length > 0 && (
              <>
                <p className="mb-2 text-[12px] text-ink-3">Nice to have</p>
                <div className="flex flex-wrap gap-2">
                  {nice.map((p) => (
                    <span key={p} className="inline-flex items-center gap-1.5 rounded-full border border-line-strong py-1 pl-3 pr-1.5 text-[13px]">
                      {preferenceLabel(p)}
                      <button
                        type="button"
                        aria-label={`Remove ${preferenceLabel(p)}`}
                        onClick={() => updateLine(idx, { spec: { ...spec, preferredAttributes: nice.filter((x) => x !== p) } })}
                        className="rounded-full p-0.5 text-ink-3 hover:bg-muted hover:text-ink"
                      >
                        <XCircle className="size-3.5" aria-hidden />
                      </button>
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        );
      })}
      {fieldError && <p className="mt-3 text-[13px] text-stop-fg">{fieldError}</p>}
    </StepScreen>
  );
}

// ---------------------------------------------------------------- step 3: working

function WorkingStep({ tx, onDone }: { tx?: TransactionView; onDone: () => void }) {
  const [skip, setSkip] = useState(false);
  const rows = useMemo<ProgressRow[]>(() => {
    if (!tx?.lines) return [];
    const c = tx.lines.reduce(
      (acc, l) => ({ products: acc.products + l.candidateCounts.retrieved + l.candidateCounts.substitutePool }),
      { products: 0 },
    );
    return [
      { icon: <MessageSquareText className="size-3.5" aria-hidden />, text: "Understood your request" },
      { icon: <Search className="size-3.5" aria-hidden />, text: `Checked ${c.products} products` },
      { icon: <Building2 className="size-3.5" aria-hidden />, text: "Asked the supplier for stock and price" },
      { icon: <FileSignature className="size-3.5" aria-hidden />, text: `Received ${Object.keys(tx.offers).length} signed offers` },
      { icon: <ShieldCheck className="size-3.5" aria-hidden />, text: "Checked your guardrails" },
    ];
  }, [tx]);
  const line = tx?.lines?.[0];
  const reason = line?.reason;
  const done = useCallback(onDone, [onDone]);
  return (
    <StepScreen
      eyebrow="Step 3 of 5"
      title="Your agent is on it"
      secondary={
        rows.length > 0 && (
          <Button variant="ghost" onClick={() => setSkip(true)}>
            Skip
          </Button>
        )
      }
    >
      {rows.length === 0 ? <p className="text-ink-3">Starting…</p> : <ProgressList rows={rows} onDone={done} skip={skip} />}
      {reason && line?.status !== "fulfilled" && (
        <div className="mt-5">
          <Notice tone="attention">
            {reason.code === "insufficient_quantity"
              ? `Only ${amount(reason.availableOnTime ?? 0)} of ${amount(reason.requested ?? 0)} ${reason.unit} can arrive on time, so I looked for alternatives.`
              : reason.code === "no_exact_match"
                ? "Nothing matched exactly within your must-haves, so I looked for alternatives."
                : "The requested product can't arrive on time, so I looked for alternatives."}
          </Notice>
        </div>
      )}
    </StepScreen>
  );
}

// ---------------------------------------------------------------- step 4: choose

function ChooseStep({ tx, loading, onNext, onChange }: { tx?: TransactionView; loading: boolean; onNext: () => void; onChange: () => void }) {
  const [detail, setDetail] = useState<Plan | null>(null);
  if (loading || !tx) return <StepScreen eyebrow="Step 4 of 5" title="Loading plans…" />;
  const line = tx.lines?.[0];
  const plans = line?.plans ?? [];
  const pending = tx.status === "PENDING_APPROVAL";
  const ordered = tx.status === "ORDERED";

  if (plans.length === 0) {
    return (
      <StepScreen
        eyebrow="Step 4 of 5"
        title="No way to get this as asked"
        primary={
          <Button variant="primary" onClick={onChange}>
            Change request
          </Button>
        }
      >
        <Notice tone={tx.status === "DENIED" ? "stop" : "neutral"}>{tx.closed?.summary ?? "No acceptable plan was found."}</Notice>
      </StepScreen>
    );
  }

  const markedRank = ordered ? line?.selectedRank : line?.recommendedRank;
  const subtitle = pending
    ? `This needs ${roleName(tx.approval?.requiredRole)}'s sign-off. They've been notified.`
    : ordered
      ? tx.order?.approval !== "auto"
        ? `${tx.closed?.summary ?? "Approved."} Your agent placed the order.`
        : line?.status === "fulfilled"
          ? "Available exactly as you asked."
          : "Your agent ordered the best plan within its authority."
      : tx.closed?.summary;

  return (
    <StepScreen
      eyebrow="Step 4 of 5"
      title={plans.length === 1 ? "Here's the plan" : `${plans.length === 2 ? "Two" : "Three"} ways to get it`}
      subtitle={subtitle}
      primary={
        <Button variant="primary" onClick={onNext}>
          {ordered ? "See confirmation" : "See status"} <ArrowRight className="size-4" aria-hidden />
        </Button>
      }
    >
      <div className="space-y-2.5" role="radiogroup" aria-label="Plans">
        {plans.map((p) => (
          <PlanCard
            key={p.rank}
            plan={p}
            selected={p.rank === markedRank}
            onDetails={() => setDetail(p)}
            marker={
              p.rank === markedRank &&
              (ordered ? (
                <StatusBadge tone="ok">{tx.order?.approval === "auto" ? "Ordered by your agent" : "Ordered after approval"}</StatusBadge>
              ) : pending ? (
                <StatusBadge tone="attention">Waiting for {roleName(tx.approval?.requiredRole)}</StatusBadge>
              ) : null)
            }
          />
        ))}
      </div>
      <PlanDetailSheet plan={detail} line={line} open={!!detail} onOpenChange={(o) => !o && setDetail(null)} />
    </StepScreen>
  );
}

// ---------------------------------------------------------------- step 5: done

function DoneStep({ tx, onNew, embedded }: { tx: TransactionView; onNew: () => void; embedded?: boolean }) {
  const [offer, setOffer] = useState<OfferCheck | null>(null);
  const verify = useQuery({ queryKey: ["agent-verify", tx.transactionId, tx.status], queryFn: () => agentApi.verify(tx.transactionId) });

  useEffect(() => {
    const offerId = tx.order?.lines[0]?.offerId;
    if (!offerId || !tx.offers[offerId]) return;
    gatewayApi
      .jwks()
      .then((j) => verifyOffer(tx.offers[offerId], j.keys))
      .then(setOffer)
      .catch(() => setOffer({ valid: false, reason: "Keys unavailable" }));
  }, [tx]);

  const line = tx.lines?.[0];
  const decidedBy =
    tx.order?.approval === "auto"
      ? "Your agent"
      : /chosen by (.+?) \(/.exec(line?.selectionText ?? "")?.[1] ?? roleName(tx.approval?.requiredRole);

  const view = {
    ORDERED: { tone: "ok", icon: CheckCircle2, title: "Ordered" },
    PENDING_APPROVAL: { tone: "attention", icon: Clock, title: "Sent for approval" },
    REJECTED: { tone: "stop", icon: XCircle, title: "Rejected" },
    DENIED: { tone: "stop", icon: XCircle, title: "Not allowed" },
  }[tx.status as string] ?? { tone: "neutral", icon: RotateCcw, title: capitalize(tx.status.toLowerCase().replace(/_/g, " ")) };
  const Icon = view.icon;
  const plan = line?.plans.find((p) => p.rank === (tx.status === "ORDERED" ? line.selectedRank : line.recommendedRank));
  const sentence =
    tx.status === "ORDERED" && tx.order
      ? `${plan ? qty(plan.covered) + " · " : ""}${money(tx.order.total)} · arrives ${day(plan?.items[0]?.availableDate)}`
      : tx.status === "PENDING_APPROVAL"
        ? `Waiting for ${roleName(tx.approval?.requiredRole)} · decide by ${time(tx.approval?.deadline)}. This page updates by itself.`
        : tx.closed?.summary ?? "";

  return (
    <StepScreen
      eyebrow="Step 5 of 5"
      title={
        <span className="flex flex-col items-center gap-3 pt-2 text-center">
          <span
            className={cx(
              "flex size-14 items-center justify-center rounded-full",
              view.tone === "ok" && "bg-ok text-ok-fg",
              view.tone === "attention" && "bg-attn text-attn-fg",
              view.tone === "stop" && "bg-stop text-stop-fg",
              view.tone === "neutral" && "bg-muted text-ink-2",
            )}
          >
            <Icon className="size-7" aria-hidden />
          </span>
          {view.title}
        </span>
      }
      subtitle={<span className="block text-center">{sentence}</span>}
      primary={
        <Button variant="primary" onClick={onNew}>
          New request
        </Button>
      }
      secondary={
        !embedded && (
          <Link to={`/audit/${encodeURIComponent(tx.transactionId)}`} className="text-[13px] text-ink-2 underline-offset-4 hover:underline">
            Open audit trail
          </Link>
        )
      }
    >
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3" aria-live="polite">
        <Tile label="Decided by" icon={<UserCheck className="size-4" aria-hidden />}>
          {tx.status === "ORDERED" ? decidedBy : tx.status === "PENDING_APPROVAL" ? "Not yet" : "—"}
        </Tile>
        <Tile label="Offer" icon={<FileSignature className="size-4" aria-hidden />}>
          {!tx.order ? "—" : offer === null ? "Checking…" : offer.valid ? <span className="text-ok-fg">Signature verified</span> : <span className="text-stop-fg">Signature could not be verified</span>}
        </Tile>
        <Tile label="Audit trail" icon={<Link2 className="size-4" aria-hidden />}>
          {verify.data ? (
            verify.data.result.ok ? (
              <span className="text-ok-fg">Verified</span>
            ) : (
              <span className="text-stop-fg">Failed at step {verify.data.result.errorSeq}</span>
            )
          ) : (
            "Checking…"
          )}
        </Tile>
      </div>
    </StepScreen>
  );
}

function Tile({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-[12px] bg-muted p-3">
      <p className="flex items-center gap-1.5 text-[12px] text-ink-3">
        {icon}
        {label}
      </p>
      <p className="mt-1 font-medium">{children}</p>
    </div>
  );
}
