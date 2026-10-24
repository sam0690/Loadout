/**
 * Body mass index, from the height and bodyweight collected at intake (D29).
 *
 * Worth stating plainly, because it decides how this is presented: BMI is mass over
 * height squared and has no term for body composition. Muscle is denser than fat, so a
 * lean trained lifter routinely lands in "overweight" — and the users of a strength
 * training app are exactly the population the index misreads. The number is real
 * arithmetic; the band is a population statistic being applied to an individual it does
 * not fit well.
 *
 * So the UI shows the figure with that caveat attached, and never as a target. Nothing
 * in `engine/` reads it and nothing should: prescriptions come from logged performance,
 * not from a ratio of two numbers a user typed in once.
 */
export type Band = "under" | "healthy" | "over" | "obese";

export interface Bmi {
  value: number;
  band: Band;
  label: string;
}

export const BAND_LABEL: Record<Band, string> = {
  under: "Underweight range",
  healthy: "Healthy range",
  over: "Overweight range",
  obese: "Obese range",
};

/** Null unless both measurements are present and sane — no half-answer arithmetic. */
export function bmi(bodyweightKg: number | null, heightCm: number | null): Bmi | null {
  if (bodyweightKg === null || heightCm === null) return null;
  if (!Number.isFinite(bodyweightKg) || !Number.isFinite(heightCm)) return null;
  if (bodyweightKg <= 0 || heightCm <= 0) return null;

  const metres = heightCm / 100;
  const value = Math.round((bodyweightKg / (metres * metres)) * 10) / 10;
  const band = bandFor(value);
  return { value, band, label: BAND_LABEL[band] };
}

function bandFor(value: number): Band {
  if (value < 18.5) return "under";
  if (value < 25) return "healthy";
  if (value < 30) return "over";
  return "obese";
}

/** Accepts the decimal strings the API returns for bodyweight. */
export function bmiFromProfile(profile: {
  bodyweight_kg?: number | string | null;
  height_cm?: number | null;
}): Bmi | null {
  const kg =
    profile.bodyweight_kg == null ? null : Number(profile.bodyweight_kg);
  return bmi(kg, profile.height_cm ?? null);
}
