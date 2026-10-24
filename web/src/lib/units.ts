/**
 * Imperial is a display concern and never reaches the server.
 *
 * Everything is stored and computed metric — the API's `bodyweight_kg` and `height_cm`,
 * and the engine's loads. A unit that round-trips through the database is a unit that
 * eventually round-trips wrong, so conversion happens at the edge of the form and
 * nowhere else.
 */
export type Units = "metric" | "imperial";

const KEY = "loadout.units";
const LB_PER_KG = 2.2046226218;
const CM_PER_IN = 2.54;

export function readUnits(): Units {
  if (typeof window === "undefined") return "metric";
  return window.localStorage.getItem(KEY) === "imperial" ? "imperial" : "metric";
}

export function writeUnits(units: Units): void {
  window.localStorage.setItem(KEY, units);
}

export const kgToLb = (kg: number): number => Math.round(kg * LB_PER_KG);
export const lbToKg = (lb: number): number => Number((lb / LB_PER_KG).toFixed(2));

/** Centimetres to whole feet and inches, with the inches carried properly at 12. */
export function cmToFtIn(cm: number): { ft: number; in: number } {
  const total = Math.round(cm / CM_PER_IN);
  const ft = Math.floor(total / 12);
  return { ft, in: total - ft * 12 };
}

export const ftInToCm = (ft: number, inches: number): number =>
  Math.round((ft * 12 + inches) * CM_PER_IN);

/** A load as the user reads it. Loads arrive from the API as decimal strings. */
export function displayLoad(kg: string | number | null, units: Units): string | null {
  if (kg === null || kg === "") return null;
  const value = typeof kg === "string" ? Number(kg) : kg;
  if (!Number.isFinite(value)) return null;
  return units === "imperial" ? `${kgToLb(value)} lb` : `${trim(value)} kg`;
}

/** 60 rather than 60.00, but 62.5 kept — plate math produces real halves. */
const trim = (n: number): string => String(Number(n.toFixed(2)));
