import { beforeEach, describe, expect, it } from "vitest";
import { db } from "../db";
import {
  closeSession,
  discard,
  enqueue,
  loggedSets,
  markSynced,
  sessionOutcome,
} from "../queue";
import { localDay } from "../day";
import { sessionDates } from "../plan";

beforeEach(async () => {
  await db.events.clear();
});

describe("reading the queue back", () => {
  it("carries the exercise name on the event, so history reads without a catalog", async () => {
    await enqueue("set_logged", { exercise_id: "x", slug: "bodyweight_squat", reps: 12, rir: 3 });
    expect((await loggedSets())[0]!.slug).toBe("bodyweight_squat");
  });

  it("dates a set by the user's own day, not by UTC", async () => {
    // 23:30 local on the 30th is already the 31st in UTC for anyone east of Greenwich,
    // and still the 30th here. Constraint 6 says the user's calendar wins.
    const late = new Date(2026, 7, 30, 23, 30);
    await enqueue("set_logged", { exercise_id: "x", reps: 5, rir: 2 }, late);
    expect((await loggedSets())[0]!.day).toBe("2026-08-30");
  });
});

describe("undo", () => {
  it("drops a set that never left this device", async () => {
    const event = await enqueue("set_logged", { exercise_id: "x", reps: 5, rir: 2 });
    await discard(event.id);
    expect(await loggedSets()).toHaveLength(0);
  });

  it("refuses to drop one the server already has", async () => {
    // The server log is append-only (constraint 2). Deleting the local copy would hide
    // a set that still exists upstream, which is worse than refusing.
    const event = await enqueue("set_logged", { exercise_id: "x", reps: 5, rir: 2 });
    await markSynced([event.id]);
    await expect(discard(event.id)).rejects.toThrow(/already synced/);
    expect(await loggedSets()).toHaveLength(1);
  });
});

describe("closing out a session", () => {
  it("has no outcome until the day is closed", async () => {
    expect(await sessionOutcome(localDay())).toBeNull();
  });

  it("records what the fatigue gate needs: the day and the sets managed", async () => {
    await closeSession("2026-08-30", "abandoned", 4);
    const [event] = await db.events.toArray();
    expect(event!.type).toBe("workout_abandoned");
    expect(event!.payload).toMatchObject({ day: "2026-08-30", sets_completed: 4 });
    expect(await sessionOutcome("2026-08-30")).toBe("abandoned");
  });

  it("keeps one day's outcome out of another's", async () => {
    await closeSession("2026-08-30", "completed", 12);
    expect(await sessionOutcome("2026-08-31")).toBeNull();
  });
});

describe("session dates", () => {
  it("keeps every day inside one ISO week, which the API requires", () => {
    for (let n = 1; n <= 7; n++) {
      const days = sessionDates(n, new Date(2026, 7, 27));
      expect(days).toHaveLength(n);
      expect(new Set(days).size).toBe(n);
      const weeks = new Set(days.map((d) => isoWeek(d)));
      expect(weeks.size).toBe(1);
    }
  });

  it("rolls to next week when the whole spread is already behind us", () => {
    // Sunday. Mon/Wed/Fri of this week have all been and gone, and a first plan whose
    // every session is in the past is nothing a new user can act on.
    const sunday = new Date(2026, 7, 30);
    const days = sessionDates(3, sunday);
    expect(days.every((d) => d > "2026-08-30")).toBe(true);
    expect(days[0]).toBe("2026-08-31");
  });

  it("leaves the common case alone", () => {
    // Tuesday: Wednesday and Friday are still ahead, so this week stands.
    expect(sessionDates(3, new Date(2026, 7, 25))[0]).toBe("2026-08-24");
  });

  it("spreads three sessions rather than packing them together", () => {
    const days = sessionDates(3, new Date(2026, 7, 27)).map((d) => new Date(d).getUTCDay());
    // Mon, Wed, Fri — never two in a row, so the fatigue gate keeps its options.
    expect(days).toEqual([1, 3, 5]);
  });
});

function isoWeek(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const start = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d.getTime() - start.getTime()) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-${week}`;
}
