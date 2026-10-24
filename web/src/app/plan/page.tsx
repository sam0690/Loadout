"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  type ContextOut,
  type PlanPayload,
  type Profile,
} from "@/lib/api/client";
import { cachePlan, cachedPlan, generatePlan, type Preferences } from "@/lib/plan";
import { resolveContext, setActiveContextId } from "@/lib/context";
import { closeSession, loggedSets, sessionOutcome, type Outcome } from "@/lib/queue";
import { readUnits, displayLoad } from "@/lib/units";
import { bmiFromProfile } from "@/lib/bmi";
import { cachedProfile, refreshProfile } from "@/lib/profile";
import { BodyMetrics } from "@/components/BodyMetrics";
import { Analysis } from "@/components/Analysis";
import { Coverage } from "@/components/Coverage";
import { analyse, type Analysis as AnalysisData } from "@/lib/analysis";
import { fromDay, localDay } from "@/lib/day";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { RowLink } from "@/components/ui/Row";
import { EmptyState } from "@/components/ui/EmptyState";
import { RowSkeleton } from "@/components/ui/Skeleton";
import { CheckIcon, OfflineIcon, PlanIcon } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/components/ui/cn";

/**
 * This week's sessions, today first.
 *
 * Four states that used to share one string variable — loading, empty, error and
 * offline — are four states here, because "No plan yet." rendering above a cached plan
 * is the kind of thing one overloaded `status` produces.
 */
type Load =
  | { kind: "loading" }
  | { kind: "ready"; payload: PlanPayload; weekOf: string | null }
  | { kind: "offline"; payload: PlanPayload }
  | { kind: "empty" }
  | { kind: "error"; message: string };

/** Shared empty map, so a session with no logging does not remount its rows. */
const EMPTY: ReadonlyMap<string, number> = new Map();

const DEFAULTS: Preferences = {
  goal: "hypertrophy",
  experience: "intermediate",
  daysPerWeek: 3,
  sessionMinutes: 60,
};

