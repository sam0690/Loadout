import { describe, expect, it } from "vitest";
import type { LoggedSet } from "../queue";
import { applySwaps, deltaVsLast, type Item } from "../workout";

const set = (day: string, reps: number, load: string | null, exerciseId = "a"): LoggedSet => ({
  id: `${day}-${reps}-${load}`,
  exerciseId,
  slug: null,
  reps,
  rir: 2,
  load,
  at: `${day}T10:00:00Z`,
  day,
  synced: true,
});

const item = (load: string | null) => ({ exercise_id: "a", load, target_reps: 10 });

describe("deltaVsLast", () => {
  it("says so when there is no earlier session", () => {
    expect(deltaVsLast(item("20"), [set("2026-10-24", 10, "20")], "2026-10-24", "metric").direction)
      .toBe("first");
  });

  it("reports a load increase against the heaviest set last time", () => {
    const sets = [set("2026-10-22", 10, "30"), set("2026-10-22", 12, "32.5")];
    expect(deltaVsLast(item("35"), sets, "2026-10-24", "metric")).toEqual({
      direction: "up",
      text: "▲ 2.5 kg vs last time",
    });
  });

  it("uses only the most recent earlier day", () => {
    const sets = [set("2026-10-22", 10, "30"), set("2026-10-20", 10, "40")];
    expect(deltaVsLast(item("27.5"), sets, "2026-10-24", "metric").text).toBe(
      "▼ 2.5 kg vs last time",
    );
  });

  it("asks for more reps at the same load", () => {
    const sets = [set("2026-10-22", 9, "30"), set("2026-10-22", 11, "30")];
    expect(deltaVsLast(item("30"), sets, "2026-10-24", "metric").text).toBe(
      "Same load — beat 11 reps",
    );
  });

  it("falls back to reps for bodyweight work", () => {
    const sets = [set("2026-10-22", 14, null)];
    expect(deltaVsLast(item(null), sets, "2026-10-24", "metric").text).toBe(
      "Last time: best set 14 reps",
    );
  });

  it("ignores other exercises", () => {
    const sets = [set("2026-10-22", 10, "30", "b")];
    expect(deltaVsLast(item("30"), sets, "2026-10-24", "metric").direction).toBe("first");
  });
});

describe("applySwaps", () => {
  const base = {
    movement_pattern: "squat",
    primary_muscle: "quads",
    sets: 3,
    target_reps: 10,
    target_rir: 2,
    load: "20",
  };
  const items = [
    { ...base, exercise_id: "a", slug: "goblet_squat", substitutes: [{ exercise_id: "s", slug: "split_squat", equipment: [] }] },
    { ...base, exercise_id: "b", slug: "row", substitutes: [] },
  ] as unknown as Item[];

  it("replaces the swapped slot and keeps its prescription", () => {
    const out = applySwaps(items, new Map([["a", "s"]]));
    expect(out[0]).toMatchObject({ exercise_id: "s", slug: "split_squat", sets: 3, load: "20", substitutes: [] });
    expect(out[1]).toBe(items[1]);
  });

  it("ignores a swap to something that is not a listed substitute", () => {
    expect(applySwaps(items, new Map([["a", "zzz"]]))[0]).toBe(items[0]);
  });
});
