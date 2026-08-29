import { pending, markSynced } from "./queue";

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
export async function flush(
  post: (events: unknown[]) => Promise<{ stored: number }>,
): Promise<SyncResult> {
  const queue = await pending();
  let stored = 0;
  for (let i = 0; i < queue.length; i += CHUNK) {
    const batch = queue.slice(i, i + CHUNK);
    const body = batch.map(({ synced_at: _synced, ...event }) => event);
    const result = await post(body);
    stored += result.stored;
    await markSynced(batch.map((e) => e.id));
  }
  return { attempted: queue.length, stored };
}

/**
 * Flush now, and again whenever the browser thinks it is back online.
 * Returns a teardown so a component can stop listening.
 */
export function syncOnReconnect(
  post: (events: unknown[]) => Promise<{ stored: number }>,
): () => void {
  const run = () => {
    void flush(post).catch(() => {
      // Offline is the normal case, not an error. The queue keeps the events and the
      // next online event tries again.
    });
  };
  run();
  window.addEventListener("online", run);
  return () => window.removeEventListener("online", run);
}
