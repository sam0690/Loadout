import { describe, expect, it } from "vitest";
import { analyse, isHard, weekStart } from "../analysis";
import type { LoggedSet } from "../queue";
import type { PlanPayload } from "../api/client";

const set = (over: Partial<LoggedSet>): LoggedSet => ({
  id: Math.random().toString(36),
  exerciseId: "squat",
  slug: "back_squat",
  reps: 10,
  rir: 2,
  load: null,
  at: "2026-08-24T10:00:00.000Z",
  day: "2026-08-24",
  synced: true,
  ...over,
});

const plan = (): PlanPayload => ({
  sessions: [
    {
      day: "2026-08-24",
      items: [
        item("squat", "quads", 3, 2),
        item("row", "back", 2, 2),
      ],
    },
    { day: "2026-08-26", items: [item("press", "chest", 3, 2)] },
  ],
});

function item(id: string, muscle: string, sets: number, rir: number) {
  return {
    exercise_id: id,
    slug: id,
    movement_pattern: "squat",
    primary_muscle: muscle,
    sets,
    target_reps: 10,
    target_rir: rir,
    load: null,
    substitutes: [],
  };
}

describe("hard sets", () => {
  it("counts RIR 3 and below, per D7", () => {
    expect(isHard(set({ rir: 0 }))).toBe(true);
    expect(isHard(set({ rir: 3 }))).toBe(true);
    expect(isHard(set({ rir: 4 }))).toBe(false);
  });
});

describe("weekStart", () => {
  it("snaps any day to that week's Monday", () => {
    expect(weekStart("2026-08-24")).toBe("2026-08-24"); // a Monday
    expect(weekStart("2026-08-27")).toBe("2026-08-24");
    expect(weekStart("2026-08-30")).toBe("2026-08-24"); // Sunday belongs to it
    expect(weekStart("2026-08-31")).toBe("2026-08-31"); // the next Monday
  });
});

describe("analyse", () => {
  it("counts what was logged against what was prescribed", () => {
    const a = analyse(
      [set({}), set({}), set({ exerciseId: "row" })],
      plan(),
      "2026-08-26",
    );
    expect(a.done).toBe(3);
    expect(a.prescribed).toBe(8); // 3 + 2 + 3
    expect(a.sessionsTouched).toBe(1);
    expect(a.sessionsPlanned).toBe(2);
  });

  it("credits the primary muscle the plan named", () => {
    const a = analyse([set({}), set({ exerciseId: "row" })], plan(), "2026-08-26");
    const quads = a.muscles.find((m) => m.muscle === "quads")!;
    expect(quads).toMatchObject({ done: 1, prescribed: 3 });
    expect(a.muscles.find((m) => m.muscle === "back")).toMatchObject({
      done: 1,
      prescribed: 2,
    });
  });

  it("leaves easy sets out of the hard-set breakdown", () => {
    const a = analyse([set({ rir: 5 }), set({ rir: 1 })], plan(), "2026-08-26");
    expect(a.muscles.find((m) => m.muscle === "quads")!.done).toBe(1);
    // Still a set that happened, so the week's total keeps it.
    expect(a.done).toBe(2);
  });

  it("ignores work from a different week entirely", () => {
    const a = analyse([set({ day: "2026-07-01" })], plan(), "2026-08-26");
    expect(a.done).toBe(0);
    expect(a.muscles.every((m) => m.done === 0)).toBe(true);
  });

  it("counts a session moved to an unplanned day of the same week", () => {
    // The plan says Monday and Wednesday; this was done on the Tuesday. The work
    // happened, so the week's adherence has to reflect it.
    const a = analyse([set({ day: "2026-08-25" })], plan(), "2026-08-26");
    expect(a.done).toBe(1);
    expect(a.muscles.find((m) => m.muscle === "quads")!.done).toBe(1);
    expect(a.sessionsTouched).toBe(1);
  });

  it("counts a set whose exercise the plan no longer lists, without a muscle for it", () => {
    const a = analyse([set({ exerciseId: "gone" })], plan(), "2026-08-26");
    expect(a.done).toBe(1);
    expect(a.muscles.every((m) => m.done === 0)).toBe(true);
  });

  it("always returns a full trend window, so a quiet week is a gap not a hole", () => {
    const a = analyse([set({})], plan(), "2026-08-26");
    expect(a.weeks).toHaveLength(6);
    expect(a.weeks[a.weeks.length - 1]!.weekStart).toBe("2026-08-24");
    expect(a.weeks[a.weeks.length - 1]!.hardSets).toBe(1);
    expect(a.weeks[0]!.hardSets).toBe(0);
  });

  it("keeps tonnage at zero for a bodyweight week rather than inventing a number", () => {
    const a = analyse([set({}), set({})], plan(), "2026-08-26");
    expect(a.weeks.at(-1)!.tonnageKg).toBe(0);
    expect(a.weeks.at(-1)!.hardSets).toBe(2);
  });

  it("multiplies load by reps for anyone actually lifting something", () => {
    const a = analyse([set({ load: "60", reps: 5 })], plan(), "2026-08-26");
    expect(a.weeks.at(-1)!.tonnageKg).toBe(300);
  });

  it("says it has nothing rather than drawing an empty panel", () => {
    expect(analyse([], plan(), "2026-08-26").hasData).toBe(false);
  });
});
