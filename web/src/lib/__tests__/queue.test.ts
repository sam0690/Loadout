import { beforeEach, describe, expect, it, vi } from "vitest";
import { db } from "../db";
import { enqueue, loggedToday, markSynced, pending } from "../queue";
import { flush } from "../sync";

beforeEach(async () => {
  await db.events.clear();
});

const set = (exerciseId: string, reps: number) => ({
  exercise_id: exerciseId,
  reps,
  rir: 2,
  load: "60",
  target_bottom: 8,
  target_top: 12,
});

describe("the offline queue", () => {
  it("records a set without any network at all", async () => {
    // The acceptance criterion: a full session is loggable with the network offline.
    const logged = await enqueue("set_logged", set("ex-1", 10));
    expect(logged.synced_at).toBeNull();
    expect(await pending()).toHaveLength(1);
  });

  it("generates the id on the client, as the idempotency key", async () => {
    // Constraint 3. The server upserts on this, which is what makes a retry free.
    const a = await enqueue("set_logged", set("ex-1", 10));
    const b = await enqueue("set_logged", set("ex-1", 11));
    expect(a.id).not.toEqual(b.id);
    expect(a.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("stamps the user's own timezone, never naive local time", async () => {
    const logged = await enqueue("set_logged", set("ex-1", 10));
    expect(logged.user_tz).toBeTruthy();
    expect(logged.client_ts).toMatch(/Z$/);
  });

  it("keeps a whole session in order", async () => {
    for (let reps = 8; reps <= 12; reps++) {
      await enqueue("set_logged", set("ex-1", reps), new Date(2026, 7, 30, 10, reps));
    }
    const queue = await pending();
    expect(queue.map((e) => e.payload.reps)).toEqual([8, 9, 10, 11, 12]);
  });

  it("renders today's sets for one exercise", async () => {
    const today = new Date(2026, 7, 30, 10, 0);
    await enqueue("set_logged", set("ex-1", 10), today);
    await enqueue("set_logged", set("ex-2", 10), today);
    const day = today.toISOString().slice(0, 10);
    expect(await loggedToday("ex-1", day)).toHaveLength(1);
  });
});

describe("flushing", () => {
  it("sends everything pending and marks it synced", async () => {
    await enqueue("set_logged", set("ex-1", 10));
    await enqueue("set_logged", set("ex-1", 11));
    const post = vi.fn().mockResolvedValue({ stored: 2 });

    const result = await flush(post);

    expect(result).toEqual({ attempted: 2, stored: 2 });
    expect(await pending()).toHaveLength(0);
  });

  it("never sends the local-only bookkeeping field", async () => {
    await enqueue("set_logged", set("ex-1", 10));
    const post = vi.fn().mockResolvedValue({ stored: 1 });
    await flush(post);
    expect(post.mock.calls[0]![0][0]).not.toHaveProperty("synced_at");
  });

  it("keeps events when the request fails, so nothing is lost", async () => {
    await enqueue("set_logged", set("ex-1", 10));
    const post = vi.fn().mockRejectedValue(new Error("offline"));

    await expect(flush(post)).rejects.toThrow("offline");
    expect(await pending()).toHaveLength(1);
  });

  it("re-sends after a crash mid-flush rather than losing the batch", async () => {
    // A request that timed out after the server committed costs a duplicate send and
    // nothing else, because the server upserts on the client-generated id.
    await enqueue("set_logged", set("ex-1", 10));
    const flaky = vi
      .fn()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValue({ stored: 1 });

    await expect(flush(flaky)).rejects.toThrow();
    expect(await pending()).toHaveLength(1);

    const second = await flush(flaky);
    expect(second.attempted).toBe(1);
    expect(await pending()).toHaveLength(0);
  });

  it("sends the same id both times, so the server can dedupe", async () => {
    const logged = await enqueue("set_logged", set("ex-1", 10));
    const seen: string[] = [];
    const post = vi.fn(async (events: unknown[]) => {
      seen.push((events[0] as { id: string }).id);
      throw new Error("offline");
    });
    await expect(flush(post)).rejects.toThrow();

    const ok = vi.fn(async (events: unknown[]) => {
      seen.push((events[0] as { id: string }).id);
      return { stored: 1 };
    });
    await flush(ok);

    expect(seen).toEqual([logged.id, logged.id]);
    expect(seen[0]).toBe(logged.id);
  });

  it("batches a long session rather than one enormous request", async () => {
    for (let i = 0; i < 120; i++) await enqueue("set_logged", set("ex-1", 10));
    const post = vi.fn().mockResolvedValue({ stored: 50 });
    await flush(post);
    expect(post).toHaveBeenCalledTimes(3);
  });

  it("does nothing when the queue is empty", async () => {
    const post = vi.fn();
    expect(await flush(post)).toEqual({ attempted: 0, stored: 0 });
    expect(post).not.toHaveBeenCalled();
  });

  it("leaves already-synced events alone", async () => {
    const logged = await enqueue("set_logged", set("ex-1", 10));
    await markSynced([logged.id]);
    const post = vi.fn();
    await flush(post);
    expect(post).not.toHaveBeenCalled();
  });
});
