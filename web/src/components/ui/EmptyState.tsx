import type { ReactNode } from "react";

/**
 * An empty state that teaches the interface rather than announcing a void.
 *
 * Every one of these says what the screen will hold and how to put something in it.
 * "Nothing logged yet." — which is what History said — tells the user nothing they
 * could not already see.
 */
export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon && (
        <div className="mb-4 flex size-11 items-center justify-center rounded-full bg-surface text-ink-faint">
          {icon}
        </div>
      )}
      <h2 className="text-[1.0625rem] font-medium text-ink">{title}</h2>
      <p className="mt-1.5 max-w-[34ch] text-[0.9375rem] leading-relaxed text-ink-faint">
        {body}
      </p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
