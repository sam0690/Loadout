"use client";

import { useRouter } from "next/navigation";
import { usePlan } from "@/lib/usePlan";
import type { Outcome } from "@/lib/queue";
import { displayLoad, readUnits } from "@/lib/units";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { RowLink } from "@/components/ui/Row";
import { useToast } from "@/components/ui/Toast";
import { OfflineIcon } from "@/components/ui/icons";
import {
  CloseOut,
  ContextSwitcher,
  ItemRow,
  PlanStates,
  exerciseName,
  formatDay,
  progress,
  type PlanItem,
  type PlanSession,
} from "@/components/Session";

const EMPTY: ReadonlyMap<string, number> = new Map();

/**
 * What to do right now. One session, one obvious next exercise, one button.
 *
 * The week used to open on a list of every session with today's somewhere in it, which
 * made the person standing in the gym do the finding. This screen does it for them.
 */
export default function Today() {
  const plan = usePlan();
  const toast = useToast();
  const { load, payload, today } = plan;

  const session = payload?.sessions.find((s) => s.day === today) ?? null;
  const next = payload?.sessions.find((s) => s.day > today) ?? null;

  async function close(next: Outcome, sets: number) {
    try {
      await plan.close(today, next, sets);
      toast(next === "completed" ? "Session logged" : "Session ended early");
    } catch {
      toast("Could not record that on this device.", "error");
    }
  }

  return (
    <AppShell width="max-w-xl">
      <header className="pt-8 pb-5">
        <p className="label flex items-center gap-2">
          <span className="text-accent">Today</span>
          <span>{formatDay(today, { weekday: "short", day: "numeric", month: "short" })}</span>
          {load.kind === "offline" && (
            <span className="inline-flex items-center gap-1 font-normal normal-case tracking-normal">
              <OfflineIcon className="size-3.5" />
              offline
            </span>
          )}
        </p>
        <h1 className="mt-2 text-display text-ink">
          {payload === null ? "Loadout" : session ? focus(session) : "Rest day"}
        </h1>
      </header>

      <ContextSwitcher
        contexts={plan.contexts}
        active={plan.active}
        disabled={plan.generating}
        onSwitch={plan.switchTo}
        className="mb-6"
      />

      <PlanStates
        load={load}
        canGenerate={plan.active !== null}
        generating={plan.generating}
        onGenerate={() => plan.active && void plan.regenerate(plan.active)}
      />

      {session && (
        <Session
          session={session}
          done={plan.done.get(today) ?? EMPTY}
          outcome={plan.outcome}
          onClose={(n, s) => void close(n, s)}
        />
      )}

      {payload && !session && <RestDay next={next} />}
    </AppShell>
  );
}

/** The day's muscles, as a title: "Chest · Back · Quads". */
function focus(session: PlanSession): string {
  const muscles = [...new Set(session.items.map((i) => i.primary_muscle.replaceAll("_", " ")))];
  return muscles.slice(0, 3).join(" · ");
}

function Session({
  session,
  done,
  outcome,
  onClose,
}: {
  session: PlanSession;
  done: ReadonlyMap<string, number>;
  outcome: Outcome | null;
  onClose: (next: Outcome, sets: number) => void;
}) {
  const { logged, total, complete } = progress(session, done);
  const upNext = session.items.find((i) => (done.get(i.exercise_id) ?? 0) < i.sets) ?? null;
  const pct = total > 0 ? Math.round((logged / total) * 100) : 0;

  return (
    <>
      <div className="mb-6">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="label">Session</span>
          <span className="font-display text-[1.125rem] font-semibold text-ink-muted">
            {logged}/{total} sets
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Sets logged today"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1.5 overflow-hidden rounded-full bg-raised"
        >
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out-soft"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {upNext && outcome === null && (
        <Hero item={upNext} started={logged > 0} />
      )}

      {complete && outcome === null && (
        <p className="mb-6 font-display text-[1.5rem] font-extrabold uppercase text-accent">
          Every set done.
        </p>
      )}

      <CloseOut logged={logged} total={total} outcome={outcome} onClose={onClose} />

      <h2 className="label mt-10 mb-3">All exercises</h2>
      <div className="space-y-2">
        {session.items.map((item) => (
          <ItemRow
            key={item.exercise_id}
            item={item}
            count={Math.min(done.get(item.exercise_id) ?? 0, item.sets)}
          />
        ))}
      </div>
    </>
  );
}

/** The next exercise at scoreboard size, and the one button that starts it. */
function Hero({ item, started }: { item: PlanItem; started: boolean }) {
  const router = useRouter();
  const load = displayLoad(item.load, readUnits());
  const [value, unit] = load ? load.split(" ") : [String(item.target_reps), "reps"];

  return (
    <section className="mb-6 rounded-card border border-line bg-surface p-5">
      <p className="label">{started ? "Up next" : "First up"}</p>
      <h2 className="mt-1 font-display text-[1.75rem] leading-tight font-extrabold uppercase text-ink">
        {exerciseName(item)}
      </h2>
      <p className="mt-4 flex items-baseline gap-2">
        <span className="font-display text-hero font-extrabold text-accent">{value}</span>
        <span className="font-display text-[1.25rem] font-semibold uppercase text-ink-muted">
          {unit}
        </span>
      </p>
      <p className="mt-2 font-display text-[1.25rem] font-semibold tracking-[0.02em] text-ink-muted">
        {item.sets} × {item.target_reps}
        <span className="text-ink-faint"> · RIR {item.target_rir}</span>
      </p>
      <Button
        variant="primary"
        full
        className="mt-5"
        onClick={() => router.push(`/workout?exercise=${item.exercise_id}`)}
      >
        {started ? "Continue workout" : "Start workout"}
      </Button>
    </section>
  );
}

/**
 * A rest day, with a way out of it. Sessions move: a missed Friday gets done on
 * Saturday, a busy Monday gets pulled forward. The sets are logged on the day they
 * happen, which is what the fatigue gate reads, so training early is honest data.
 */
function RestDay({ next }: { next: PlanSession | null }) {
  const router = useRouter();
  return (
    <section>
      <p className="mb-6 text-[0.9375rem] text-ink-muted">
        Nothing scheduled today. Recovery is when the work turns into strength.
      </p>
      {next ? (
        <>
          <RowLink
            href="/week"
            title={`Next: ${formatDay(next.day, { weekday: "long" })}`}
            detail={`${next.items.length} exercises · ${focus(next)}`}
            trailing="Week →"
          />
          <Button
            full
            className="mt-3"
            onClick={() => router.push(`/workout?exercise=${next.items[0]!.exercise_id}`)}
          >
            Do {formatDay(next.day, { weekday: "long" })}&apos;s session now
          </Button>
        </>
      ) : (
        <RowLink href="/week" title="This week is done" detail="Build next week from the Week tab" />
      )}
    </section>
  );
}
