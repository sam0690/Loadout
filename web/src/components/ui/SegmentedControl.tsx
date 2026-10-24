"use client";

import { cn } from "./cn";

/**
 * A small closed set, all options visible. Goal, experience, units, days per week.
 *
 * A select would be one tap shorter and show one option at a time; on the intake
 * screens the whole point is that the user can see what they are choosing between
 * without committing to anything first.
 */
interface Option<T extends string> {
  value: T;
  label: string;
  /** Second line — what this choice actually means for the plan. */
  detail?: string;
}

interface Props<T extends string> {
  label: string;
  value: T | null;
  options: readonly Option<T>[];
  onChange: (next: T) => void;
  /** Stack full-width instead of sitting side by side. For options that need a detail line. */
  stacked?: boolean;
}

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  stacked = false,
}: Props<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        "no-select gap-1.5",
        stacked ? "flex flex-col" : "grid auto-cols-fr grid-flow-col rounded-control bg-surface p-1",
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            style={{ minHeight: stacked ? "var(--tap)" : "var(--tap-sm)" }}
            className={cn(
              "rounded-control px-3 transition-colors duration-150 ease-out-soft",
              stacked ? "px-4 py-3 text-left" : "text-center text-[0.9375rem]",
              active
                ? "bg-accent text-accent-ink"
                : stacked
                  ? "bg-surface text-ink hover:bg-raised"
                  : "text-ink-muted hover:text-ink",
            )}
          >
            <span className={cn("block", stacked && "text-[0.9375rem]", active && "font-medium")}>
              {option.label}
            </span>
            {option.detail && (
              <span
                className={cn(
                  "mt-0.5 block text-[0.8125rem]",
                  active ? "text-accent-ink/70" : "text-ink-faint",
                )}
              >
                {option.detail}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
