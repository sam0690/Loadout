"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { PlanPayload } from "@/lib/api/client";
import { enqueue, loggedToday } from "@/lib/queue";
import { SyncBadge } from "@/components/SyncBadge";

type Item = PlanPayload["sessions"][number]["items"][number];

/**
 * The screen that matters. Used mid-set, one-handed, possibly sweaty.
 *
 * Every control is a full-width button. There is no modal, no dropdown and no free-text
 * input in the logging path: reps and RIR are steppers, because typing a number with wet
 * hands between sets is the thing that stops people logging at all.
 */
export default function Logger({
  params,
}: {
  params: Promise<{ exerciseId: string }>;
}) {
  const { exerciseId } = use(params);
  const router = useRouter();
  const [item, setItem] = useState<Item | null>(null);
  const [reps, setReps] = useState(10);
  const [rir, setRir] = useState(2);
  const [done, setDone] = useState<number[]>([]);
  const [swapping, setSwapping] = useState(false);

  useEffect(() => {
    const raw = window.localStorage.getItem("loadout.plan");
    if (!raw) return;
    const plan = JSON.parse(raw) as PlanPayload;
    const found = plan.sessions
      .flatMap((s) => s.items)
      .find((i) => i.exercise_id === exerciseId);
    if (found) {
      setItem(found);
      setReps(found.target_reps);
      setRir(found.target_rir);
    }
    const day = new Date().toISOString().slice(0, 10);
    void loggedToday(exerciseId, day).then((events) =>
      setDone(events.map((e) => Number(e.payload.reps))),
    );
  }, [exerciseId]);

  /**
   * The occupied-machine flow (PRD §6), and the reason substitutes travel with the plan.
   *
   * Everything needed is already on the device: the alternatives, their names and their
   * equipment. No request is made, because this happens mid-set in a basement. The swap
   * is recorded as an event with reason "unavailable_now", which is a different signal
   * from disliking an exercise and must not be conflated with one.
   */
  async function swapTo(substitute: { exercise_id: string; slug: string }) {
    if (!item) return;
    await enqueue("exercise_swapped", {
      from_exercise_id: item.exercise_id,
      to_exercise_id: substitute.exercise_id,
      reason: "unavailable_now",
    });
    router.replace(`/log/${substitute.exercise_id}`);
  }

  async function logSet() {
    if (!item) return;
    // Optimistic and local-first: the set is on screen before anything touches the
    // network, and stays there whether or not the network exists.
    setDone((prev) => [...prev, reps]);
    await enqueue("set_logged", {
      exercise_id: exerciseId,
      reps,
      rir,
      load: item.load,
      target_bottom: item.target_reps,
      target_top: item.target_reps,
    });
  }

  if (!item) {
    return <main className="p-6 text-white/60">No plan on this device yet.</main>;
  }

  return (
    <main className="flex min-h-dvh flex-col">
      <header className="px-6 pt-6">
        <h1 className="text-2xl font-semibold">{item.slug.replaceAll("_", " ")}</h1>
        <p className="mt-1 text-white/50">
          {item.sets} × {item.target_reps} @ RIR {item.target_rir}
          {item.load ? ` · ${item.load}kg` : ""}
        </p>
      </header>

      <ol className="flex gap-2 px-6 pt-5" aria-label="sets completed">
        {Array.from({ length: item.sets }).map((_, i) => (
          <li
            key={i}
            className={`h-2 flex-1 rounded-full ${
              i < done.length ? "bg-emerald-400" : "bg-white/15"
            }`}
          />
        ))}
      </ol>

      <div className="mt-auto space-y-3 px-6 pb-6">
        <Stepper label="Reps" value={reps} onChange={setReps} min={1} max={50} />
        <Stepper label="RIR" value={rir} onChange={setRir} min={0} max={5} />
        <button
          onClick={logSet}
          className="w-full rounded-2xl bg-emerald-500 text-lg font-semibold text-black active:bg-emerald-400"
        >
          Log set {done.length + 1}
        </button>
        {!swapping && (
          <button
            onClick={() => setSwapping(true)}
            disabled={item.substitutes.length === 0}
            className="w-full rounded-2xl border border-white/15 text-white/70 disabled:opacity-30"
          >
            {item.substitutes.length ? "In use — swap" : "No alternative on this device"}
          </button>
        )}

        {swapping && (
          // Inline, not a modal: a dialog needing a precise tap to dismiss is a trap
          // when the user is holding a dumbbell.
          <div className="space-y-2">
            {item.substitutes.map((substitute) => (
              <button
                key={substitute.exercise_id}
                onClick={() => swapTo(substitute)}
                className="w-full rounded-2xl bg-white/10 px-4 py-4 text-left capitalize"
              >
                <span className="block">{substitute.slug.replaceAll("_", " ")}</span>
                <span className="block text-xs opacity-50">
                  {substitute.equipment.length
                    ? substitute.equipment.join(", ").replaceAll("_", " ")
                    : "no equipment"}
                </span>
              </button>
            ))}
            <button
              onClick={() => setSwapping(false)}
              className="w-full rounded-2xl border border-white/15 text-white/50"
            >
              Keep this one
            </button>
          </div>
        )}

        <button
          onClick={() => router.push("/plan")}
          className="w-full rounded-2xl border border-white/15 text-white/70"
        >
          Done
        </button>
      </div>
      <SyncBadge />
    </main>
  );
}

/** A stepper, not a text field: no keyboard, no focus, no precision required. */
function Stepper({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min: number;
  max: number;
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        aria-label={`${label} down`}
        onClick={() => onChange(Math.max(min, value - 1))}
        className="w-20 rounded-2xl bg-white/10 text-2xl"
      >
        −
      </button>
      <div className="flex-1 text-center">
        <div className="text-3xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
      </div>
      <button
        aria-label={`${label} up`}
        onClick={() => onChange(Math.min(max, value + 1))}
        className="w-20 rounded-2xl bg-white/10 text-2xl"
      >
        +
      </button>
    </div>
  );
}