export default function PlanView() {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [contexts, setContexts] = useState<ContextOut[]>([]);
  const [active, setActive] = useState<ContextOut | null>(null);
  // Keyed by plan day, then exercise. A session card must show the sets logged on
  // *its* day -- crediting today's work to every session that lists the same exercise
  // made a past Monday read as done because you trained this morning.
  const [done, setDone] = useState<Map<string, Map<string, number>>>(new Map());
  const [generating, setGenerating] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Cache first so the figure survives a cold start with no network, then refresh.
  const [profile, setProfile] = useState<Profile | null>(cachedProfile);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const toast = useToast();

  const today = localDay();

  // Whatever this device already had, so a dead network shows the last plan rather than
  // an empty screen. With no cache the two failures are genuinely different: a 404 means
  // no plan has ever been generated, anything else means we could not ask.
  const fallBack = useCallback((reason: "missing" | "unreachable") => {
    const cached = cachedPlan();
    if (cached) return setLoad({ kind: "offline", payload: cached });
    setLoad(
      reason === "missing"
        ? { kind: "empty" }
        : { kind: "error", message: "Loadout could not be reached from this device." },
    );
  }, []);

  const refreshDay = useCallback(async () => {
    const byDay = new Map<string, Map<string, number>>();
    for (const set of await loggedSets()) {
      const day = byDay.get(set.day) ?? new Map<string, number>();
      day.set(set.exerciseId, (day.get(set.exerciseId) ?? 0) + 1);
      byDay.set(set.day, day);
    }
    setDone(byDay);
    setOutcome(await sessionOutcome(today));
  }, [today]);

  useEffect(() => {
    void refreshDay();
  }, [refreshDay]);

  async function close(day: string, next: Outcome, sets: number) {
    try {
      await closeSession(day, next, sets);
      await refreshDay();
      toast(next === "completed" ? "Session logged" : "Session ended early");
    } catch {
      toast("Could not record that on this device.", "error");
    }
  }

  useEffect(() => {
    void api
      .currentPlan()
      .then((plan) => {
        const payload = plan.payload as PlanPayload;
        cachePlan(payload);
        setLoad({ kind: "ready", payload, weekOf: plan.week_of || null });
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) fallBack("missing");
        else fallBack("unreachable");
      });
  }, [fallBack]);

  useEffect(() => {
    void refreshProfile().then(setProfile);
  }, []);

  // Counting only, and all of it local: the panel has to render offline like the rest
  // of this screen. `done` is in the dependency list so logging a set moves the bars.
  useEffect(() => {
    const plan =
      load.kind === "ready" || load.kind === "offline" ? load.payload : null;
    if (plan === null) return;
    void loggedSets().then((sets) => setAnalysis(analyse(sets, plan, today)));
  }, [load, done, today]);

  useEffect(() => {
    void api
      .listContexts()
      .then(async (all) => {
        setContexts(all);
        setActive(await resolveContext());
      })
      .catch(() => setContexts([]));
  }, []);

  async function regenerate(context: ContextOut) {
    if (generating) return; // A double tap used to enqueue two generation jobs.
    setGenerating(true);
    setError(null);
    try {
      const prefs = (await refreshProfile()) ?? profile;
      setProfile(prefs);
      const plan = await generatePlan(context.id, {
        goal: prefs?.goal ?? DEFAULTS.goal,
        experience: prefs?.experience ?? DEFAULTS.experience,
        daysPerWeek: prefs?.days_per_week ?? DEFAULTS.daysPerWeek,
        sessionMinutes: prefs?.session_minutes ?? DEFAULTS.sessionMinutes,
      });
      setLoad({
        kind: "ready",
        payload: plan.payload as PlanPayload,
        weekOf: plan.week_of || null,
      });
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : "Could not build a plan. Try again in a moment.",
      );
    } finally {
      setGenerating(false);
    }
  }

  function switchTo(context: ContextOut) {
    setActive(context);
    setActiveContextId(context.id);
    void regenerate(context);
  }

  const payload =
    load.kind === "ready" || load.kind === "offline" ? load.payload : null;
  const measurements = profile ? bmiFromProfile(profile) : null;

  return (
    <AppShell width="max-w-3xl">
      <PageHeader
        title="This week"
        meta={
          load.kind === "offline" ? (
            <span className="inline-flex items-center gap-1.5 text-ink-faint">
              <OfflineIcon className="size-3.5" />
              Showing what is on this device
            </span>
          ) : load.kind === "ready" && load.weekOf ? (
            `From ${formatDay(load.weekOf, { day: "numeric", month: "long" })}`
          ) : undefined
        }
        action={
          payload ? (
            <Button
              compact
              loading={generating}
              onClick={() => active && regenerate(active)}
              disabled={!active}
            >
              Regenerate
            </Button>
          ) : undefined
        }
      />

      {contexts.length > 1 && active && (
        <ContextSwitcher
          contexts={contexts}
          active={active}
          disabled={generating}
          onSwitch={switchTo}
        />
      )}

      {payload?.unreachable && payload.unreachable.length > 0 && (
        <Coverage unreachable={payload.unreachable} className="mb-6" />
      )}

      {measurements && (
        <BodyMetrics
          bmi={measurements}
          bodyweightKg={profile?.bodyweight_kg == null ? null : Number(profile.bodyweight_kg)}
          units={readUnits()}
          className="mb-6"
        />
      )}

      {error && (
        <p role="alert" className="mb-6 text-[0.875rem] text-danger">
          {error}
        </p>
      )}

      {load.kind === "loading" && (
        <div className="space-y-8">
          <RowSkeleton count={3} />
          <RowSkeleton count={2} />
        </div>
      )}

      {load.kind === "error" && (
        <EmptyState
          title="Could not load your plan"
          body={load.message}
          action={<Button onClick={() => location.reload()}>Try again</Button>}
        />
      )}

      {load.kind === "empty" && (
        <EmptyState
          icon={<PlanIcon />}
          title="No plan yet"
          body="Loadout builds a week of sessions around the equipment you can actually reach, then adjusts it as you log."
          action={
            <Button
              variant="primary"
              loading={generating}
              disabled={!active}
              onClick={() => active && regenerate(active)}
            >
              {active ? "Build my first week" : "Set up your equipment first"}
            </Button>
          }
        />
      )}

      {payload && (
        <div className="space-y-8 md:grid md:grid-cols-2 md:gap-6 md:space-y-0">
          {payload.sessions.map((session) => (
            <SessionCard
              key={session.day}
              session={session}
              today={today}
              done={done.get(session.day) ?? EMPTY}
              outcome={session.day === today ? outcome : null}
              onClose={
                session.day === today
                  ? (next, sets) => void close(session.day, next, sets)
                  : undefined
              }
            />
          ))}
        </div>
      )}

      {analysis && <Analysis data={analysis} units={readUnits()} className="mt-10" />}
    </AppShell>
  );
}

