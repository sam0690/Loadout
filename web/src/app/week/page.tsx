"use client";

import { usePlan } from "@/lib/usePlan";
import { Coverage } from "@/components/Coverage";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { OfflineIcon } from "@/components/ui/icons";
import {
  ContextSwitcher,
  PlanStates,
  SessionCard,
  formatDay,
} from "@/components/Session";

/** Shared empty map, so a session with no logging does not remount its rows. */
const EMPTY: ReadonlyMap<string, number> = new Map();

/**
 * The whole week, for planning around it. Doing today's session lives on Today, and
 * the numbers about it on Progress -- this page used to carry all three.
 */
export default function Week() {
  const plan = usePlan();
  const { load, payload, active, generating } = plan;

  return (
    <AppShell width="max-w-3xl">
      <PageHeader
        title="This week"
        meta={
          load.kind === "offline" ? (
            <span className="inline-flex items-center gap-1.5 text-ink-faint">
              <OfflineIcon className="size-3.5" />
              Showing what is on this device
            </span>
          ) : load.kind === "ready" && load.weekOf ? (
            `From ${formatDay(load.weekOf, { day: "numeric", month: "long" })}`
          ) : undefined
        }
        action={
          payload ? (
            <Button
              compact
              loading={generating}
              onClick={() => active && void plan.regenerate(active)}
              disabled={!active}
            >
              Regenerate
            </Button>
          ) : undefined
        }
      />

      <ContextSwitcher
        contexts={plan.contexts}
        active={active}
        disabled={generating}
        onSwitch={plan.switchTo}
        className="mb-6"
      />

      {payload?.unreachable && payload.unreachable.length > 0 && (
        <Coverage unreachable={payload.unreachable} className="mb-6" />
      )}

      {plan.error && (
        <p role="alert" className="mb-6 text-[0.875rem] text-danger">
          {plan.error}
        </p>
      )}

      <PlanStates
        load={load}
        canGenerate={active !== null}
        generating={generating}
        onGenerate={() => active && void plan.regenerate(active)}
      />

      {payload && (
        <div className="space-y-8 md:grid md:grid-cols-2 md:gap-6 md:space-y-0">
          {payload.sessions.map((session) => (
            <SessionCard
              key={session.day}
              session={session}
              today={plan.today}
              done={plan.done.get(session.day) ?? EMPTY}
            />
          ))}
        </div>
      )}
    </AppShell>
  );
}
