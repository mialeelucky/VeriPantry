// ProgressList, CompareRow, Countdown, PhoneFrame (frontend.md §7).

import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight, Check } from "lucide-react";
import { useGatewayOffset } from "../lib/clock";
import { duration, time } from "../lib/format";
import { cx } from "./ui";

export interface ProgressRow {
  icon: ReactNode;
  text: string;
}

/** Replays real stages after the fact (frontend.md §5.1 step 3): skippable, at most ~4 s. */
export function ProgressList({ rows, onDone, skip }: { rows: ProgressRow[]; onDone: () => void; skip?: boolean }) {
  const [done, setDone] = useState(0);
  useEffect(() => {
    if (skip || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDone(rows.length);
      return;
    }
    const step = Math.min(600, 3600 / Math.max(1, rows.length));
    const timers = rows.map((_, i) => window.setTimeout(() => setDone(i + 1), step * (i + 1)));
    return () => timers.forEach(clearTimeout);
  }, [rows, skip]);
  useEffect(() => {
    if (done >= rows.length && rows.length > 0) {
      const t = window.setTimeout(onDone, 500);
      return () => clearTimeout(t);
    }
  }, [done, rows.length, onDone]);
  return (
    <ul className="space-y-3.5" aria-live="polite">
      {rows.map((r, i) => {
        const ticked = i < done;
        return (
          <li key={r.text} className={cx("flex items-center gap-3 transition-colors", ticked ? "text-ink" : "text-ink-3")}>
            <span className={cx("flex size-7 items-center justify-center rounded-full transition-colors", ticked ? "bg-ok text-ok-fg" : "bg-muted")}>
              {ticked ? <Check className="size-4" aria-hidden /> : r.icon}
            </span>
            {r.text}
          </li>
        );
      })}
    </ul>
  );
}

export function CompareRow({ label, asked, proposed, note }: { label: string; asked: string; proposed: string; note?: string }) {
  return (
    <div>
      <p className="mb-1.5 text-[12px] text-ink-3">{label}</p>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="rounded-[12px] bg-muted p-2.5">
          <p className="text-[11px] text-ink-3">You asked</p>
          <p className="font-medium">{asked}</p>
        </div>
        <ArrowRight className="size-4 text-ink-3" aria-hidden />
        <div className="rounded-[12px] bg-attn p-2.5 text-attn-fg">
          <p className="text-[11px]">Proposed</p>
          <p className="font-medium">{proposed}</p>
        </div>
      </div>
      {note && <p className="mt-1 text-[12px] text-ink-3">{note}</p>}
    </div>
  );
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/** Time left to a deadline, on the gateway's clock; the gateway decides expiry. */
export function Countdown({ deadline }: { deadline: string }) {
  const now = useNow() + useGatewayOffset();
  const left = new Date(deadline).getTime() - now;
  if (left <= 0) return <span>Expired</span>;
  return (
    <span className="tabular">
      {duration(left)} left · until {time(deadline)}
    </span>
  );
}

export function PhoneFrame({ children, caption }: { children: ReactNode; caption: string }) {
  return (
    <figure className="flex flex-col items-center">
      <div className="w-[340px] rounded-[40px] border border-line-strong bg-surface p-3 shadow-sm">
        <div className="mx-auto mb-2 h-1.5 w-20 rounded-full bg-line-strong" aria-hidden />
        <div className="h-[640px] overflow-y-auto rounded-[28px] bg-bg">{children}</div>
      </div>
      <figcaption className="mt-2 text-[12px] text-ink-3">{caption}</figcaption>
    </figure>
  );
}
