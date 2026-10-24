"use client";

import Link from "next/link";
import type { Bmi } from "@/lib/bmi";
import { displayLoad, type Units } from "@/lib/units";
import { cn } from "./ui/cn";

/**
 * Bodyweight and BMI, stated rather than judged.
 *
 * Deliberately not the hero-metric treatment — no giant number, no accent, no progress
 * ring. It is one reference figure on a screen whose job is this week's training, and
 * giving it more weight than the sessions would be giving it more weight than it has.
 *
 * The caveat is not decoration. BMI does not distinguish muscle from fat, and the people
 * using a strength training app are the ones it misreads most: a lean lifter lands in
 * "overweight" routinely. Showing the band without saying so would be the app asserting
 * something it has no grounds for.
 */
export function BodyMetrics({
  bmi,
  bodyweightKg,
  units,
  className,
}: {
  bmi: Bmi;
  bodyweightKg: number | null;
  units: Units;
  className?: string;
}) {
  const weight = displayLoad(bodyweightKg, units);
  return (
    <section
      className={cn("rounded-card bg-surface px-4 py-3.5", className)}
      aria-label="Body measurements"
    >
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <Figure label="BMI" value={bmi.value.toFixed(1)} note={bmi.label} />
        {weight && <Figure label="Bodyweight" value={weight} />}
      </div>
      <p className="mt-2.5 text-2xs leading-relaxed text-ink-faint">
        BMI is weight over height squared and says nothing about what that weight is
        made of. It reads high for trained lifters. Treat it as a reference figure, not
        a target —{" "}
        <Link href="/settings" className="underline underline-offset-2 hover:text-ink-muted">
          update your measurements
        </Link>
        .
      </p>
    </section>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <p className="flex items-baseline gap-2">
      <span className="label">{label}</span>
      <span className="font-display text-[1.5rem] leading-none font-extrabold text-ink">{value}</span>
      {note && <span className="text-[0.8125rem] text-ink-faint">{note}</span>}
    </p>
  );
}
