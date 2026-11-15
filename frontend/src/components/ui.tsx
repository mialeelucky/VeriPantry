// Small building blocks shared by every screen (frontend.md §7).

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, CheckCircle2, CircleSlash, Info, Lock, Check, Loader2 } from "lucide-react";
import type { Tone } from "../lib/status";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

type Variant = "primary" | "secondary" | "ghost" | "ok" | "danger";

export function Button({
  variant = "secondary",
  className,
  children,
  busy,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  const styles: Record<Variant, string> = {
    primary: "bg-primary text-on-primary hover:opacity-90",
    secondary: "bg-surface border border-line-strong text-ink hover:bg-muted",
    ghost: "text-ink-2 hover:bg-muted",
    ok: "bg-ok-fg text-surface hover:opacity-90",
    danger: "bg-surface border border-line-strong text-stop-fg hover:bg-stop",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-[12px] px-4 text-[14px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        styles[variant],
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

const toneStyle: Record<Tone, string> = {
  ok: "bg-ok text-ok-fg",
  attention: "bg-attn text-attn-fg",
  stop: "bg-stop text-stop-fg",
  neutral: "bg-muted text-ink-2",
};
const toneIcon: Record<Tone, typeof CheckCircle2> = { ok: CheckCircle2, attention: AlertTriangle, stop: CircleSlash, neutral: Info };

/** Status is never colour only: icon plus words (frontend.md §6.1, §10). */
export function StatusBadge({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  const Icon = toneIcon[tone];
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium leading-4", toneStyle[tone], className)}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {children}
    </span>
  );
}

type PillKind = "must" | "nice" | "unchanged" | "deviation" | "neutral";

export function Pill({ kind, children }: { kind: PillKind; children: ReactNode }) {
  const styles: Record<PillKind, string> = {
    must: "bg-stop text-stop-fg",
    nice: "border border-line-strong text-ink",
    unchanged: "border border-line text-ink",
    deviation: "bg-attn text-attn-fg",
    neutral: "bg-muted text-ink-2",
  };
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] leading-4", styles[kind])}>
      {kind === "must" && <Lock className="size-3.5" aria-hidden />}
      {kind === "unchanged" && <Check className="size-3.5 text-ok-fg" aria-hidden />}
      {children}
    </span>
  );
}

export function MetricTile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-[12px] bg-muted p-3.5">
      <p className="text-[12px] text-ink-3">{label}</p>
      <p className="tabular mt-1 text-[22px] font-medium leading-7">
        {value} {sub && <span className="text-[13px] font-normal text-ink-2">{sub}</span>}
      </p>
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-[16px] border border-line bg-surface", className)}>{children}</div>;
}

export function Notice({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const Icon = toneIcon[tone];
  return (
    <div role={tone === "stop" ? "alert" : "status"} className={cx("flex gap-2.5 rounded-[12px] px-3.5 py-3", toneStyle[tone])}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="text-[13px] leading-5">
        {title && <p className="font-medium">{title}</p>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-ink-3" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function Mark() {
  return (
    <span className="inline-flex size-7 items-center justify-center rounded-[8px] bg-ok text-ok-fg" aria-hidden>
      <svg viewBox="0 0 24 24" className="size-[17px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 15c0-5 3.5-8.5 10-9.5-.5 6.5-4 10-9 10" />
        <path d="M6 18c1.6-3.3 4-5.7 7.2-7.6" />
      </svg>
    </span>
  );
}