function SessionCard({
  session,
  today,
  done,
  outcome,
  onClose,
}: {
  session: PlanPayload["sessions"][number];
  today: string;
  done: ReadonlyMap<string, number>;
  outcome: Outcome | null;
  onClose?: (next: Outcome, setsCompleted: number) => void;
}) {
  const units = readUnits();
  const isToday = session.day === today;
  const isPast = session.day < today;
  const logged = session.items.reduce(
    (n, item) => n + Math.min(done.get(item.exercise_id) ?? 0, item.sets),
    0,
  );
  const total = session.items.reduce((n, item) => n + item.sets, 0);
  const complete = logged >= total && total > 0;

  return (
    <section className={cn("space-y-2", isToday && "md:col-span-2")}>
      <div className="flex items-baseline justify-between gap-3">
        <h2
          className={cn(
            "text-[0.8125rem] tracking-[0.08em] uppercase",
            isToday ? "text-accent" : "text-ink-faint",
          )}
        >
          {isToday ? "Today" : formatDay(session.day, { weekday: "long" })}
          <span className="ml-2 tracking-normal normal-case text-ink-faint">
            {formatDay(session.day, { day: "numeric", month: "short" })}
          </span>
        </h2>
        <span className="flex items-center gap-1.5 text-2xs text-ink-faint">
          {complete && <CheckIcon className="size-3.5 text-accent" />}
          {logged}/{total} sets
        </span>
      </div>

      <div className={cn("space-y-2", isPast && !complete && "opacity-55")}>
        {session.items.map((item) => {
          const count = Math.min(done.get(item.exercise_id) ?? 0, item.sets);
          const load = displayLoad(item.load, units);
          return (
            <RowLink
              key={item.exercise_id}
              href={`/log/${item.exercise_id}`}
              title={<span className="capitalize">{item.slug.replaceAll("_", " ")}</span>}
              detail={
                <>
                  {item.sets}×{item.target_reps} · RIR {item.target_rir}
                  {load ? ` · ${load}` : ""}
                </>
              }
              trailing={
                count > 0 ? (
                  <span
                    className={cn(
                      "flex items-center gap-1",
                      count >= item.sets && "text-accent",
                    )}
                  >
                    {count >= item.sets && <CheckIcon className="size-4" />}
                    {count}/{item.sets}
                  </span>
                ) : undefined
              }
            />
          );
        })}
      </div>

      {onClose && <CloseOut logged={logged} total={total} outcome={outcome} onClose={onClose} />}
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
function CloseOut({
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
      <Button variant="primary" compact full onClick={() => onClose("completed", logged)}>
        Finish session
      </Button>
      {logged < total && (
        <Button variant="ghost" compact onClick={() => onClose("abandoned", logged)}>
          End early
        </Button>
      )}
    </div>
  );
}

/** One tap between places, per D28. Hidden entirely when there is only one. */
function ContextSwitcher({
  contexts,
  active,
  disabled,
  onSwitch,
}: {
  contexts: ContextOut[];
  active: ContextOut;
  disabled: boolean;
  onSwitch: (context: ContextOut) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Training context"
      className="mb-6 flex gap-1.5 overflow-x-auto pb-1"
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
              ? "bg-accent text-accent-ink"
              : "bg-surface text-ink-muted hover:bg-raised hover:text-ink",
          )}
        >
          {context.label}
        </button>
      ))}
    </div>
  );
}


function formatDay(day: string, options: Intl.DateTimeFormatOptions): string {
  return fromDay(day)?.toLocaleDateString(undefined, options) ?? day;
}
