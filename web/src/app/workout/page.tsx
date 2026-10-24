"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { PlanPayload } from "@/lib/api/client";
import { cachedPlan } from "@/lib/plan";
import {
  closeSession,
  discard,
  enqueue,
  loggedSets,
  sessionOutcome,
  swapsOn,
  type LoggedSet,
  type Outcome,
} from "@/lib/queue";
import { applySwaps, deltaVsLast, workoutSession, type Item } from "@/lib/workout";
import { displayLoad, readUnits } from "@/lib/units";
import { localDay } from "@/lib/day";
import { Button } from "@/components/ui/Button";
import { Stepper } from "@/components/ui/Stepper";
import { useToast } from "@/components/ui/Toast";
import { SyncBadge } from "@/components/Sync";
import { RestTimer, SetList, SlotBar, SwapList } from "@/components/Workout";
import { UndoIcon } from "@/components/ui/icons";
import { Frames, HowTo } from "@/components/ExerciseMedia";
import { cn } from "@/components/ui/cn";

/**
 * The workout, start to finish, on one screen. Used mid-set, one-handed, possibly sweaty.
 *
 * Replaces a logger that held one exercise at a time and sent the user back to the plan
 * between each. No tab bar competing with the primary control; a thumb-width column at
 * every breakpoint; no modal and no free-text input anywhere in the logging path.
 *
 * Exactly one heading element lives here, deliberately: the e2e specs address this
 * screen through `getByRole("heading")`, and a second one would break them.
 */
const LOAD_STEP = 2.5;

type Session = PlanPayload["sessions"][number];

export default function WorkoutPage() {
  return (
    <Suspense>
      <Workout />
    </Suspense>
  );
}

