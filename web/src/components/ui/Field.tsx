"use client";

import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";

/**
 * Label, input, hint and error, wired together.
 *
 * The wiring is the point: an error rendered as a loose paragraph beside an input is
 * invisible to a screen reader, which is what the app did everywhere before this.
 */
interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  /** Rendered inside the field's trailing edge — "kg", "cm", "years". */
  unit?: string;
}

export function Field({ label, hint, error, unit, className, ...rest }: Props) {
  const id = useId();
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[0.8125rem] text-ink-muted">
        {label}
      </label>

      <div className="relative">
        <input
          {...rest}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          className={cn(
            "w-full rounded-control bg-surface px-4 text-[1.0625rem] text-ink",
            "border transition-colors duration-150 ease-out-soft",
            "placeholder:text-ink-faint/60",
            unit && "pr-14",
            error
              ? "border-danger"
              : "border-line hover:border-line-strong focus:border-accent",
            className,
          )}
          style={{ minHeight: "var(--tap)" }}
        />
        {unit && (
          <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-sm text-ink-faint">
            {unit}
          </span>
        )}
      </div>

      {hint && !error && (
        <p id={`${id}-hint`} className="text-2xs text-ink-faint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-2xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
