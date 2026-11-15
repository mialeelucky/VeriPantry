// StepIndicator and StepScreen: one question per screen, one primary action (F1, F3).

import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cx } from "./ui";

export function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex items-center gap-1.5" aria-label="Progress">
      {steps.map((label, i) => {
        const done = i < current;
        const on = i === current;
        return (
          <li key={label} className={cx("flex items-center gap-1.5 text-[12px]", on ? "text-ink" : "text-ink-3")} aria-current={on ? "step" : undefined}>
            <span
              className={cx(
                "flex size-[22px] items-center justify-center rounded-full border text-[11px]",
                on && "border-primary bg-primary text-on-primary",
                done && "border-transparent bg-ok text-ok-fg",
                !on && !done && "border-line-strong",
              )}
            >
              {done ? <Check className="size-3" aria-hidden /> : i + 1}
            </span>
            <span className={cx(on ? "inline" : "hidden sm:inline")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function StepScreen({
  eyebrow,
  title,
  subtitle,
  children,
  primary,
  secondary,
}: {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  primary?: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <section className="vp-step flex flex-col">
      <div className="rounded-[16px] border border-line bg-surface px-6 py-6 sm:px-7">
        {eyebrow && <p className="mb-1 text-[12px] text-ink-3">{eyebrow}</p>}
        <h1 className="text-[22px] font-medium leading-7">{title}</h1>
        {subtitle && <p className="mt-1.5 text-ink-2">{subtitle}</p>}
        <div className="mt-5">{children}</div>
      </div>
      {(primary || secondary) && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <div>{secondary}</div>
          <div>{primary}</div>
        </div>
      )}
    </section>
  );
}
