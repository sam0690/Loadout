"use client";

import type { ContextOut, PlanPayload } from "@/lib/api/client";
import type { Outcome } from "@/lib/queue";
import type { Load } from "@/lib/usePlan";
import { displayLoad, readUnits } from "@/lib/units";
import { fromDay } from "@/lib/day";
import { Button } from "./ui/Button";
import { RowLink } from "./ui/Row";
import { EmptyState } from "./ui/EmptyState";
import { RowSkeleton } from "./ui/Skeleton";
import { CheckIcon, PlanIcon } from "./ui/icons";
import { cn } from "./ui/cn";
import { Thumb } from "./ExerciseMedia";

export type PlanSession = PlanPayload["sessions"][number];
export type PlanItem = PlanSession["items"][number];

export const exerciseName = (item: { slug: string }) => item.slug.replaceAll("_", " ");

export function formatDay(day: string, options: Intl.DateTimeFormatOptions): string {
  return fromDay(day)?.toLocaleDateString(undefined, options) ?? day;
}

/** Sets logged against a session, each exercise capped at what was prescribed. */
export function progress(session: PlanSession, done: ReadonlyMap<string, number>) {
  const logged = session.items.reduce(
    (n, item) => n + Math.min(done.get(item.exercise_id) ?? 0, item.sets),
    0,
  );
  const total = session.items.reduce((n, item) => n + item.sets, 0);
  return { logged, total, complete: logged >= total && total > 0 };
}

/** The non-plan states both Today and Week render identically. */
export function PlanStates({
  load,
  canGenerate,
  generating,
  onGenerate,
}: {
  load: Load;
  canGenerate: boolean;
  generating: boolean;
  onGenerate: () => void;
}) {
  if (load.kind === "loading") {
    return (
      <div className="space-y-8">
        <RowSkeleton count={3} />
        <RowSkeleton count={2} />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <EmptyState
        title="Could not load your plan"
        body={load.message}
        action={<Button onClick={() => location.reload()}>Try again</Button>}
      />
    );
  }
  if (load.kind === "empty") {
    return (
      <EmptyState
        icon={<PlanIcon />}
        title="No plan yet"
        body="Loadout builds a week of sessions around the equipment you can actually reach, then adjusts it as you log."
        action={
          <Button variant="primary" loading={generating} disabled={!canGenerate} onClick={onGenerate}>
            {canGenerate ? "Build my first week" : "Set up your equipment first"}
          </Button>
        }
      />
    );
  }
  return null;
}

/** One exercise row, linking into the logger, with its logged count. */
export function ItemRow({ item, count }: { item: PlanItem; count: number }) {
  const load = displayLoad(item.load, readUnits());
  return (
    <RowLink
      href={`/workout?exercise=${item.exercise_id}`}
      leading={<Thumb slug={item.slug} />}
      title={<span className="capitalize">{exerciseName(item)}</span>}
      detail={
        <>
          {item.sets}×{item.target_reps} · RIR {item.target_rir}
          {load ? ` · ${load}` : ""}
        </>
      }
      trailing={
        count > 0 ? (
          <span className={cn("flex items-center gap-1", count >= item.sets && "text-accent")}>
            {count >= item.sets && <CheckIcon className="size-4" />}
            {count}/{item.sets}
          </span>
        ) : undefined
      }
    />
  );
}

export function SessionCard({
  session,
  today,
  done,
}: {
  session: PlanSession;
  today: string;
  done: ReadonlyMap<string, number>;
}) {
  const isToday = session.day === today;
  const isPast = session.day < today;
  const { logged, total, complete } = progress(session, done);

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className={cn("label", isToday && "text-accent")}>
          {isToday ? "Today" : formatDay(session.day, { weekday: "long" })}
          <span className="ml-2 font-normal tracking-normal normal-case text-ink-faint">
            {formatDay(session.day, { day: "numeric", month: "short" })}
          </span>
        </h2>
        <span className="flex items-center gap-1.5 text-2xs text-ink-faint">
          {complete && <CheckIcon className="size-3.5 text-accent" />}
          {logged}/{total} sets
        </span>
      </div>

      <div className={cn("space-y-2", isPast && !complete && "opacity-55")}>
        {session.items.map((item) => (
          <ItemRow
            key={item.exercise_id}
            item={item}
            count={Math.min(done.get(item.exercise_id) ?? 0, item.sets)}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * Closing out the day.
 *
 * These are the only two events in the vocabulary that were defined, accepted by the
 * server and never once emitted. The fatigue gate reads an abandoned session and caps
 * the next day at the sets that were actually managed, so "I got two exercises in and
 * the gym shut" is real information the engine has been going without.
 *
 * Explicit rather than inferred: guessing that a quiet evening means an abandoned
 * workout would put invented evidence into an append-only log.
 */
export function CloseOut({
  logged,
  total,
  outcome,
  onClose,
}: {
  logged: number;
  total: number;
  outcome: Outcome | null;
  onClose: (next: Outcome, setsCompleted: number) => void;
}) {
  if (outcome !== null) {
    return (
      <p className="mt-3 flex items-center gap-1.5 text-[0.875rem] text-ink-faint">
        {outcome === "completed" ? (
          <>
            <CheckIcon className="size-4 text-accent" />
            Session logged
          </>
        ) : (
          "Session ended early"
        )}
      </p>
    );
  }

  if (logged === 0) return null;

  return (
    <div className="mt-3 flex gap-2">
      {/* Volt only once every set is in: mid-session the next exercise is the action,
          and two loud buttons on one screen means neither is. */}
      <Button
        variant={logged >= total ? "primary" : "secondary"}
        compact
        full
        onClick={() => onClose("completed", logged)}
      >
        Finish session
      </Button>
      {logged < total && (
        <Button
          variant="ghost"
          compact
          className="whitespace-nowrap"
          onClick={() => onClose("abandoned", logged)}
        >
          End early
        </Button>
      )}
    </div>
  );
}

/** One tap between places, per D28. Hidden entirely when there is only one. */
export function ContextSwitcher({
  contexts,
  active,
  disabled,
  onSwitch,
  className,
}: {
  contexts: ContextOut[];
  active: ContextOut | null;
  disabled: boolean;
  onSwitch: (context: ContextOut) => void;
  className?: string;
}) {
  if (contexts.length < 2 || active === null) return null;
  return (
    <div
      role="radiogroup"
      aria-label="Training context"
      className={cn("flex gap-1.5 overflow-x-auto pb-1", className)}
    >
      {contexts.map((context) => (
        <button
          key={context.id}
          type="button"
          role="radio"
          aria-checked={context.id === active.id}
          disabled={disabled}
          onClick={() => onSwitch(context)}
          style={{ minHeight: "var(--tap-sm)" }}
          className={cn(
            "shrink-0 rounded-full px-3.5 text-[0.875rem] transition-colors duration-150 ease-out-soft",
            "disabled:opacity-40",
            context.id === active.id
              ? "bg-accent text-accent-ink font-medium"
              : "bg-surface text-ink-muted hover:bg-raised hover:text-ink",
          )}
        >
          {context.label}
        </button>
      ))}
    </div>
  );
}
