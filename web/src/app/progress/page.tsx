"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { loggedSets, type LoggedSet } from "@/lib/queue";
import { cachedPlan } from "@/lib/plan";
import { analyse } from "@/lib/analysis";
import { bmiFromProfile } from "@/lib/bmi";
import { cachedProfile, refreshProfile } from "@/lib/profile";
import type { Profile } from "@/lib/api/client";
import { trends } from "@/lib/progress";
import { Analysis } from "@/components/Analysis";
import { Strength } from "@/components/Strength";
import { BodyMetrics } from "@/components/BodyMetrics";
import { fromDay, localDay } from "@/lib/day";
import { displayLoad, readUnits, type Units } from "@/lib/units";
import { AppShell, PageHeader } from "@/components/AppShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { RowSkeleton } from "@/components/ui/Skeleton";
import { HistoryIcon } from "@/components/ui/icons";

/**
 * The numbers: this week against the plan, the trend, the body, then every set.
 *
 * Everything logged on this device, newest first.
 *
 * Reads the local queue rather than the server: history has to work offline too, and
 * the queue already holds every set including the ones not yet sent.
 *
 * It used to render one line per day — "3 sets" — while the queue held the reps, the
 * RIR and the load for every one of them. Showing the work is the point: this is the
 * only screen where a user can see that they are actually getting stronger.
 */
interface Day {
  day: string;
  sets: LoggedSet[];
  byExercise: { name: string; sets: LoggedSet[] }[];
  unsynced: number;
}

/** Sessions shown before "Show older": the strength cards already carry the long view. */
const RECENT = 7;

