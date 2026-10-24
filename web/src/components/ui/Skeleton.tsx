import { cn } from "./cn";

/**
 * Loading placeholders shaped like the content that replaces them, not a spinner in
 * the middle of an empty screen. The plan and history screens both showed nothing at
 * all while fetching, which is indistinguishable from being broken.
 *
 * The pulse is disabled wholesale by the reduced-motion block in globals.css.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-control bg-surface", className)} />;
}

/** A session's worth of plan rows, at the height RowLink settles to, so nothing jumps. */
export function RowSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-14 rounded-card" />
      ))}
    </div>
  );
}
