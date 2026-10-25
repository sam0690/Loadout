import type { LoggedSet } from "./queue";
import { e1rm } from "./summary";

export interface Point {
  day: string;
  value: number;
}

/**
 * One exercise over time.
 *
 * Loaded work is tracked as best e1RM per day, so a heavier triple and a lighter set of
 * ten compare on one scale. Bodyweight work has no load to put through Epley, so it is
 * tracked as best reps -- the honest measure of a push-up getting stronger.
 */
export interface Trend {
  exerciseId: string;
  name: string;
  kind: "e1rm" | "reps";
  points: Point[];
  record: Point;
  /** Last point minus first; 0 with a single session. */
  change: number;
}

/** Every exercise logged on this device, most recently trained first. */
export function trends(sets: readonly LoggedSet[]): Trend[] {
  const byExercise = new Map<string, LoggedSet[]>();
  for (const s of sets) byExercise.set(s.exerciseId, [...(byExercise.get(s.exerciseId) ?? []), s]);

  const out = [...byExercise.entries()].map(([exerciseId, own]): Trend => {
    // A loaded set anywhere in the history makes it a loaded exercise; bodyweight sets
    // of it then sit out the e1RM line rather than dragging it to zero.
    const loaded = own.some((s) => s.load !== null && Number(s.load) > 0);
    const valued = own.filter((s) => !loaded || (s.load !== null && Number(s.load) > 0));
    const bestByDay = new Map<string, number>();
    for (const s of valued) {
      const v = loaded ? e1rm(Number(s.load), s.reps) : s.reps;
      bestByDay.set(s.day, Math.max(bestByDay.get(s.day) ?? 0, v));
    }
    const points = [...bestByDay.entries()]
      .map(([day, value]) => ({ day, value }))
      .sort((a, b) => a.day.localeCompare(b.day));
    const record = points.reduce((best, p) => (p.value > best.value ? p : best));
    return {
      exerciseId,
      name: (own.find((s) => s.slug)?.slug ?? "exercise").replaceAll("_", " "),
      kind: loaded ? "e1rm" : "reps",
      points,
      record,
      change: points.at(-1)!.value - points[0]!.value,
    };
  });

  return out.sort((a, b) => b.points.at(-1)!.day.localeCompare(a.points.at(-1)!.day));
}

/**
 * Records set across the whole log: each loaded day that beat every earlier day of the
 * same exercise. The first day only sets a baseline, as in `summarise`, so the count
 * agrees with the PR cards a user saw at the end of each session.
 */
export function records(all: readonly Trend[]): number {
  let n = 0;
  for (const t of all) {
    if (t.kind !== "e1rm") continue;
    let best = t.points[0]!.value;
    for (const p of t.points.slice(1)) {
      if (p.value > best) n++;
      best = Math.max(best, p.value);
    }
  }
  return n;
}