export default function Progress() {
  const [sets, setSets] = useState<LoggedSet[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(cachedProfile);
  const [older, setOlder] = useState(false);
  const units = readUnits();

  useEffect(() => {
    void loggedSets().then(setSets);
    void refreshProfile().then(setProfile);
  }, []);

  const days = useMemo(() => (sets === null ? null : group(sets)), [sets]);
  // The cached plan, not a fetch: this screen has to render offline like the rest.
  const analysis = useMemo(() => {
    if (sets === null) return null; // Also keeps localStorage out of the prerender.
    const plan = cachedPlan();
    return plan === null ? null : analyse(sets, plan, localDay());
  }, [sets]);
  const strength = useMemo(() => (sets === null ? [] : trends(sets)), [sets]);
  const measurements = profile ? bmiFromProfile(profile) : null;

  const totals = useMemo(() => {
    if (!days) return null;
    return {
      sessions: days.length,
      sets: days.reduce((n, d) => n + d.sets.length, 0),
    };
  }, [days]);

  return (
    <AppShell width="max-w-2xl">
      <PageHeader
        title="Progress"
        meta={
          totals && totals.sets > 0
            ? `${totals.sets} set${totals.sets === 1 ? "" : "s"} across ${totals.sessions} session${totals.sessions === 1 ? "" : "s"}`
            : undefined
        }
      />

      <Strength trends={strength} units={units} className="mb-10" />

      {analysis && <Analysis data={analysis} units={units} className="mb-10" />}

      {measurements && (
        <BodyMetrics
          bmi={measurements}
          bodyweightKg={profile?.bodyweight_kg == null ? null : Number(profile.bodyweight_kg)}
          units={units}
          className="mb-10"
        />
      )}

      {days !== null && days.length > 0 && <h2 className="label mb-4">Log</h2>}

      {days === null && <RowSkeleton count={4} />}

      {days !== null && days.length === 0 && (
        <EmptyState
          icon={<HistoryIcon />}
          title="Nothing logged yet"
          body="Every set you log lands here — the reps, the load and how close you were to failure — so you can see the numbers move week to week."
          action={
            <Link
              href="/today"
              className="inline-flex items-center justify-center rounded-control bg-accent px-5 font-display text-[1.125rem] font-extrabold tracking-[0.06em] text-accent-ink uppercase"
              style={{ minHeight: "var(--tap)" }}
            >
              Go to today
            </Link>
          }
        />
      )}

      {days?.slice(0, older ? undefined : RECENT).map((entry) => (
        <section key={entry.day} className="mb-8">
          <div className="mb-2.5 flex items-baseline justify-between gap-3">
            <h2 className="label">
              {label(entry.day)}
            </h2>
            <span className="text-2xs text-ink-faint">
              {entry.sets.length} set{entry.sets.length === 1 ? "" : "s"}
              {entry.unsynced > 0 && ` · ${entry.unsynced} not yet sent`}
            </span>
          </div>

          <div className="space-y-2">
            {entry.byExercise.map((group) => (
              <article key={group.name} className="rounded-card bg-surface px-4 py-3">
                <h3 className="text-[0.9375rem] text-ink capitalize">{group.name}</h3>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {group.sets.map((set) => (
                    <li
                      key={set.id}
                      className="rounded-full bg-raised px-2.5 py-1 text-[0.8125rem] text-ink-muted"
                      title={`RIR ${set.rir}`}
                    >
                      {set.reps}
                      {set.load ? ` × ${displayLoad(set.load, units)}` : " reps"}
                      <span className="text-ink-faint"> · RIR {set.rir}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-2xs text-ink-faint">
                  {volume(group.sets, units)}
                </p>
              </article>
            ))}
          </div>
        </section>
      ))}
      {days !== null && days.length > RECENT && (
        <Button variant="ghost" full compact onClick={() => setOlder(!older)}>
          {older ? "Show fewer" : `Show ${days.length - RECENT} older sessions`}
        </Button>
      )}
    </AppShell>
  );
}

/** Sets → days → exercises, preserving the newest-first order loggedSets returns. */
function group(sets: LoggedSet[]): Day[] {
  const names = nameLookup();
  const byDay = new Map<string, LoggedSet[]>();
  for (const set of sets) {
    byDay.set(set.day, [...(byDay.get(set.day) ?? []), set]);
  }

  return [...byDay.entries()].map(([day, daySets]) => {
    const byExercise = new Map<string, LoggedSet[]>();
    for (const set of daySets) {
      const name = readable(set.slug ?? names.get(set.exerciseId) ?? null);
      byExercise.set(name, [...(byExercise.get(name) ?? []), set]);
    }
    return {
      day,
      sets: daySets,
      // Sets within an exercise read oldest-first, the order they were performed.
      byExercise: [...byExercise.entries()].map(([name, s]) => ({
        name,
        sets: [...s].reverse(),
      })),
      unsynced: daySets.filter((s) => !s.synced).length,
    };
  });
}

/** Older events predate the slug on the payload; the cached plan covers most of them. */
function nameLookup(): Map<string, string> {
  const lookup = new Map<string, string>();
  for (const session of cachedPlan()?.sessions ?? []) {
    for (const item of session.items) lookup.set(item.exercise_id, item.slug);
  }
  return lookup;
}

const readable = (slug: string | null): string =>
  slug === null ? "Unnamed exercise" : slug.replaceAll("_", " ");

/** Sets × reps, and tonnage where there was a load to multiply by. */
function volume(sets: LoggedSet[], units: Units): string {
  const reps = sets.reduce((n, s) => n + s.reps, 0);
  const loaded = sets.filter((s) => s.load !== null);
  if (loaded.length === 0) return `${sets.length} sets · ${reps} reps`;
  const kg = loaded.reduce((n, s) => n + Number(s.load) * s.reps, 0);
  return `${sets.length} sets · ${reps} reps · ${displayLoad(kg, units)} total`;
}

function label(day: string): string {
  if (day === localDay()) return "Today";
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (day === localDay(yesterday)) return "Yesterday";
  return (
    fromDay(day)?.toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "short",
    }) ?? day
  );
}
