import { describe, expect, it } from "vitest";
import { bmi, bmiFromProfile } from "../bmi";

describe("bmi", () => {
  it("computes mass over height squared", () => {
    // 80kg at 1.80m = 24.7
    expect(bmi(80, 180)?.value).toBe(24.7);
    expect(bmi(62, 165)?.value).toBe(22.8);
  });

  it("bands at the WHO thresholds, on the correct side of each boundary", () => {
    expect(bmi(59, 180)?.band).toBe("under"); // 18.2
    expect(bmi(60, 180)?.band).toBe("healthy"); // 18.5, the first healthy value
    expect(bmi(81, 180)?.band).toBe("over"); // 25.0, the first overweight value
    expect(bmi(97.2, 180)?.band).toBe("obese"); // 30.0, the first obese value
  });

  it("bands the figure it displays, so the number and the label never disagree", () => {
    // 18.487 rounds to the 18.5 shown on screen, and 18.5 is a healthy reading.
    // Banding the unrounded value would print "18.5 · Underweight range".
    const edge = bmi(59.9, 180)!;
    expect(edge.value).toBe(18.5);
    expect(edge.band).toBe("healthy");
  });

  it("is null until both measurements are there", () => {
    expect(bmi(80, null)).toBeNull();
    expect(bmi(null, 180)).toBeNull();
    expect(bmi(null, null)).toBeNull();
  });

  it("refuses nonsense rather than returning Infinity", () => {
    expect(bmi(80, 0)).toBeNull();
    expect(bmi(0, 180)).toBeNull();
    expect(bmi(Number.NaN, 180)).toBeNull();
  });

  it("reads the decimal strings the API returns for bodyweight", () => {
    expect(bmiFromProfile({ bodyweight_kg: "80.00", height_cm: 180 })?.value).toBe(24.7);
    expect(bmiFromProfile({ bodyweight_kg: null, height_cm: 180 })).toBeNull();
    expect(bmiFromProfile({})).toBeNull();
  });

  it("puts a muscular lifter in the overweight band, which is the caveat's whole point", () => {
    // 95kg at 1.80m: lean and strong reads 29.3. The band is wrong about this person,
    // which is why the UI ships the explanation next to the number.
    expect(bmi(95, 180)?.band).toBe("over");
  });
});
