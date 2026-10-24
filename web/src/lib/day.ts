/**
 * Calendar days in the user's own zone.
 *
 * Constraint 6: events are stored UTC plus an IANA zone, and "did I train today" is a
 * question about the user's local calendar, not about UTC. Slicing an ISO string gets
 * this wrong for everyone who is not on UTC — a set logged at 8pm in New York lands on
 * tomorrow's date — so the conversion happens here and only here.
 */
export function localDay(at: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${p(at.getMonth() + 1)}-${p(at.getDate())}`;
}

/** Parse a YYYY-MM-DD back into a local Date. `new Date("2026-08-30")` parses as UTC
 * midnight and renders as the previous day for anyone west of Greenwich. */
export function fromDay(day: string): Date | null {
  const [y, m, d] = day.split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d) : null;
}
