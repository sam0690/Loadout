import type { PlanPayload } from "./api/client";
import type { LoggedSet } from "./queue";
import { fromDay, localDay } from "./day";

/**
 * What this device can honestly say about how training is going.
 *
 * Everything here is **counting** — sets, reps, tonnage, days. That boundary is
 * deliberate. Progression arithmetic (e1RM, double progression, the volume landmarks)
 * lives in `engine/` as pure Python and is the single source of it; reimplementing
 * Epley in TypeScript to draw a nicer chart would give the project two implementations
 * of the same formula, free to drift, which is exactly what constraint 1 exists to
 * prevent. An e1RM trend needs `exercise_state` exposed over the API, not a second
 * copy of the maths here.
 *
 * "Hard" is a logged RIR of 3 or less, per D7 — the achieved side of that decision's
 * prescribed-vs-logged split.
 */
const HARD_RIR = 3;
const TREND_WEEKS = 6;

export interface MuscleVolume {
  muscle: string;
  /** Hard sets actually logged this week. */
  done: number;
  /** Hard sets this week's plan asked for. */
  prescribed: number;
}

export interface WeekPoint {
  /** Monday of the week, as YYYY-MM-DD. */
  weekStart: string;
  hardSets: number;
  /** Sum of load × reps, where a load was recorded. Zero for bodyweight-only weeks. */
  tonnageKg: number;
}

export interface Analysis {
  /** Sets logged against sets prescribed for the plan's week. */
  done: number;
  prescribed: number;
  /** Days in the plan on which at least one set was logged, over days planned. */
  sessionsTouched: number;
  sessionsPlanned: number;
  muscles: MuscleVolume[];
  weeks: WeekPoint[];
  /** True once anything at all has been logged; the panel hides before that. */
  hasData: boolean;
}

export const isHard = (set: LoggedSet): boolean => set.rir <= HARD_RIR;

/** The Monday of a day's week, in the user's own zone. */
export function weekStart(day: string): string {
  const date = fromDay(day);
  if (date === null) return day;
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  return localDay(date);
}

export function analyse(
  sets: LoggedSet[],
  plan: PlanPayload | null,
  today: string = localDay(),
): Analysis {
  const planDays = new Set((plan?.sessions ?? []).map((s) => s.day));
  // Adherence is measured over the plan's *week*, not its exact days. Plans are weekly
  // (D16), and someone who moved Wednesday's session to Tuesday did the work — counting
  // only the prescribed dates would report that week as a miss.
  const firstDay = [...planDays].sort()[0];
  const planWeek = firstDay === undefined ? null : weekStart(firstDay);
  const inPlanWeek =
    planWeek === null ? [] : sets.filter((s) => weekStart(s.day) === planWeek);

  // Muscle comes from the plan, which ships primary_muscle with every item. A set on
  // an exercise the current plan does not contain has no muscle we can name without
  // the catalog, so it counts toward the week but not toward the breakdown.
  const muscleOf = new Map<string, string>();
  const prescribed = new Map<string, number>();
  let prescribedSets = 0;
  for (const session of plan?.sessions ?? []) {
    for (const item of session.items) {
      muscleOf.set(item.exercise_id, item.primary_muscle);
      prescribedSets += item.sets;
      // Only sets the plan itself considers hard belong in the comparison (D7).
      if (item.target_rir <= HARD_RIR) {
        prescribed.set(
          item.primary_muscle,
          (prescribed.get(item.primary_muscle) ?? 0) + item.sets,
        );
      }
    }
  }

  const done = new Map<string, number>();
  for (const set of inPlanWeek) {
    if (!isHard(set)) continue;
    const muscle = muscleOf.get(set.exerciseId);
    if (muscle === undefined) continue;
    done.set(muscle, (done.get(muscle) ?? 0) + 1);
  }

  const muscles = [...new Set([...prescribed.keys(), ...done.keys()])]
    .map((muscle) => ({
      muscle,
      done: done.get(muscle) ?? 0,
      prescribed: prescribed.get(muscle) ?? 0,
    }))
    // Most work first: the reader is scanning for where the volume went.
    .sort((a, b) => b.prescribed - a.prescribed || b.done - a.done);

  const touched = new Set(inPlanWeek.map((s) => s.day));

  return {
    done: inPlanWeek.length,
    prescribed: prescribedSets,
    sessionsTouched: touched.size,
    sessionsPlanned: planDays.size,
    muscles,
    weeks: trend(sets, today),
    hasData: sets.length > 0,
  };
}

/**
 * Hard sets per week, most recent last.
 *
 * Hard sets rather than tonnage as the headline series: the launch cohort is the
 * minimal-equipment user (PRD §10), and a bodyweight week has a tonnage of zero, which
 * would draw an empty chart for the people the product is aimed at. Tonnage rides
 * along for anyone lifting something.
 */
function trend(sets: LoggedSet[], today: string): WeekPoint[] {
  const buckets = new Map<string, WeekPoint>();
  const thisWeek = weekStart(today);

  // Seed the window so quiet weeks render as gaps rather than vanishing.
  // fromDay, not `new Date(thisWeek)`: the string form parses as UTC midnight and
  // reading local parts back off it lands on the previous day west of Greenwich.
  const monday = fromDay(thisWeek);
  if (monday === null) return [];
  for (let i = TREND_WEEKS - 1; i >= 0; i--) {
    const d = new Date(monday);
    d.setDate(monday.getDate() - i * 7);
    const key = localDay(d);
    buckets.set(key, { weekStart: key, hardSets: 0, tonnageKg: 0 });
  }

  for (const set of sets) {
    const bucket = buckets.get(weekStart(set.day));
    if (bucket === undefined) continue;
    if (isHard(set)) bucket.hardSets += 1;
    if (set.load !== null) bucket.tonnageKg += Number(set.load) * set.reps;
  }

  return [...buckets.values()];
}
