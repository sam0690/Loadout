"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { PlanPayload } from "@/lib/api/client";
import { cachedPlan } from "@/lib/plan";
import { discard, enqueue, loggedSets, type LoggedSet } from "@/lib/queue";
import { displayLoad, readUnits } from "@/lib/units";
import { localDay } from "@/lib/day";
import { Button } from "@/components/ui/Button";
import { Stepper } from "@/components/ui/Stepper";
import { useToast } from "@/components/ui/Toast";
import { SyncBadge } from "@/components/Sync";
import { BackIcon, CheckIcon, UndoIcon } from "@/components/ui/icons";
import { cn } from "@/components/ui/cn";

type Item = PlanPayload["sessions"][number]["items"][number];

/**
 * The screen that matters. Used mid-set, one-handed, possibly sweaty.
 *
 * Everything here follows from that. No tab bar competing with the primary control; a
 * thumb-width column at every breakpoint, because widening it on a laptop would break
 * the only thing it is designed around; every control full-width and bottom-weighted;
 * no modal, no dropdown, and no free-text input anywhere in the logging path — reps,
 * RIR and load are steppers, because typing a number with wet hands between sets is the
 * thing that stops people logging at all.
 *
 * Exactly one heading element lives here, deliberately: the e2e specs address this
 * screen through `getByRole("heading")`, and a second one would break them.
 */
const LOAD_STEP = 2.5;

