import { pending, markRejected, markSynced } from "./queue";

export interface SyncResult {
  attempted: number;
  stored: number;
}

/** Batch size. Small enough that a flaky connection makes progress rather than
 * repeatedly failing one enormous request. */
const CHUNK = 50;

/**
 * Push everything unsynced. Safe to call at any time, from anywhere.
 *
 * Retries are free because the server upserts on the client-generated id, so a request
 * that timed out after the server committed costs a duplicate send and nothing else.
 * Events are only marked synced once the server has answered, so a crash mid-flush
 * re-sends rather than loses.
 */
type Post = (
  events: unknown[],
) => Promise<{ stored: number; rejected?: { id: string; reason: string }[] }>;

export async function flush(post: Post): Promise<SyncResult> {
  const queue = await pending();
  let stored = 0;
  for (let i = 0; i < queue.length; i += CHUNK) {
    const batch = queue.slice(i, i + CHUNK);
    const body = batch.map(({ synced_at: _synced, rejected: _rejected, ...event }) => event);
    const result = await post(body);
    stored += result.stored;
    const turnedAway = new Set((result.rejected ?? []).map((r) => r.id));
    await markSynced(batch.filter((e) => !turnedAway.has(e.id)).map((e) => e.id));
    await markRejected(result.rejected ?? []);
  }
  return { attempted: queue.length, stored };
}

/**
 * Flush now, on reconnect, and every `everyMs` while the app is open.
 *
 * Reconnect alone was not enough: a user who stays online through a whole workout never
 * fires an "online" event, so their sets sat on the phone until the app was next opened
 * from cold -- and every plan generated meanwhile was built without them. The interval
 * reads the queue first, so an idle tick is one IndexedDB read and no request.
 *
 * One flush at a time. Overlap would only cost a duplicate send (the server dedupes on
 * the client id), but a slow connection would otherwise stack a request per tick.
 * Returns a teardown.
 */
export function keepSynced(
  post: Post,
  everyMs: number,
): () => void {
  let running = false;
  const run = () => {
    if (running) return;
    running = true;
    void flush(post)
      .catch(() => {
        // Offline is the normal case, not an error. The queue keeps the events and the
        // next tick or online event tries again.
      })
      .finally(() => {
        running = false;
      });
  };
  run();
  window.addEventListener("online", run);
  const timer = setInterval(run, everyMs);
  return () => {
    window.removeEventListener("online", run);
    clearInterval(timer);
  };
}
