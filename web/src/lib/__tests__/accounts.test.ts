import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { db } from "../db";
import { enqueue, loggedSets, pending, restore } from "../queue";

/** A token whose payload names `sub`. Unsigned: the client never verifies it. */
const tokenFor = (sub: string) => `h.${btoa(JSON.stringify({ sub })).replace(/=+$/, "")}.s`;

function signIn(sub: string | null) {
  const store = new Map<string, string>();
  if (sub !== null) store.set("loadout.token", tokenFor(sub));
  vi.stubGlobal("window", { localStorage: { getItem: (k: string) => store.get(k) ?? null } });
}

beforeEach(async () => {
  await db.events.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const set = { exercise_id: "e", reps: 10, rir: 2, load: "20" };

describe("one device, two accounts", () => {
  it("shows and sends only the signed-in account's events", async () => {
    signIn("alice");
    await enqueue("set_logged", set);
    signIn("bob");
    await enqueue("set_logged", set);

    expect(await loggedSets()).toHaveLength(1);
    expect((await pending()).map((e) => e.user)).toEqual(["bob"]);

    signIn("alice");
    expect((await pending()).map((e) => e.user)).toEqual(["alice"]);
  });

  it("keeps events from before accounts were tracked visible", async () => {
    await db.events.add({
      id: "old", type: "set_logged", payload: set, client_ts: "2026-10-01T10:00:00.000Z",
      user_tz: "UTC", synced_at: null,
    });
    signIn("alice");
    expect(await pending()).toHaveLength(1);
  });
});

describe("restoring a device", () => {
  const remote = [
    {
      id: "r1", type: "set_logged" as const, payload: set,
      client_ts: "2026-10-20T10:00:00+00:00", user_tz: "UTC",
      server_ts: "2026-10-20T10:00:05+00:00",
    },
  ];

  it("brings the server log in as synced, under the signed-in account", async () => {
    signIn("carol");
    expect(await restore(async () => remote)).toBe(1);
    const row = await db.events.get("r1");
    expect(row).toMatchObject({ user: "carol", synced_at: "2026-10-20T10:00:05+00:00" });
    expect(row?.client_ts).toBe("2026-10-20T10:00:00.000Z");
    expect(await pending()).toHaveLength(0);
    expect(await loggedSets()).toHaveLength(1);
  });

  it("leaves sets still waiting on the device alone", async () => {
    signIn("dave");
    const waiting = await enqueue("set_logged", set);
    await restore(async () => remote);
    expect((await pending()).map((e) => e.id)).toEqual([waiting.id]);
  });

  it("runs once per account per load", async () => {
    signIn("erin");
    const fetchAll = vi.fn(async () => remote);
    await restore(fetchAll);
    await restore(fetchAll);
    expect(fetchAll).toHaveBeenCalledTimes(1);
  });

  it("does nothing signed out", async () => {
    signIn(null);
    const fetchAll = vi.fn(async () => remote);
    expect(await restore(fetchAll)).toBe(0);
    expect(fetchAll).not.toHaveBeenCalled();
  });
});