export default function Logger({
  params,
}: {
  params: Promise<{ exerciseId: string }>;
}) {
  const { exerciseId } = use(params);
  const router = useRouter();
  const toast = useToast();
  const units = readUnits();

  const [item, setItem] = useState<Item | null>(null);
  const [missing, setMissing] = useState(false);
  const [reps, setReps] = useState(10);
  const [rir, setRir] = useState(2);
  const [load, setLoad] = useState<number | null>(null);
  const [sets, setSets] = useState<LoggedSet[]>([]);
  const [swapping, setSwapping] = useState(false);
  const [saving, setSaving] = useState(false);

  const today = localDay();

  const refresh = useCallback(async () => {
    const all = await loggedSets();
    setSets(
      all
        .filter((s) => s.exerciseId === exerciseId && s.day === today)
        .reverse(), // loggedSets is newest-first; a set list reads oldest-first.
    );
  }, [exerciseId, today]);

  useEffect(() => {
    const plan = cachedPlan();
    const found = plan?.sessions
      .flatMap((s) => s.items)
      .find((i) => i.exercise_id === exerciseId);
    if (found) {
      setItem(found);
      setReps(found.target_reps);
      setRir(found.target_rir);
      setLoad(found.load === null ? null : Number(found.load));
    } else {
      setMissing(true);
    }
    void refresh();
  }, [exerciseId, refresh]);

  /**
   * The occupied-machine flow (PRD §6), and the reason substitutes travel with the plan.
   *
   * Everything needed is already on the device: the alternatives, their names and their
   * equipment. No request is made, because this happens mid-set in a basement. The swap
   * is recorded with reason "unavailable_now", which is a different signal from
   * disliking an exercise and must not be conflated with one.
   */
  async function swapTo(substitute: { exercise_id: string; slug: string }) {
    if (!item) return;
    try {
      await enqueue("exercise_swapped", {
        from_exercise_id: item.exercise_id,
        to_exercise_id: substitute.exercise_id,
        reason: "unavailable_now",
      });
      router.replace(`/log/${substitute.exercise_id}`);
    } catch {
      toast("Could not record the swap on this device.", "error");
    }
  }

  async function logSet() {
    if (!item || saving) return;
    setSaving(true);
    try {
      await enqueue("set_logged", {
        exercise_id: exerciseId,
        // Carried so history can render itself with no catalog and no network.
        slug: item.slug,
        reps,
        rir,
        load: load === null ? null : String(load),
        target_bottom: item.target_reps,
        target_top: item.target_reps,
      });
      await refresh();
    } catch {
      // The write is the product. A set that failed to reach IndexedDB — a full quota,
      // a private window — must never look like a set that was saved.
      toast("That set was not saved. Check your storage and try again.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function undoLast() {
    const last = sets[sets.length - 1];
    if (!last) return;
    try {
      await discard(last.id);
      await refresh();
      toast("Set removed");
    } catch {
      toast("That set has already synced and cannot be undone here.", "error");
    }
  }

  if (missing) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
        <h1 className="text-[1.25rem] font-semibold text-ink">
          This exercise is not on this device
        </h1>
        <p className="text-[0.9375rem] text-ink-faint">
          Open your plan while online once, and the whole week — including the swaps —
          will be here next time.
        </p>
        <Link href="/plan">
          <Button variant="primary">Back to plan</Button>
        </Link>
      </main>
    );
  }

  if (!item) {
    return (
      <main className="mx-auto min-h-dvh max-w-md px-5 pt-16">
        <div className="h-8 w-2/3 animate-pulse rounded-control bg-surface" />
      </main>
    );
  }

  const prescribedLoad = displayLoad(item.load, units);
  const remaining = Math.max(0, item.sets - sets.length);

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col px-5">
      <header className="flex items-start gap-3 pt-6">
        <Link
          href="/plan"
          aria-label="Back to plan"
          className="-ml-2 flex size-11 shrink-0 items-center justify-center rounded-control text-ink-faint transition-colors duration-150 hover:bg-surface hover:text-ink"
        >
          <BackIcon />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-[1.375rem] leading-tight font-semibold tracking-[-0.02em] text-ink capitalize">
            {item.slug.replaceAll("_", " ")}
          </h1>
          <p className="mt-1 text-[0.875rem] text-ink-faint">
            {item.sets} × {item.target_reps} · RIR {item.target_rir}
            {prescribedLoad ? ` · ${prescribedLoad}` : ""}
          </p>
        </div>
      </header>

      {/* What was actually lifted, not just how many dots are filled. */}
      <ol className="mt-6 space-y-1.5" aria-label="Sets completed">
        {sets.map((set, i) => (
          <li
            key={set.id}
            className="flex items-center gap-3 rounded-control bg-surface px-3.5 py-2.5 text-[0.9375rem]"
          >
            <CheckIcon className="size-4 shrink-0 text-accent" />
            <span className="w-6 text-ink-faint">{i + 1}</span>
            <span className="flex-1 text-ink">
              {set.reps} reps
              {set.load ? ` · ${displayLoad(set.load, units)}` : ""}
            </span>
            <span className="text-ink-faint">RIR {set.rir}</span>
          </li>
        ))}
        {Array.from({ length: remaining }).map((_, i) => (
          <li
            key={`todo-${i}`}
            className="flex items-center gap-3 rounded-control border border-dashed border-line px-3.5 py-2.5 text-[0.9375rem] text-ink-faint"
          >
            <span className="size-4 shrink-0" />
            <span className="w-6">{sets.length + i + 1}</span>
            <span className="flex-1">
              {item.target_reps} reps
              {prescribedLoad ? ` · ${prescribedLoad}` : ""}
            </span>
          </li>
        ))}
      </ol>

      {sets.length > 0 && <RestTimer since={sets[sets.length - 1]!.at} />}

      <div className="mt-auto space-y-3 pb-6 pt-8">
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
              item.load !== null && Number(item.load) !== load
                ? `Prescribed ${prescribedLoad}`
                : undefined
            }
          />
        )}

        <Button variant="primary" full loading={saving} onClick={logSet}>
          Log set {sets.length + 1}
        </Button>

        <div className="flex gap-2">
          {!swapping && (
            <Button
              full
              onClick={() => setSwapping(true)}
              disabled={item.substitutes.length === 0}
            >
              {item.substitutes.length ? "In use — swap" : "No alternative on this device"}
            </Button>
          )}
          {sets.length > 0 && !swapping && (
            <Button variant="ghost" onClick={undoLast} aria-label="Undo last set">
              <UndoIcon className="size-5" />
            </Button>
          )}
        </div>

        {swapping && (
          // Inline, not a modal: a dialog needing a precise tap to dismiss is a trap
          // when the user is holding a dumbbell.
          <div className="space-y-2">
            {item.substitutes.map((substitute) => (
              <button
                key={substitute.exercise_id}
                onClick={() => swapTo(substitute)}
                className={cn(
                  "no-select w-full rounded-card bg-surface px-4 py-3.5 text-left capitalize",
                  "transition-colors duration-150 ease-out-soft hover:bg-raised active:bg-raised",
                )}
              >
                <span className="block text-[0.9375rem] text-ink">
                  {substitute.slug.replaceAll("_", " ")}
                </span>
                <span className="mt-0.5 block text-[0.8125rem] normal-case text-ink-faint">
                  {substitute.equipment.length
                    ? substitute.equipment.join(", ").replaceAll("_", " ")
                    : "no equipment"}
                </span>
              </button>
            ))}
            <Button full variant="ghost" onClick={() => setSwapping(false)}>
              Keep this one
            </Button>
          </div>
        )}

        <Button full variant="ghost" onClick={() => router.push("/plan")}>
          Done
        </Button>

        <SyncBadge className="flex justify-center pt-1" />
      </div>
    </main>
  );
}

/**
 * Time since the last set. Counts up rather than down from a prescribed rest, because
 * the engine does not prescribe one and inventing a number here would be the app
 * pretending to know something it does not.
 */
function RestTimer({ since }: { since: string }) {
  const [elapsed, setElapsed] = useState(() => secondsSince(since));

  useEffect(() => {
    setElapsed(secondsSince(since));
    const timer = setInterval(() => setElapsed(secondsSince(since)), 1000);
    return () => clearInterval(timer);
  }, [since]);

  return (
    <p className="mt-4 text-center text-[0.875rem] text-ink-faint" aria-live="off">
      <span className="tabular-nums text-ink-muted">
        {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
      </span>{" "}
      since your last set
    </p>
  );
}

const secondsSince = (iso: string): number =>
  Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));

