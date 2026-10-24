import type { PlanPayload } from "./api/client";
import type { LoggedSet } from "./queue";
import { displayLoad, type Units } from "./units";

type Session = PlanPayload["sessions"][number];
export type Item = Session["items"][number];

/**
 * The session a workout runs through: today's when today has one, otherwise the one
 * holding the exercise that was opened. Opening an exercise from another day still
 * lets someone train it, which is what the one-exercise logger used to allow.
 */
export function workoutSession(
  plan: PlanPayload,
  today: string,
  exerciseId: string | null,
  swaps: ReadonlyMap<string, string>,
): Session | null {
  const holds = (s: Session) =>
    exerciseId === null ||
    s.items.some((i) => i.exercise_id === exerciseId || swaps.get(i.exercise_id) === exerciseId);
  const todays = plan.sessions.find((s) => s.day === today);
  if (todays && holds(todays)) return todays;
  return exerciseId === null ? null : (plan.sessions.find(holds) ?? null);
}

/**
 * The session's items with today's swaps applied, slot for slot.
 *
 * A substitute keeps the slot's sets, reps and RIR and starts from its load: the user
 * adjusts it with the stepper, and the engine seeds real state for it from what they
 * log (D15). It carries no substitutes of its own.
 *
 * ponytail: one swap per slot -- swapping a substitute again is not offered. Add a
 * chain (and swapping back) if real logs show people needing it.
 */
export function applySwaps(items: readonly Item[], swaps: ReadonlyMap<string, string>): Item[] {
  return items.map((item) => {
    const to = swaps.get(item.exercise_id);
    const sub = to === undefined ? undefined : item.substitutes.find((s) => s.exercise_id === to);
    return sub ? { ...item, exercise_id: sub.exercise_id, slug: sub.slug, substitutes: [] } : item;
  });
}

export type Delta = { direction: "up" | "down" | "same" | "first"; text: string };

/**
 * Today's prescription against the last time this exercise was trained.
 *
 * Arithmetic on two numbers the user can already see, nothing more: the engine made the
 * decision, this only makes it visible. `sets` is newest-first, as `loggedSets` returns.
 */
export function deltaVsLast(
  item: Pick<Item, "exercise_id" | "load" | "target_reps">,
  sets: readonly LoggedSet[],
  today: string,
  units: Units,
): Delta {
  const lastDay = sets.find((s) => s.exerciseId === item.exercise_id && s.day < today)?.day;
  if (lastDay === undefined) return { direction: "first", text: "First time logging this one" };
  const last = sets.filter((s) => s.exerciseId === item.exercise_id && s.day === lastDay);
  const bestReps = Math.max(...last.map((s) => s.reps));

  const before = Math.max(...last.map((s) => (s.load === null ? 0 : Number(s.load))));
  const now = item.load === null ? 0 : Number(item.load);
  if (item.load === null || before === 0) {
    return { direction: "same", text: `Last time: best set ${bestReps} reps` };
  }
  const diff = Number((now - before).toFixed(2));
  if (diff > 0) return { direction: "up", text: `▲ ${displayLoad(diff, units)} vs last time` };
  if (diff < 0) return { direction: "down", text: `▼ ${displayLoad(-diff, units)} vs last time` };
  return { direction: "same", text: `Same load — beat ${bestReps} reps` };
}
