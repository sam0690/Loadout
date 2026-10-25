import { describe, expect, it } from "vitest";
import type { LoggedSet } from "../queue";
import { records, trends } from "../progress";
import { e1rm } from "../summary";

let n = 0;
const set = (exerciseId: string, day: string, reps: number, load: string | null): LoggedSet => ({
  id: String(n++),
  exerciseId,
  slug: `${exerciseId}_lift`,
  reps,
  rir: 2,
  load,
  at: `${day}T10:00:00Z`,
  day,
  synced: true,
});

describe("trends", () => {
  it("keeps the best e1RM per day, in date order", () => {
    const [t] = trends([
      set("a", "2026-10-24", 10, "32.5"),
      set("a", "2026-10-22", 10, "30"),
      set("a", "2026-10-22", 5, "35"),
    ]);
    expect(t!.kind).toBe("e1rm");
    expect(t!.points.map((p) => p.day)).toEqual(["2026-10-22", "2026-10-24"]);
    expect(t!.points[0]!.value).toBeCloseTo(Math.max(e1rm(30, 10), e1rm(35, 5)));
    expect(t!.name).toBe("a lift");
  });

  it("tracks the record and the change since the first session", () => {
    const [t] = trends([
      set("a", "2026-10-20", 10, "30"),
      set("a", "2026-10-22", 10, "40"),
      set("a", "2026-10-24", 10, "35"),
    ]);
    expect(t!.record.day).toBe("2026-10-22");
    expect(t!.change).toBeCloseTo(e1rm(35, 10) - e1rm(30, 10));
  });

  it("uses best reps for bodyweight work", () => {
    const [t] = trends([set("b", "2026-10-20", 12, null), set("b", "2026-10-24", 15, null)]);
    expect(t).toMatchObject({ kind: "reps", change: 3, record: { value: 15 } });
  });

  it("leaves bodyweight sets of a loaded exercise out of the e1RM line", () => {
    const [t] = trends([set("a", "2026-10-20", 10, "30"), set("a", "2026-10-22", 20, null)]);
    expect(t!.points).toHaveLength(1);
  });

  it("puts the most recently trained exercise first", () => {
    const out = trends([set("a", "2026-10-20", 10, "30"), set("b", "2026-10-24", 10, null)]);
    expect(out.map((t) => t.exerciseId)).toEqual(["b", "a"]);
  });
});

describe("records", () => {
  it("counts days that beat every earlier day, never the first, never bodyweight", () => {
    const t = trends([
      set("a", "2026-10-01", 5, "100"),
      set("a", "2026-10-03", 5, "105"), // record
      set("a", "2026-10-05", 5, "102.5"),
      set("a", "2026-10-07", 5, "110"), // record
      set("b", "2026-10-01", 5, "50"),
      set("c", "2026-10-01", 10, null),
      set("c", "2026-10-03", 15, null),
    ]);
    expect(records(t)).toBe(2);
  });
});
