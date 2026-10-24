import { describe, expect, it } from "vitest";
import type { LoggedSet } from "../queue";
import { e1rm, summarise } from "../summary";

let n = 0;
const set = (
  day: string,
  time: string,
  reps: number,
  load: string | null,
  exerciseId = "a",
): LoggedSet => ({
  id: String(n++),
  exerciseId,
  slug: exerciseId === "a" ? "goblet_squat" : "push_up",
  reps,
  rir: 2,
  load,
  at: `${day}T${time}:00Z`,
  day,
  synced: false,
});

describe("e1rm", () => {
  it("is Epley", () => {
    expect(e1rm(100, 10)).toBeCloseTo(133.33, 2);
  });
});

describe("summarise", () => {
  it("totals one day only", () => {
    const s = summarise(
      [set("2026-10-24", "10:00", 10, "20"), set("2026-10-24", "10:12", 8, "20"), set("2026-10-22", "09:00", 10, "20")],
      "2026-10-24",
    );
    expect(s).toMatchObject({ sets: 2, reps: 18, volumeKg: 360, minutes: 12 });
    expect(s.exercises).toHaveLength(1);
    expect(s.exercises[0]!.name).toBe("goblet squat");
  });

  it("flags a PR only when there is an earlier best to beat", () => {
    const first = summarise([set("2026-10-24", "10:00", 10, "20")], "2026-10-24");
    expect(first.exercises[0]!.isPr).toBe(false);

    const beaten = summarise(
      [set("2026-10-22", "10:00", 10, "20"), set("2026-10-24", "10:00", 10, "22.5")],
      "2026-10-24",
    );
    expect(beaten.exercises[0]).toMatchObject({ isPr: true });
    expect(beaten.exercises[0]!.previous).toBeCloseTo(e1rm(20, 10));
  });

  it("does not call a matched best a PR", () => {
    const s = summarise(
      [set("2026-10-22", "10:00", 10, "20"), set("2026-10-24", "10:00", 10, "20")],
      "2026-10-24",
    );
    expect(s.exercises[0]!.isPr).toBe(false);
  });

  it("leaves bodyweight work out of e1RM and volume", () => {
    const s = summarise([set("2026-10-24", "10:00", 15, null, "b")], "2026-10-24");
    expect(s).toMatchObject({ volumeKg: 0, minutes: null });
    expect(s.exercises[0]).toMatchObject({ best: null, isPr: false });
  });
});
