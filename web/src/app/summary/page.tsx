"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { loggedSets, sessionOutcome, type Outcome } from "@/lib/queue";
import { summarise, type Summary } from "@/lib/summary";
import { displayLoad, readUnits } from "@/lib/units";
import { localDay } from "@/lib/day";
import { Button } from "@/components/ui/Button";
import { formatDay } from "@/components/Session";

/**
 * The end of a workout: what got done, and anything that beat the user's best.
 *
 * Built from the sets on this device, so it renders in the same basement the workout
 * happened in. Deliberately silent on what changes next time -- that is the engine's
 * decision, and guessing it here would be the client inventing a prescription.
 */
export default function SummaryPage() {
  return (
    <Suspense>
      <SessionSummary />
    </Suspense>
  );
}

function SessionSummary() {
  const day = useSearchParams().get("day") ?? localDay();
  const router = useRouter();
  const units = readUnits();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    void loggedSets().then((sets) => setSummary(summarise(sets, day)));
    void sessionOutcome(day).then(setOutcome);
  }, [day]);

  if (summary === null) {
    return (
      <main className="mx-auto min-h-dvh max-w-md px-5 pt-16">
        <div className="h-24 w-1/2 animate-pulse rounded-control bg-surface" />
      </main>
    );
  }

  const prs = summary.exercises.filter((e) => e.isPr);
  const status =
    outcome === "completed" ? "Session complete" : outcome === "abandoned" ? "Ended early" : "Logged";

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col px-5 pt-10 pb-6">
      <p className="label">
        <span className="text-accent">{status}</span>
        <span className="ml-2">{formatDay(day, { weekday: "short", day: "numeric", month: "short" })}</span>
      </p>

      {summary.sets === 0 ? (
        <h1 className="mt-3 text-display text-ink">Nothing logged</h1>
      ) : (
        <>
          <h1 className="mt-2 flex items-baseline gap-3 text-ink">
            <span className="font-display text-hero font-extrabold text-accent">{summary.sets}</span>
            <span className="text-display">{summary.sets === 1 ? "set" : "sets"}</span>
          </h1>

          <dl className="mt-6 grid grid-cols-3 gap-2">
            <Stat label="Volume" value={summary.volumeKg > 0 ? displayLoad(summary.volumeKg, units)! : "—"} />
            <Stat label="Reps" value={String(summary.reps)} />
            <Stat label="Time" value={summary.minutes === null ? "—" : `${summary.minutes} min`} />
          </dl>

          {prs.length > 0 && (
            <section className="mt-8">
              <h2 className="label mb-3">Personal bests</h2>
              <ul className="space-y-2">
                {prs.map((e) => (
                  <li key={e.exerciseId} className="rounded-card bg-accent px-4 py-3 text-accent-ink">
                    <p className="font-display text-[1.25rem] leading-tight font-extrabold uppercase">
                      ▲ {e.name}
                    </p>
                    <p className="mt-0.5 text-[0.875rem] text-accent-ink/80">
                      Est. 1RM {displayLoad(round(e.best!), units)}, up{" "}
                      {displayLoad(round(e.best! - e.previous!), units)}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="mt-8">
            <h2 className="label mb-3">Exercises</h2>
            <ul className="space-y-2">
              {summary.exercises.map((e) => (
                <li key={e.exerciseId} className="rounded-card bg-surface px-4 py-3">
                  <p className="text-[0.9375rem] font-medium text-ink capitalize">{e.name}</p>
                  <p className="mt-1.5 flex flex-wrap gap-1.5">
                    {e.sets.map((s) => (
                      <span
                        key={s.id}
                        className="rounded-full bg-raised px-2.5 py-0.5 font-display text-[1rem] font-semibold text-ink-muted"
                      >
                        {s.reps}
                        {s.load ? ` × ${displayLoad(s.load, units)}` : " reps"}
                      </span>
                    ))}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      <div className="mt-auto pt-10">
        <Button variant="primary" full onClick={() => router.push("/today")}>
          Done
        </Button>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-control bg-surface px-3 py-3">
      <dt className="label">{label}</dt>
      <dd className="mt-1 font-display text-[1.5rem] leading-none font-extrabold text-ink">{value}</dd>
    </div>
  );
}

/** To the nearest 0.5: an estimate shown to two decimals claims precision it lacks. */
const round = (n: number): number => Math.round(n * 2) / 2;
