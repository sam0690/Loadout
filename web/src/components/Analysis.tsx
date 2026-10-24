"use client";

import type { Analysis as Data, MuscleVolume, WeekPoint } from "@/lib/analysis";
import { displayLoad, type Units } from "@/lib/units";
import { fromDay } from "@/lib/day";
import { cn } from "./ui/cn";

/**
 * How the week is going, from what is on this device.
 *
 * Three views, each picked from the job its data does rather than from a chart menu:
 *
 * - **Adherence is one number**, so it is a stat tile with a meter, not a chart. A
 *   two-slice donut of "done vs remaining" would be the same number wearing a costume.
 * - **Volume per muscle is magnitude across unordered categories**, so it is a
 *   horizontal bar list — one hue for every bar. Colouring each bar darker-where-bigger
 *   would double-encode length as hue and spend the only free channel on information
 *   the bar length already carries.
 * - **The trend is one series**, so no legend, and only the endpoint is labelled.
 *
 * Marks are thin, ends are rounded and anchored to a zero baseline, bars are separated
 * by a gap of surface rather than by a border, and the axis is a solid hairline. There
 * are no tooltips: this is a touch device with no hover, so the values are on the rows.
 */
export function Analysis({
  data,
  units,
  className,
}: {
  data: Data;
  units: Units;
  className?: string;
}) {
  if (!data.hasData) return null;

  return (
    <section className={cn("space-y-7", className)} aria-label="Training analysis">
      <h2 className="label">This week</h2>

      <Adherence data={data} />

      {data.muscles.length > 0 && (
        <Figure
          title="Hard sets by muscle"
          note="Sets logged at RIR 3 or less, against what this week's plan asked for."
        >
          <ul className="space-y-2.5">
            {data.muscles.map((m) => (
              <MuscleBar key={m.muscle} volume={m} />
            ))}
          </ul>
        </Figure>
      )}

      <Figure
        title="Hard sets per week"
        note={
          totalTonnage(data.weeks) > 0
            ? `${displayLoad(totalTonnage(data.weeks), units)} moved over these weeks.`
            : "Counted in sets rather than weight, so bodyweight training still registers."
        }
      >
        <Trend weeks={data.weeks} />
      </Figure>
    </section>
  );
}

/** The headline. One number, so it gets the tile and not a plot. */
function Adherence({ data }: { data: Data }) {
  const pct =
    data.prescribed === 0 ? 0 : Math.round((data.done / data.prescribed) * 100);
  return (
    <div className="rounded-card bg-surface px-4 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <p className="flex items-baseline gap-2">
          <span className="font-display text-display font-extrabold text-ink">
            {data.done}
          </span>
          <span className="text-[0.9375rem] text-ink-faint">
            of {data.prescribed} sets this week
          </span>
        </p>
        <span className="font-display text-[1.5rem] font-extrabold text-accent">{pct}%</span>
      </div>

      <Meter value={data.done} max={data.prescribed} className="mt-3" />

      <p className="mt-2.5 text-2xs text-ink-faint">
        {data.sessionsTouched} of {data.sessionsPlanned} sessions started.
      </p>
    </div>
  );
}

function MuscleBar({ volume }: { volume: MuscleVolume }) {
  const target = Math.max(volume.prescribed, volume.done, 1);
  return (
    <li className="grid grid-cols-[minmax(5.5rem,7rem)_1fr_auto] items-center gap-3">
      <span className="truncate text-[0.8125rem] text-ink-muted capitalize">
        {volume.muscle.replaceAll("_", " ")}
      </span>
      <Meter value={volume.done} max={target} />
      <span className="font-display text-[0.9375rem] font-semibold text-ink-faint">
        {volume.done}/{volume.prescribed}
      </span>
    </li>
  );
}

/**
 * A track and a fill: one measure against its reference. Rounded ends, anchored at
 * zero, and the track is a surface step rather than an outline.
 */
function Meter({
  value,
  max,
  className,
}: {
  value: number;
  max: number;
  className?: string;
}) {
  const pct = max === 0 ? 0 : Math.min(100, (value / max) * 100);
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-raised", className)}
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
    >
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out-soft"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/**
 * Six weeks, one series. The current week is the emphasised mark and the only one
 * carrying a value — a number over every column is chaos that goes unread.
 */
function Trend({ weeks }: { weeks: WeekPoint[] }) {
  const peak = Math.max(1, ...weeks.map((w) => w.hardSets));
  return (
    <div>
      <ul className="flex h-24 items-end gap-2" role="list">
        {weeks.map((week, i) => {
          const current = i === weeks.length - 1;
          const height = (week.hardSets / peak) * 100;
          return (
            <li
              key={week.weekStart}
              className="flex h-full flex-1 flex-col justify-end gap-1.5"
              title={`Week of ${label(week.weekStart)}: ${week.hardSets} hard sets`}
            >
              {current && week.hardSets > 0 && (
                <span className="text-center text-2xs text-ink-muted tabular-nums">
                  {week.hardSets}
                </span>
              )}
              <div
                className={cn(
                  "w-full rounded-t-[4px]",
                  current ? "bg-accent" : "bg-line-strong",
                )}
                // A zero week keeps a visible sliver, so a gap reads as "nothing
                // logged" rather than as a week that is missing from the chart.
                style={{ height: `${Math.max(height, week.hardSets > 0 ? 4 : 2)}%` }}
              />
            </li>
          );
        })}
      </ul>

      {/* Solid hairline, never dashed: a dashed rule reads as a threshold. */}
      <div className="mt-1.5 h-px w-full bg-line" />

      <ul className="mt-1.5 flex gap-2" aria-hidden="true">
        {weeks.map((week, i) => (
          <li
            key={week.weekStart}
            className={cn(
              "flex-1 text-center text-2xs",
              i === weeks.length - 1 ? "text-ink-muted" : "text-ink-faint",
            )}
          >
            {label(week.weekStart)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Figure({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="rounded-card bg-surface px-4 py-4">
      <figcaption className="mb-3.5">
        <p className="font-display text-[1.25rem] leading-tight font-extrabold text-ink uppercase">
          {title}
        </p>
        <p className="mt-0.5 text-2xs leading-relaxed text-ink-faint">{note}</p>
      </figcaption>
      {children}
    </figure>
  );
}

const totalTonnage = (weeks: WeekPoint[]): number =>
  weeks.reduce((n, w) => n + w.tonnageKg, 0);

const label = (day: string): string =>
  fromDay(day)?.toLocaleDateString(undefined, { day: "numeric", month: "short" }) ?? day;
