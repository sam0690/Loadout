"use client";

import { useEffect, useState } from "react";
import { db, type QueuedEvent } from "@/lib/db";
import { Chrome } from "@/components/Chrome";

/**
 * Everything logged on this device, newest first.
 *
 * Reads the local queue rather than the server: history has to work offline too, and the
 * queue already holds every set including the ones not yet sent.
 */
export default function History() {
  const [events, setEvents] = useState<QueuedEvent[]>([]);

  useEffect(() => {
    void db.events
      .orderBy("client_ts")
      .reverse()
      .toArray()
      .then((all) => setEvents(all.filter((e) => e.type === "set_logged")));
  }, []);

  const byDay = new Map<string, QueuedEvent[]>();
  for (const event of events) {
    const day = event.client_ts.slice(0, 10);
    byDay.set(day, [...(byDay.get(day) ?? []), event]);
  }

  return (
    <Chrome>
      <main className="space-y-6 p-6">
        <h1 className="text-2xl font-semibold">History</h1>
        {byDay.size === 0 && <p className="text-white/50">Nothing logged yet.</p>}
        {[...byDay.entries()].map(([day, sets]) => (
          <section key={day} className="space-y-1">
            <h2 className="text-sm uppercase tracking-wide text-white/40">{day}</h2>
            <p className="text-white/70">
              {sets.length} set{sets.length === 1 ? "" : "s"}
              {sets.some((s) => s.synced_at === null) && (
                <span className="text-white/30"> · some not yet synced</span>
              )}
            </p>
          </section>
        ))}
      </main>
    </Chrome>
  );
}
