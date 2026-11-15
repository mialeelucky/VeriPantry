// PlanCard, ScoreBars and PlanDetailSheet (frontend.md §5.1, step 4).

import * as Dialog from "@radix-ui/react-dialog";
import { ChevronRight, X } from "lucide-react";
import type { LineView, Plan } from "../api/types";
import { capitalize, day, deviationLabel, deviationValue, money, planName, qty, shortName } from "../lib/format";
import { outcomeBadge } from "../lib/status";
import { StatusBadge, cx } from "./ui";

export function PlanCard({
  plan,
  selected,
  onSelect,
  marker,
  onDetails,
}: {
  plan: Plan;
  selected?: boolean;
  onSelect?: () => void;
  marker?: React.ReactNode;
  onDetails?: () => void;
}) {
  const badge = outcomeBadge(plan.guardrail?.outcome, plan.guardrail?.requiredRole);
  return (
    <div
      role={onSelect ? "radio" : undefined}
      aria-checked={onSelect ? !!selected : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (onSelect && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cx(
        "rounded-[14px] border bg-surface p-4 text-left transition-colors",
        onSelect && "cursor-pointer hover:border-line-strong",
        selected ? "border-2 border-ok-fg p-[15px]" : "border-line",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[15px] font-medium leading-[22px]">
            {capitalize(plan.label ?? "plan")} · {shortName(planName(plan.items), 52)}
          </p>
          <p className="mt-0.5 text-[13px] text-ink-2">{capitalize(plan.rationaleText)}.</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="tabular text-[18px] font-medium leading-6">{money(plan.total)}</p>
          <p className="text-[12px] text-ink-3">{qty(plan.covered)}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={badge.tone}>{badge.text}</StatusBadge>
          {marker}
        </div>
        {onDetails && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDetails();
            }}
            className="inline-flex items-center gap-0.5 rounded-md px-1 text-[13px] text-ink-2 hover:text-ink"
          >
            Details <ChevronRight className="size-4" aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}

export function ScoreBars({ scores }: { scores: Plan["scores"] }) {
  const rows: [string, number][] = [
    ["Fit to your request", scores.fit],
    ["Cost", scores.cost],
    ["Delivery reliability", scores.reliability],
    ["Sustainability", scores.sustainability],
  ];
  return (
    <div className="space-y-2.5">
      {rows.map(([label, value]) => (
        <div key={label}>
          <div className="flex justify-between text-[12px]">
            <span className="text-ink-2">{label}</span>
            <span className="tabular text-ink">{Math.round(value * 100)}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-muted" aria-hidden>
            <div className="h-1.5 rounded-full bg-ink" style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const reasonText: Record<string, string> = {
  strategy_diversity: "Two plans of the same kind were already shown",
  duplicate_products: "Same products as a listed plan",
  ranked_below_third: "Ranked below third",
};

export function PlanDetailSheet({ plan, line, open, onOpenChange }: { plan: Plan | null; line?: LineView; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content className="fixed inset-x-0 bottom-0 max-h-[88vh] overflow-y-auto rounded-t-[20px] bg-surface p-6 shadow-xl outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[560px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-[20px]">
          {plan && (
            <>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[12px] text-ink-3">{capitalize(plan.label ?? "")} plan · {plan.strategy.replace(/_/g, " ")}</p>
                  <Dialog.Title className="text-[18px] font-medium leading-6">{money(plan.total)} · {qty(plan.covered)}</Dialog.Title>
                </div>
                <Dialog.Close className="rounded-md p-1 text-ink-2 hover:bg-muted" aria-label="Close">
                  <X className="size-5" />
                </Dialog.Close>
              </div>
              <Dialog.Description className="mt-1 text-[13px] text-ink-2">{capitalize(plan.rationaleText)}.</Dialog.Description>

              <h3 className="mt-5 text-[12px] text-ink-3">Products</h3>
              <ul className="mt-1.5 divide-y divide-line">
                {plan.items.map((i) => (
                  <li key={i.productId + i.salesUnits} className="flex justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate">{i.name}</p>
                      <p className="text-[12px] text-ink-3">
                        {i.productId} · {i.salesUnits} {i.salesUnit} · arrives {day(i.availableDate)} · {i.stockBasis === "warehouse" ? "in stock" : "supplier-direct"}
                      </p>
                    </div>
                    <p className="tabular shrink-0">{money(i.lineTotal)}</p>
                  </li>
                ))}
              </ul>

              {plan.deviations.length > 0 && (
                <>
                  <h3 className="mt-4 text-[12px] text-ink-3">Differs from your request</h3>
                  <ul className="mt-1.5 space-y-1">
                    {plan.deviations.map((d) => (
                      <li key={d.attribute} className="text-[13px]">
                        {deviationLabel(d.attribute)}: {deviationValue(d.attribute, d.requested)} → {deviationValue(d.attribute, d.proposed)}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <h3 className="mt-5 text-[12px] text-ink-3">Why it ranks here</h3>
              <div className="mt-2">
                <ScoreBars scores={plan.scores} />
              </div>

              <h3 className="mt-5 text-[12px] text-ink-3">Guardrails</h3>
              {plan.guardrail && plan.guardrail.reasons.length > 0 ? (
                <ul className="mt-1.5 space-y-1.5">
                  {plan.guardrail.reasons.map((r, idx) => (
                    <li key={idx} className="text-[13px]">
                      <span className="font-medium">{r.rule}</span> · {r.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 text-[13px] text-ink-2">Every guardrail rule passed.</p>
              )}

              {line && line.notPresented.length > 0 && (
                <>
                  <h3 className="mt-5 text-[12px] text-ink-3">Also considered, not shown</h3>
                  <ul className="mt-1.5 space-y-1 text-[13px] text-ink-2">
                    {line.notPresented.slice(0, 4).map((n, idx) => (
                      <li key={idx}>
                        {n.productIds.join(" + ")} · {money(n.total)} · {reasonText[n.reason] ?? n.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
