"use client";

import { useEffect, useRef } from "react";
import { cn } from "./cn";

/**
 * The signature control. A stepper, not a text field: no keyboard, no focus, no
 * precision required.
 *
 * Typing a number with wet hands between sets is the single thing most likely to stop
 * someone logging at all, so the logging path contains no free-text input anywhere.
 *
 * Press and hold repeats, speeding up: a first session opens the load at 0 (the engine
 * does not guess a first weight), and walking that to 60 kg one tap at a time is 24 taps.
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
  const timer = useRef<number | undefined>(undefined);
  // The latest handler, so each repeat steps from the value the last one produced.
  const step = useRef(onClick);
  step.current = onClick;
  const stop = () => window.clearTimeout(timer.current);

  // A disabled button gets no pointerup, so hitting min or max has to end the hold here.
  useEffect(() => {
    if (disabled) stop();
  }, [disabled]);
  useEffect(() => stop, []);

  function hold() {
    step.current();
    let delay = 400; // one deliberate step first, so a tap never overshoots
    const loop = () => {
      timer.current = window.setTimeout(() => {
        step.current();
        delay = Math.max(60, delay * 0.75);
        loop();
      }, delay);
    };
    loop();
  }

  return (
    <button
      type="button"
      aria-label={label}
      onPointerDown={(e) => e.button === 0 && hold()}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      // Keyboard activation arrives as a click with no pointer (detail 0); pointer clicks
      // were already stepped on pointerdown.
      onClick={(e) => e.detail === 0 && onClick()}
      onContextMenu={(e) => e.preventDefault()}
      disabled={disabled}
      className={cn(
        "flex w-20 shrink-0 touch-none items-center justify-center rounded-control bg-raised text-ink",
        "transition-colors duration-150 ease-out-soft",
        "hover:bg-line active:bg-line disabled:opacity-25 disabled:pointer-events-none",
      )}
    >
      {children}
    </button>
  );
}
