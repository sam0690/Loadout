import { describe, expect, it } from "vitest";
import { cmToFtIn, displayLoad, ftInToCm, kgToLb, lbToKg } from "../units";

/**
 * Imperial never reaches the server, so the only thing that matters is that a value
 * survives the trip out to the form and back without drifting.
 */
describe("unit conversion", () => {
  it("round-trips a bodyweight through pounds without drifting", () => {
    for (const kg of [50, 62.5, 80, 97.7, 140]) {
      expect(Math.abs(lbToKg(kgToLb(kg)) - kg)).toBeLessThan(0.5);
    }
  });

  it("carries inches at twelve rather than reporting 5ft 12in", () => {
    const tall = cmToFtIn(182.88); // exactly 6ft
    expect(tall).toEqual({ ft: 6, in: 0 });
    expect(cmToFtIn(180).in).toBeLessThan(12);
  });

  it("round-trips a height through feet and inches", () => {
    for (const cm of [150, 165, 178, 191, 203]) {
      const { ft, in: inches } = cmToFtIn(cm);
      expect(Math.abs(ftInToCm(ft, inches) - cm)).toBeLessThanOrEqual(2);
    }
  });
});

describe("displayLoad", () => {
  it("reads loads that arrive from the API as decimal strings", () => {
    expect(displayLoad("62.50", "metric")).toBe("62.5 kg");
    expect(displayLoad("60.00", "metric")).toBe("60 kg");
  });

  it("keeps real half-plates rather than rounding them away", () => {
    expect(displayLoad(62.5, "metric")).toBe("62.5 kg");
  });

  it("has nothing to show for a bodyweight exercise", () => {
    expect(displayLoad(null, "metric")).toBeNull();
    expect(displayLoad("", "imperial")).toBeNull();
  });

  it("converts for display only", () => {
    expect(displayLoad("100", "imperial")).toBe("220 lb");
  });
});
