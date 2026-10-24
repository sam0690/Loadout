import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";

/**
 * Every button in the app. Previously each of the fourteen call sites re-declared its
 * own colours and radius, which is why no two of them agreed.
 *
 * `loading` is separate from `disabled` on purpose: a request in flight and a control
 * that cannot be used are different things and read differently, but both must refuse
 * a second click. The plan screen shipped a bug for want of exactly this — a double tap
 * enqueued two generation jobs.
 */
type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-ink font-display text-[1.125rem] font-extrabold uppercase tracking-[0.06em] hover:bg-accent-hover active:bg-accent-hover",
  secondary:
    "bg-raised text-ink border border-line hover:border-line-strong active:bg-line",
  ghost: "text-ink-muted hover:text-ink hover:bg-surface active:bg-raised",
  danger:
    "bg-danger-quiet text-danger border border-danger/30 hover:border-danger/60 active:bg-danger/20",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  /** Half-height, for controls that sit beside content rather than under it. */
  compact?: boolean;
  full?: boolean;
  children: ReactNode;
}

export function Button({
  variant = "secondary",
  loading = false,
  compact = false,
  full = false,
  className,
  disabled,
  children,
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      style={compact ? { minHeight: "var(--tap-sm)" } : undefined}
      className={cn(
        "no-select relative inline-flex items-center justify-center gap-2 rounded-control px-4",
        "text-[0.9375rem] transition-[color,background-color,border-color,transform] active:scale-[0.98] duration-150 ease-out-soft",
        "disabled:pointer-events-none disabled:opacity-40",
        full && "w-full",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Spinner />}
      <span className={cn(loading && "opacity-70")}>{children}</span>
    </button>
  );
}

function Spinner() {
  return (
    <svg
      className="size-4 animate-spin"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path
        d="M14.5 8A6.5 6.5 0 0 0 8 1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
