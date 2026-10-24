"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type ContextOut, type PlanPayload, type Profile } from "./api/client";
import { cachePlan, cachedPlan, generatePlan, type Preferences } from "./plan";
import { resolveContext, setActiveContextId } from "./context";
import { closeSession, loggedSets, sessionOutcome, type Outcome } from "./queue";
import { cachedProfile, refreshProfile } from "./profile";
import { localDay } from "./day";

/**
 * The plan, the contexts it can be built for, and what has been logged against it.
 * Shared by Today and Week, which are two views of one week.
 *
 * Four states that used to share one string variable — loading, empty, error and
 * offline — are four states here, because "No plan yet." rendering above a cached plan
 * is the kind of thing one overloaded `status` produces.
 */
export type Load =
  | { kind: "loading" }
  | { kind: "ready"; payload: PlanPayload; weekOf: string | null }
  | { kind: "offline"; payload: PlanPayload }
  | { kind: "empty" }
  | { kind: "error"; message: string };

const DEFAULTS: Preferences = {
  goal: "hypertrophy",
  experience: "intermediate",
  daysPerWeek: 3,
  sessionMinutes: 60,
};

export function usePlan() {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [contexts, setContexts] = useState<ContextOut[]>([]);
  const [active, setActive] = useState<ContextOut | null>(null);
  // Keyed by plan day, then exercise. A session card must show the sets logged on
  // *its* day -- crediting today's work to every session that lists the same exercise
  // made a past Monday read as done because you trained this morning.
  const [done, setDone] = useState<Map<string, Map<string, number>>>(new Map());
  const [generating, setGenerating] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Cache first so the figure survives a cold start with no network, then refresh.
  const [profile, setProfile] = useState<Profile | null>(cachedProfile);

  const today = localDay();

  // Whatever this device already had, so a dead network shows the last plan rather than
  // an empty screen. With no cache the two failures are genuinely different: a 404 means
  // no plan has ever been generated, anything else means we could not ask.
  const fallBack = useCallback((reason: "missing" | "unreachable") => {
    const cached = cachedPlan();
    if (cached) return setLoad({ kind: "offline", payload: cached });
    setLoad(
      reason === "missing"
        ? { kind: "empty" }
        : { kind: "error", message: "Loadout could not be reached from this device." },
    );
  }, []);

  const refreshDay = useCallback(async () => {
    const byDay = new Map<string, Map<string, number>>();
    for (const set of await loggedSets()) {
      const day = byDay.get(set.day) ?? new Map<string, number>();
      day.set(set.exerciseId, (day.get(set.exerciseId) ?? 0) + 1);
      byDay.set(set.day, day);
    }
    setDone(byDay);
    setOutcome(await sessionOutcome(today));
  }, [today]);

  useEffect(() => {
    void refreshDay();
  }, [refreshDay]);

  useEffect(() => {
    void api
      .currentPlan()
      .then((plan) => {
        const payload = plan.payload as PlanPayload;
        cachePlan(payload);
        setLoad({ kind: "ready", payload, weekOf: plan.week_of || null });
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) fallBack("missing");
        else fallBack("unreachable");
      });
  }, [fallBack]);

  useEffect(() => {
    void refreshProfile().then(setProfile);
  }, []);

  useEffect(() => {
    void api
      .listContexts()
      .then(async (all) => {
        setContexts(all);
        setActive(await resolveContext());
      })
      .catch(() => setContexts([]));
  }, []);

  async function regenerate(context: ContextOut) {
    if (generating) return; // A double tap used to enqueue two generation jobs.
    setGenerating(true);
    setError(null);
    try {
      const prefs = (await refreshProfile()) ?? profile;
      setProfile(prefs);
      const plan = await generatePlan(context.id, {
        goal: prefs?.goal ?? DEFAULTS.goal,
        experience: prefs?.experience ?? DEFAULTS.experience,
        daysPerWeek: prefs?.days_per_week ?? DEFAULTS.daysPerWeek,
        sessionMinutes: prefs?.session_minutes ?? DEFAULTS.sessionMinutes,
      });
      setLoad({
        kind: "ready",
        payload: plan.payload as PlanPayload,
        weekOf: plan.week_of || null,
      });
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : "Could not build a plan. Try again in a moment.",
      );
    } finally {
      setGenerating(false);
    }
  }

  function switchTo(context: ContextOut) {
    setActive(context);
    setActiveContextId(context.id);
    void regenerate(context);
  }

  /** Throws on failure, so the caller decides how to tell the user. */
  async function close(day: string, next: Outcome, sets: number) {
    await closeSession(day, next, sets);
    await refreshDay();
  }

  const payload = load.kind === "ready" || load.kind === "offline" ? load.payload : null;

  return {
    load,
    payload,
    contexts,
    active,
    done,
    generating,
    outcome,
    error,
    profile,
    today,
    regenerate,
    switchTo,
    close,
  };
}