function Workout() {
  const opened = useSearchParams().get("exercise");
  const router = useRouter();
  const toast = useToast();
  const units = readUnits();
  const today = localDay();

  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [swaps, setSwaps] = useState<Map<string, string>>(new Map());
  const [all, setAll] = useState<LoggedSet[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [index, setIndex] = useState(0);
  const [reps, setReps] = useState(10);
  const [rir, setRir] = useState(2);
  const [load, setLoad] = useState<number | null>(null);
  const [swapping, setSwapping] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    const [sets, sw] = await Promise.all([loggedSets(), swapsOn(today)]);
    setAll(sets);
    setSwaps(sw);
    return { sets, sw };
  }, [today]);

  const items = useMemo(() => (session ? applySwaps(session.items, swaps) : []), [session, swaps]);
  const setsToday = useCallback(
    // loggedSets is newest-first; a set list reads oldest-first.
    (id: string) => all.filter((s) => s.exerciseId === id && s.day === today).reverse(),
    [all, today],
  );
  const doneCount = useCallback((id: string) => setsToday(id).length, [setsToday]);

  // Mount only: the URL names where to start, after that the screen owns the position.
  useEffect(() => {
    void (async () => {
      const { sets, sw } = await refresh();
      setOutcome(await sessionOutcome(today));
      const plan = cachedPlan();
      const found = plan ? workoutSession(plan, today, opened, sw) : null;
      setSession(found);
      if (!found) return;
      const slots = applySwaps(found.items, sw);
      const count = (id: string) => sets.filter((s) => s.exerciseId === id && s.day === today).length;
      const at = opened
        ? slots.findIndex((i) => i.exercise_id === opened)
        : slots.findIndex((i) => count(i.exercise_id) < i.sets);
      setIndex(Math.max(0, at));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current: Item | undefined = items[index];
  const done = current ? setsToday(current.exercise_id) : [];

  // Steppers open on the last set logged today, else on the prescription.
  useEffect(() => {
    if (!current) return;
    const last = setsToday(current.exercise_id).at(-1);
    setReps(last?.reps ?? current.target_reps);
    setRir(last?.rir ?? current.target_rir);
    const start = last?.load ?? current.load;
    // Nothing to start from on a first session: 0, and the user walks it up. A default
    // weight here would be the client prescribing a load, which only the engine does.
    setLoad(start !== null ? Number(start) : current.loadable ? 0 : null);
    setSwapping(false);
    window.history.replaceState(null, "", `/workout?exercise=${current.exercise_id}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.exercise_id]);

  /**
   * The occupied-machine flow (PRD §6). Everything needed is already on the device, so
   * no request is made. Recorded as "unavailable_now", which is a different signal from
   * disliking an exercise and must not be conflated with one.
   */
  async function swapTo(substitute: Item["substitutes"][number]) {
    if (!current) return;
    try {
      await enqueue("exercise_swapped", {
        from_exercise_id: current.exercise_id,
        to_exercise_id: substitute.exercise_id,
        reason: "unavailable_now",
      });
      await refresh();
    } catch {
      toast("Could not record the swap on this device.", "error");
    }
  }

  async function logSet() {
    if (!current || saving) return;
    setSaving(true);
    try {
      await enqueue("set_logged", {
        exercise_id: current.exercise_id,
        // Carried so history can render itself with no catalog and no network.
        slug: current.slug,
        reps,
        rir,
        // 0 on a loadable exercise means the weight was never entered, not lifted at 0.
        load: load === null || load === 0 ? null : String(load),
        target_bottom: current.target_reps,
        target_top: current.target_reps,
      });
      await refresh();
    } catch {
      // The write is the product. A set that failed to reach IndexedDB must never look
      // like a set that was saved.
      toast("That set was not saved. Check your storage and try again.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function undoLast() {
    const last = done.at(-1);
    if (!last) return;
    try {
      await discard(last.id);
      await refresh();
      toast("Set removed");
    } catch {
      toast("That set has already synced and cannot be undone here.", "error");
    }
  }

  const logged = items.reduce((n, i) => n + Math.min(doneCount(i.exercise_id), i.sets), 0);
  const total = items.reduce((n, i) => n + i.sets, 0);

  async function finish(next: Outcome) {
    try {
      if (outcome === null && logged > 0) await closeSession(today, next, logged);
      router.push(logged > 0 ? `/summary?day=${today}` : "/today");
    } catch {
      toast("Could not record that on this device.", "error");
    }
  }

  if (session === undefined) {
    return (
      <main className="mx-auto min-h-dvh max-w-md px-5 pt-16">
        <div className="h-10 w-2/3 animate-pulse rounded-control bg-surface" />
      </main>
    );
  }

  if (session === null || !current) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <h1 className="text-[1.75rem] text-ink">No workout on this device</h1>
        <p className="text-[0.9375rem] text-ink-faint">
          Open your plan while online once, and the whole week — including the swaps — will
          be here next time.
        </p>
        <Button variant="primary" onClick={() => router.push("/today")}>
          Back to today
        </Button>
      </main>
    );
  }

  const prescribed = displayLoad(current.load, units);
  const [value, unit] = prescribed ? prescribed.split(" ") : [String(current.target_reps), "reps"];
  const delta = deltaVsLast(current, all, today, units);
  const exerciseDone = done.length >= current.sets;
  const allDone = logged >= total;
  // The next unfinished slot after this one, wrapping: sessions get done out of order
  // whenever a rack is taken.
  const nextIndex = [...items.keys()]
    .map((k) => (index + 1 + k) % items.length)
    .find((k) => k !== index && doneCount(items[k]!.exercise_id) < items[k]!.sets);
  const next = nextIndex === undefined ? undefined : items[nextIndex];

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col px-5">
      <div className="flex items-center justify-between pt-4">
        <Button variant="ghost" compact className="-ml-3" onClick={() => router.push("/today")}>
          Close
        </Button>
        <span className="label">
          Exercise {index + 1} / {items.length}
        </span>
        <SyncBadge />
      </div>

      <SlotBar items={items} doneCount={doneCount} index={index} onSelect={setIndex} />

      {/* Keyed so a new exercise remounts and fades up rather than its name and numbers
          swapping in place. No sideways slide: the strip jumps backwards as well. */}
      <section
        key={current.exercise_id}
        className="mt-4 transition-[opacity,transform] duration-200 ease-out-soft starting:translate-y-1 starting:opacity-0"
      >
        <Frames slug={current.slug} className="mb-4 h-44" />
        <h1 className="text-[2rem] leading-[1.05] text-ink">{current.slug.replaceAll("_", " ")}</h1>
        <p className="mt-3 flex items-baseline gap-2">
          <span className="font-display text-hero font-extrabold text-accent">{value}</span>
          <span className="font-display text-[1.25rem] font-semibold text-ink-muted uppercase">{unit}</span>
          <span className="ml-auto font-display text-[1.375rem] font-semibold text-ink-muted">
            {current.sets} × {current.target_reps}
            <span className="text-ink-faint"> · RIR {current.target_rir}</span>
          </span>
        </p>
        <p
          className={cn(
            "mt-2 text-[0.875rem]",
            delta.direction === "up" ? "text-accent" : "text-ink-faint",
          )}
        >
          {delta.text}
        </p>
      </section>

      <div className="mt-5 space-y-3">
        <SetList item={current} sets={done} units={units} />
        {done.length > 0 && <RestTimer since={done.at(-1)!.at} />}
        <HowTo slug={current.slug} name={current.slug.replaceAll("_", " ")} />
      </div>

      <div className="mt-auto space-y-3 pt-8 pb-6">
        <Stepper label="Reps" value={reps} onChange={setReps} min={1} max={50} />
        <Stepper label="RIR" value={rir} onChange={setRir} min={0} max={5} />
        {load !== null && (
          <Stepper
            label="Load"
            value={load}
            onChange={setLoad}
            min={0}
            max={500}
            step={LOAD_STEP}
            suffix="kg"
            hint={
              current.load === null
                ? "First time: set your weight"
                : Number(current.load) !== load
                  ? `Prescribed ${prescribed}`
                  : undefined
            }
          />
        )}

        <Button
          variant={exerciseDone ? "secondary" : "primary"}
          full
          loading={saving}
          onClick={logSet}
        >
          Log set {done.length + 1}
        </Button>

        {exerciseDone && !allDone && next && nextIndex !== undefined && (
          <Button variant="primary" full onClick={() => setIndex(nextIndex)}>
            Next: {next.slug.replaceAll("_", " ")}
          </Button>
        )}
        {allDone && outcome === null && (
          <Button variant="primary" full onClick={() => void finish("completed")}>
            Finish workout
          </Button>
        )}

        {swapping ? (
          <>
            <SwapList item={current} onPick={(s) => void swapTo(s)} />
            <Button full variant="ghost" onClick={() => setSwapping(false)}>
              Keep this one
            </Button>
          </>
        ) : (
          <div className="flex gap-2">
            <Button full onClick={() => setSwapping(true)} disabled={current.substitutes.length === 0}>
              {current.substitutes.length ? "In use — swap" : "No alternative on this device"}
            </Button>
            {done.length > 0 && (
              <Button variant="ghost" onClick={undoLast} aria-label="Undo last set">
                <UndoIcon className="size-5" />
              </Button>
            )}
          </div>
        )}

        {outcome === null && logged > 0 && logged < total && (
          <Button full variant="ghost" onClick={() => void finish("abandoned")}>
            End workout early
          </Button>
        )}
      </div>
    </main>
  );
}
