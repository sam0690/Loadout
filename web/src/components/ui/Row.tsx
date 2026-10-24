import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "./cn";

/**
 * The tappable list row: plan items, substitutes, archetypes, contexts, history days.
 *
 * A list, not a grid of cards. Same-size cards of heading-plus-text are the lazy
 * container, and everything this app lists is genuinely a sequence of like things
 * where the eye should run down one edge rather than hunt across a grid.
 */
interface Common {
  title: ReactNode;
  /** Sits under the title. Equipment, set counts, whatever qualifies the row. */
  detail?: ReactNode;
  /** Sits at the trailing edge. Usually a prescription or a count. */
  trailing?: ReactNode;
  selected?: boolean;
  className?: string;
}

function body({ title, detail, trailing, selected }: Common) {
  return (
    <>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.9375rem] font-medium text-ink">{title}</span>
        {detail !== undefined && (
          <span
            className={cn(
              "mt-0.5 block truncate text-[0.8125rem]",
              selected ? "text-accent-ink/70" : "text-ink-faint",
            )}
          >
            {detail}
          </span>
        )}
      </span>
      {trailing !== undefined && (
        <span
          className={cn(
            "shrink-0 font-display text-[1.125rem] font-semibold",
            selected ? "text-accent-ink/80" : "text-ink-faint",
          )}
        >
          {trailing}
        </span>
      )}
    </>
  );
}

const SHELL =
  "flex w-full items-center gap-4 rounded-card px-4 py-3.5 text-left transition-colors duration-150 ease-out-soft";

export function RowLink({ href, ...props }: Common & { href: string }) {
  return (
    <Link
      href={href}
      className={cn(
        SHELL,
        "bg-surface hover:bg-raised active:bg-raised",
        props.className,
      )}
      style={{ minHeight: "var(--tap)" }}
    >
      {body(props)}
    </Link>
  );
}

export function RowButton({
  onClick,
  disabled,
  ...props
}: Common & { onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={props.selected}
      className={cn(
        SHELL,
        "no-select disabled:pointer-events-none disabled:opacity-40",
        props.selected
          ? "bg-accent text-accent-ink"
          : "bg-surface hover:bg-raised active:bg-raised",
        props.className,
      )}
    >
      {body(props)}
    </button>
  );
}

/** The same shape, but inert — for rows that display rather than navigate. */
export function Row(props: Common) {
  return (
    <div className={cn(SHELL, "bg-surface", props.className)}>{body(props)}</div>
  );
}
