import {
  api,
  type Experience,
  type Goal,
  type PlanOut,
  type PlanPayload,
} from "./api/client";

/**
 * Requesting a plan and waiting for it.
 *
 * This lived inline in the plan screen, which meant onboarding could not generate a
 * first plan without duplicating it. Both callers need the same poll, the same failure
 * modes and the same caching, so it lives here once.
 */
const CACHE_KEY = "loadout.plan";
const POLL_MS = 500;
const POLL_ATTEMPTS = 60;

/**
 * Which weekdays a given number of sessions lands on, as offsets from Monday.
 *
 * Spread rather than packed: the engine's own fatigue gate (D14) refuses to program a
 * muscle hard on consecutive days, so handing it back-to-back days costs it choices it
 * did not need to lose.
 */
const SPREADS: Record<number, readonly number[]> = {
  1: [2],
  2: [0, 3],
  3: [0, 2, 4],
  4: [0, 1, 3, 4],
  5: [0, 1, 2, 3, 4],
  6: [0, 1, 2, 3, 4, 5],
  7: [0, 1, 2, 3, 4, 5, 6],
};

/**
 * The dates for this week's sessions, in the user's own zone.
 *
 * The engine has no clock and no timezone (constraint 1), so the client resolves real
 * calendar dates and sends those. Anchored to this ISO week's Monday because the API
 * requires every day to fall in one ISO week, and D16 makes plans weekly.
 */
export function sessionDates(daysPerWeek: number, now: Date = new Date()): string[] {
  const monday = new Date(now);
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const offsets = SPREADS[Math.min(7, Math.max(1, daysPerWeek))] ?? SPREADS[3]!;

  // Onboarding on a Saturday used to hand back a week whose every session had already
  // happened -- nothing to log, and the first thing a new user saw. Roll to next week
  // only when the whole spread is behind us, so the common case is untouched.
  const lastOffset = offsets[offsets.length - 1]!;
  const last = new Date(monday);
  last.setDate(monday.getDate() + lastOffset);
  if (last < startOfDay(now)) monday.setDate(monday.getDate() + 7);

  return offsets.map((offset) => {
    const day = new Date(monday);
    day.setDate(monday.getDate() + offset);
    // Local date parts, not toISOString: the latter converts to UTC first and can move
    // the date across midnight for anyone east or west of it.
    return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
  });
}

const pad = (n: number): string => String(n).padStart(2, "0");

const startOfDay = (d: Date): Date =>
  new Date(d.getFullYear(), d.getMonth(), d.getDate());

export interface Preferences {
  goal: Goal;
  experience: Experience;
  daysPerWeek: number;
  sessionMinutes: number;
}

export class GenerationError extends Error {}

/**
 * Enqueue a plan and wait for the worker, then return it.
 *
 * Generation is queued rather than served inline (§6), so the only honest thing the
 * client can do is poll. Throws rather than returning a null plan: a failed generation
 * that looks like an empty week is the worst of the available outcomes.
 */
export async function generatePlan(
  contextId: string,
  prefs: Preferences,
): Promise<PlanOut> {
  const { job_id } = await api.requestPlan({
    training_context_id: contextId,
    days: sessionDates(prefs.daysPerWeek),
    time_budget_minutes: prefs.sessionMinutes,
    experience: prefs.experience,
    goal: prefs.goal,
  });

  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt++) {
    const job = await api.job(job_id);
    if (job.status === "finished") {
      const plan = await api.currentPlan();
      cachePlan(plan.payload as PlanPayload);
      return plan;
    }
    if (job.status === "failed") {
      throw new GenerationError("The generator could not build a plan from that setup.");
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  throw new GenerationError("Generation is taking longer than expected.");
}

/**
 * The plan is cached the moment it arrives, because the logger has to open with no
 * network — including the substitution set for every exercise, resolved at generation
 * precisely so the swap works offline (§6).
 */
export function cachePlan(payload: PlanPayload): void {
  window.localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
}

export function cachedPlan(): PlanPayload | null {
  const raw = window.localStorage.getItem(CACHE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PlanPayload;
  } catch {
    // A corrupt cache is not worth crashing the only screen that works offline.
    return null;
  }
}
