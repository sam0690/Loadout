"use client";

import { cn } from "./cn";

/**
 * The signature control. A stepper, not a text field: no keyboard, no focus, no
 * precision required.
 *
 * Typing a number with wet hands between sets is the single thing most likely to stop
 * someone logging at all, so the logging path contains no free-text input anywhere.
 *
 * ponytail: tap-per-increment, no hold-to-repeat. Fine while every value opens on the
 * prescribed number and moves by one or two taps; add press-and-hold the day someone
 * has to walk a load from 0 to 100.
 */
interface Props {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min: number;
  max: number;
  step?: number;
  /** Rendered small, after the value. "kg", "reps". */
  suffix?: string;
  /** Sits under the label — what the plan asked for, so a deviation is visible. */
  hint?: string;
}

export function Stepper({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  hint,
}: Props) {
  const clamp = (n: number) => Math.min(max, Math.max(min, Number(n.toFixed(2))));
  return (
    <div className="no-select flex items-center gap-3">
      <Nudge
        label={`${label} down`}
        onClick={() => onChange(clamp(value - step))}
        disabled={value <= min}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
          <path d="M4 10h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </Nudge>

      <div className="flex-1 text-center">
        <div className="flex items-baseline justify-center gap-1">
          <span className="font-display text-display font-extrabold text-ink">
            {value}
          </span>
          {suffix && <span className="text-sm text-ink-faint">{suffix}</span>}
        </div>
        <div className="label mt-1.5">
          {label}
        </div>
        {hint && <div className="mt-0.5 text-2xs text-ink-faint/70">{hint}</div>}
      </div>

      <Nudge
        label={`${label} up`}
        onClick={() => onChange(clamp(value + step))}
        disabled={value >= max}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
          <path
            d="M10 4v12M4 10h12"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      </Nudge>
    </div>
  );
}

function Nudge({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-20 shrink-0 items-center justify-center rounded-control bg-raised text-ink",
        "transition-colors duration-150 ease-out-soft",
        "hover:bg-line active:bg-line disabled:opacity-25 disabled:pointer-events-none",
      )}
    >
      {children}
    </button>
  );
}
