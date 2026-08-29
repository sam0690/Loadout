"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, api, type PlanOut, type PlanPayload } from "@/lib/api/client";
import { Chrome } from "@/components/Chrome";
import { SyncBadge } from "@/components/SyncBadge";

/**
 * This week's sessions.
 *
 * The plan is cached in localStorage the moment it arrives, because the logger has to
 * open with no network — including the substitution set for every exercise, which is
 * resolved at generation precisely so the swap works offline (§6).
 */
export default function PlanView() {
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const cache = useCallback((fetched: PlanOut) => {
    setPlan(fetched);
    window.localStorage.setItem("loadout.plan", JSON.stringify(fetched.payload));
  }, []);

  useEffect(() => {
    api
      .currentPlan()
      .then(cache)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) {
          setStatus("No plan yet.");
          // Fall back to whatever this device already had, so a dead network shows the
          // last plan rather than an empty screen.
          const cached = window.localStorage.getItem("loadout.plan");
          if (cached)
            setPlan({
              id: "",
              training_context_id: "",
              week_of: "",
              engine_version: "",
              payload: JSON.parse(cached),
            } as PlanOut);
        } else {
          setStatus("Offline — showing what is on this device.");
        }
      });
  }, [cache]);

  async function generate() {
    setStatus("Generating…");
    const contexts = await api.listContexts();
    const context = contexts.find((c) => c.is_default) ?? contexts[0];
    if (!context) {
      setStatus("Set up your equipment first.");
      return;
    }
    const monday = new Date();
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    const days = [0, 2, 4].map((offset) => {
      const day = new Date(monday);
      day.setDate(monday.getDate() + offset);
      return day.toISOString().slice(0, 10);
    });

    const { job_id } = await api.requestPlan({
      training_context_id: context.id,
      days,
      time_budget_minutes: 60,
      experience: "intermediate",
      goal: "hypertrophy",
    });

    // Poll, per §6: generation is queued and the client waits rather than blocking a
    // request for it.
    for (let attempt = 0; attempt < 30; attempt++) {
      const job = await api.job(job_id);
      if (job.status === "finished") {
        cache(await api.currentPlan());
        setStatus(null);
        return;
      }
      if (job.status === "failed") {
        setStatus("Generation failed.");
        return;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    setStatus("Still generating — pull down in a moment.");
  }

  const payload = plan?.payload as PlanPayload | undefined;

  return (
    <Chrome>
      <main className="space-y-6 p-6">
        <header>
          <h1 className="text-2xl font-semibold">This week</h1>
          {plan?.week_of && (
            <p className="text-sm text-white/40">from {plan.week_of}</p>
          )}
        </header>

        {status && <p className="text-white/50">{status}</p>}

        {payload?.sessions.map((session) => (
          <section key={session.day} className="space-y-2">
            <h2 className="text-sm uppercase tracking-wide text-white/40">
              {new Date(session.day).toLocaleDateString(undefined, { weekday: "long" })}
            </h2>
            {session.items.map((item) => (
              <Link
                key={item.exercise_id}
                href={`/log/${item.exercise_id}`}
                className="flex items-center justify-between rounded-2xl bg-white/5 px-4 py-4 active:bg-white/10"
              >
                <span className="capitalize">{item.slug.replaceAll("_", " ")}</span>
                <span className="text-white/40">
                  {item.sets}×{item.target_reps}
                </span>
              </Link>
            ))}
          </section>
        ))}

        <button
          onClick={generate}
          className="w-full rounded-2xl border border-white/15 text-white/70"
        >
          {payload ? "Regenerate" : "Generate a plan"}
        </button>
      </main>
      <SyncBadge />
    </Chrome>
  );
}
