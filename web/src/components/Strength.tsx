"use client";

import { useState } from "react";
import type { Trend } from "@/lib/progress";
import { displayLoad, type Units } from "@/lib/units";
import { formatDay } from "./Session";
import { Button } from "./ui/Button";
import { cn } from "./ui/cn";

const SHOWN = 6;

/**
 * Is it working? One card per exercise: the best so far at scoreboard size, the change
 * since the first session, and the line between them.
 *
 * Sparklines, not axes: each card answers "up or down, and by how much", and the number
 * beside the line carries the magnitude. A labelled axis per exercise would be six
 * charts' worth of ticks nobody reads on a phone.
 */
export function Strength({
  trends,
  units,
  className,
}: {
  trends: Trend[];
  units: Units;
  className?: string;
}) {
  const [all, setAll] = useState(false);
  if (trends.length === 0) return null;
  const shown = all ? trends : trends.slice(0, SHOWN);

  return (
    <section className={className} aria-label="Strength">
      <h2 className="label mb-3">Strength</h2>
      <ul className="space-y-2">
        {shown.map((t) => (
          <Card key={t.exerciseId} trend={t} units={units} />
        ))}
      </ul>
      {trends.length > SHOWN && (
        <Button variant="ghost" full compact className="mt-2" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${trends.length}`}
        </Button>
      )}
    </section>
  );
}

function Card({ trend, units }: { trend: Trend; units: Units }) {
  const fmt = (v: number) =>
    trend.kind === "e1rm" ? displayLoad(Math.round(v * 2) / 2, units)! : `${v} reps`;
  const up = trend.change > 0;
  const single = trend.points.length === 1;

  return (
    <li className="rounded-card bg-surface px-4 py-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="truncate text-[0.9375rem] font-medium text-ink capitalize">{trend.name}</p>
        <p
          className={cn(
            "shrink-0 font-display text-[1.0625rem] font-semibold",
            up ? "text-accent" : "text-ink-faint",
          )}
        >
          {single
            ? `Since ${formatDay(trend.points[0]!.day, { day: "numeric", month: "short" })}`
            : trend.change === 0
              ? "Holding"
              : `${up ? "▲" : "▼"} ${fmt(Math.abs(trend.change))}`}
        </p>
      </div>
      <div className="mt-2 flex items-end justify-between gap-4">
        <p>
          <span className="font-display text-[2rem] leading-none font-extrabold text-ink">
            {fmt(trend.record.value)}
          </span>
          <span className="label ml-2 whitespace-nowrap">
            {trend.kind === "e1rm" ? "est. 1RM" : "best set"}
          </span>
        </p>
        {!single && <Sparkline values={trend.points.map((p) => p.value)} up={up} />}
      </div>
    </li>
  );
}

/** One series, no axes. The latest point is the only marked one. */
function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const y = (v: number) => 90 - ((v - lo) / span) * 80; // 10% headroom top and bottom
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 100},${y(v)}`).join(" ");

  return (
    <div className="relative h-10 w-28 shrink-0" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="size-full overflow-visible">
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          className={up ? "text-accent" : "text-line-strong"}
        />
      </svg>
      {/* The end marker is HTML, not an SVG circle, so the stretched viewBox cannot
          squash it into an ellipse. */}
      <span
        className={cn(
          "absolute right-0 size-2 translate-x-1/2 -translate-y-1/2 rounded-full",
          up ? "bg-accent" : "bg-ink-muted",
        )}
        style={{ top: `${y(values.at(-1)!)}%` }}
      />
    </div>
  );
}
