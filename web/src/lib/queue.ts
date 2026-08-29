import { db, type QueuedEvent } from "./db";

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
  };
  await db.events.add(event);
  return event;
}

export async function pending(): Promise<QueuedEvent[]> {
  // Dexie cannot index null, so the filter is in memory. The queue is a session's worth
  // of sets; if that ever stops being true, store a 0/1 flag instead of a timestamp.
  const all = await db.events.orderBy("client_ts").toArray();
  return all.filter((e) => e.synced_at === null);
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
  const all = await db.events.orderBy("client_ts").toArray();
  return all.filter(
    (e) =>
      e.type === "set_logged" &&
      e.payload.exercise_id === exerciseId &&
      e.client_ts.slice(0, 10) === day,
  );
}
