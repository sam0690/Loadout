import Dexie, { type EntityTable } from "dexie";

/**
 * One logged event, exactly as `POST /events` will receive it.
 *
 * `id` is generated here, on the client, and is the idempotency key (CLAUDE.md
 * constraint 3). The server upserts on it, so a retry is free and a flush that half
 * succeeded can simply be run again.
 */
export interface QueuedEvent {
  id: string;
  type:
    | "set_logged"
    | "exercise_swapped"
    | "workout_completed"
    | "workout_abandoned"
    | "feedback_submitted";
  payload: Record<string, unknown>;
  client_ts: string;
  user_tz: string;
  /** Null until the server has acknowledged it. Rows are kept, not deleted, so a
   * successful flush is distinguishable from a queue that was never written to. */
  synced_at: string | null;
  /** Set when the server turned this event away as malformed. Kept on the device, never
   * resent: one bad event must not hold up every good one queued behind it. */
  rejected?: string;
}

const db = new Dexie("loadout") as Dexie & {
  events: EntityTable<QueuedEvent, "id">;
};

// synced_at is indexed because the only hot query is "what still needs sending".
db.version(1).stores({ events: "id, synced_at, client_ts" });

export { db };
