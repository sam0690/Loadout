import { db, type QueuedEvent } from "./db";
import { currentUserId } from "./api/client";
import { localDay } from "./day";

/** The user's own zone, resolved here rather than on the server (constraint 6). */
export function userTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * Write an event locally. This is the only write path.
 *
 * The logger renders from IndexedDB, not from the response, so a set is recorded the
 * moment the user taps — mid-set, one-handed, in a basement with no signal. Sync is a
 * background concern that never blocks the interaction.
 */
export async function enqueue(
  type: QueuedEvent["type"],
  payload: Record<string, unknown>,
  now: Date = new Date(),
): Promise<QueuedEvent> {
  const event: QueuedEvent = {
    // Client-generated, and the server's idempotency key (constraint 3).
    id: crypto.randomUUID(),
    type,
    payload,
    client_ts: now.toISOString(),
    user_tz: userTimezone(),
    synced_at: null,
    user: currentUserId() ?? undefined,
  };
  await db.events.add(event);
  return event;
}

/**
 * This account's events, oldest first. Every read goes through here.
 *
 * The device store outlives a sign-out (unsent sets must not be lost), so without this a
 * second account on the same phone saw the first one's history -- and uploaded its
 * unsent sets under the wrong account.
 */
async function mine(): Promise<QueuedEvent[]> {
  const user = currentUserId();
  const all = await db.events.orderBy("client_ts").toArray();
  return all.filter((e) => e.user === undefined || e.user === user);
}

export async function pending(): Promise<QueuedEvent[]> {
  // Dexie cannot index null, so the filter is in memory. The queue is a session's worth
  // of sets; if that ever stops being true, store a 0/1 flag instead of a timestamp.
  const all = await mine();
  return all.filter((e) => e.synced_at === null && e.rejected === undefined);
}

export async function markRejected(rejected: { id: string; reason: string }[]): Promise<void> {
  await Promise.all(rejected.map(({ id, reason }) => db.events.update(id, { rejected: reason })));
}

export async function markSynced(ids: string[], at: Date = new Date()): Promise<void> {
  const stamp = at.toISOString();
  await db.events.where("id").anyOf(ids).modify({ synced_at: stamp });
}

/** Everything logged for one exercise today, newest last. Renders the logger. */
export async function loggedToday(
  exerciseId: string,
  day: string,
): Promise<QueuedEvent[]> {
  const all = await mine();
  return all.filter(
    (e) =>
      e.type === "set_logged" &&
      e.payload.exercise_id === exerciseId &&
      e.client_ts.slice(0, 10) === day,
  );
}

/** One set as it was logged, with the payload's loose JSON narrowed once, here. */
export interface LoggedSet {
  id: string;
  exerciseId: string;
  /**
   * The exercise's name, carried on the event itself.
   *
   * History has to render months after the plan that prescribed the set was replaced,
   * and a log entry that cannot be read without joining against a catalog which has
   * since moved is a weaker record than one that describes itself. Absent on events
   * written before this, hence the null.
   */
  slug: string | null;
  reps: number;
  rir: number;
  load: string | null;
  at: string;
  /** The user's own calendar day, not the UTC one (constraint 6). */
  day: string;
  synced: boolean;
}

function asLoggedSet(event: QueuedEvent): LoggedSet {
  const p = event.payload;
  return {
    id: event.id,
    exerciseId: String(p.exercise_id ?? ""),
    slug: p.slug == null ? null : String(p.slug),
    reps: Number(p.reps ?? 0),
    rir: Number(p.rir ?? 0),
    load: p.load == null ? null : String(p.load),
    at: event.client_ts,
    day: localDay(new Date(event.client_ts)),
    synced: event.synced_at !== null,
  };
}

/**
 * Every set on this device, newest first.
 *
 * Reads the queue rather than the server because history has to work offline too, and
 * the queue already holds every set including the ones not yet sent.
 */
export async function loggedSets(): Promise<LoggedSet[]> {
  const all = (await mine()).reverse();
  return all.filter((e) => e.type === "set_logged").map(asLoggedSet);
}

/**
 * Undo a set that has not left this device yet.
 *
 * The local queue is an outbox, not the log: an event still sitting here has never
 * reached the server, so dropping it is not a mutation of anything append-only
 * (constraint 2). Once it *has* synced the log owns it, and the honest correction is a
 * compensating event rather than a delete — so this refuses, loudly, rather than
 * quietly removing a row from a screen while the server keeps the set forever.
 */
export async function discard(id: string): Promise<void> {
  const event = await db.events.get(id);
  if (event === undefined) return;
  if (event.synced_at !== null) {
    throw new Error(`event ${id} has already synced and cannot be discarded`);
  }
  await db.events.delete(id);
}

/**
 * A day's swaps, from → to, read back from the queue.
 *
 * The swap event is already the record of what replaced what, so a reload mid-workout
 * restores the substitute from it rather than from a second copy of the same fact.
 */
export async function swapsOn(day: string): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  for (const e of await mine()) {
    if (e.type !== "exercise_swapped" || localDay(new Date(e.client_ts)) !== day) continue;
    out.set(String(e.payload.from_exercise_id), String(e.payload.to_exercise_id));
  }
  return out;
}

export type Outcome = "completed" | "abandoned";

/**
 * Whether a day's session has already been closed out, so it is not closed twice.
 *
 * These two events are session-level, not per-exercise: the fatigue gate reads an
 * abandoned workout as `(day, sets_completed)` and caps the next day's work at what was
 * actually managed (`engine/progression/volume.py`). One exercise finishing is not a
 * workout finishing, so this is recorded for the day rather than from the logger.
 */
export async function sessionOutcome(day: string): Promise<Outcome | null> {
  const all = (await mine()).reverse();
  for (const event of all) {
    if (event.type !== "workout_completed" && event.type !== "workout_abandoned") continue;
    if (event.payload.day !== day) continue;
    return event.type === "workout_completed" ? "completed" : "abandoned";
  }
  return null;
}

/** Close out a day's session. `sets_completed` is the evidence the fatigue gate uses. */
export async function closeSession(
  day: string,
  outcome: Outcome,
  setsCompleted: number,
): Promise<void> {
  await enqueue(
    outcome === "completed" ? "workout_completed" : "workout_abandoned",
    { day, sets_completed: setsCompleted },
  );
}

type Stored = Pick<QueuedEvent, "id" | "type" | "payload" | "client_ts" | "user_tz"> & {
  server_ts: string;
};

const restored = new Set<string>();

/**
 * Merge this account's server log into the device, once per account per page load.
 *
 * History, progress and PRs all read the device copy so they work offline, and that copy
 * starts empty on a new phone or after cleared storage. A merge by id is always safe:
 * whatever the server has is synced by definition, and events still waiting here (or
 * turned away) are not on the server, so nothing local is overwritten with older news.
 *
 * ponytail: the whole log on every app load. Fine at a few thousand sets a year; fetch
 * only what is newer than the last restore when that stops being cheap.
 */
export async function restore(fetchAll: () => Promise<Stored[]>): Promise<number> {
  const user = currentUserId();
  if (user === null || restored.has(user)) return 0;
  const remote = await fetchAll();
  await db.events.bulkPut(
    remote.map((e) => ({
      id: e.id,
      type: e.type,
      payload: e.payload,
      // One timestamp format on the device, so ordering by the string stays correct.
      client_ts: new Date(e.client_ts).toISOString(),
      user_tz: e.user_tz,
      synced_at: e.server_ts,
      user,
    })),
  );
  restored.add(user);
  return remote.length;
}
