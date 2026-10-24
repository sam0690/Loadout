import type { LoggedSet } from "./queue";

/**
 * Epley e1RM, for display only. The engine's copy (engine/progression) is the one that
 * prescribes; this one only labels a PR the user has already lifted.
 */
export const e1rm = (load: number, reps: number): number => load * (1 + reps / 30);

export interface ExerciseSummary {
  exerciseId: string;
  name: string;
  sets: LoggedSet[];
  /** Best e1RM today, null for bodyweight work. */
  best: number | null;
  /** Best e1RM on any earlier day, null if never loaded before. */
  previous: number | null;
  isPr: boolean;
}

export interface Summary {
  day: string;
  sets: number;
  reps: number;
  volumeKg: number;
  /** First set to last set; null for a single set, where there is no span to measure. */
  minutes: number | null;
  exercises: ExerciseSummary[];
}

const bestOf = (sets: readonly LoggedSet[]): number | null => {
  const loaded = sets.filter((s) => s.load !== null && Number(s.load) > 0);
  return loaded.length ? Math.max(...loaded.map((s) => e1rm(Number(s.load), s.reps))) : null;
};

/**
 * One day's work, from every set on the device (any order).
 *
 * A PR needs something to beat: the first time an exercise is loaded it sets a baseline,
 * not a record, or every new user's first session would be a wall of trophies.
 */
export function summarise(all: readonly LoggedSet[], day: string): Summary {
  const today = all.filter((s) => s.day === day).sort((a, b) => a.at.localeCompare(b.at));
  const ids = [...new Set(today.map((s) => s.exerciseId))];

  const exercises = ids.map((id) => {
    const sets = today.filter((s) => s.exerciseId === id);
    const best = bestOf(sets);
    const previous = bestOf(all.filter((s) => s.exerciseId === id && s.day < day));
    return {
      exerciseId: id,
      name: (sets[0]!.slug ?? "exercise").replaceAll("_", " "),
      sets,
      best,
      previous,
      isPr: best !== null && previous !== null && best > previous,
    };
  });

  const span =
    today.length > 1
      ? (new Date(today.at(-1)!.at).getTime() - new Date(today[0]!.at).getTime()) / 60_000
      : null;

  return {
    day,
    sets: today.length,
    reps: today.reduce((n, s) => n + s.reps, 0),
    volumeKg: today.reduce((n, s) => n + s.reps * (s.load === null ? 0 : Number(s.load)), 0),
    minutes: span === null ? null : Math.max(1, Math.round(span)),
    exercises,
  };
}
