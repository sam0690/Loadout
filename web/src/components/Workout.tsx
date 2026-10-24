"use client";

import { useEffect, useState } from "react";
import type { LoggedSet } from "@/lib/queue";
import type { Item } from "@/lib/workout";
import { displayLoad, type Units } from "@/lib/units";
import { CheckIcon } from "./ui/icons";
import { cn } from "./ui/cn";
import { Thumb } from "./ExerciseMedia";

/**
 * One segment per exercise: done, current, still to come. Tappable, because the order
 * of a session bends to whatever rack is free.
 */
export function SlotBar({
  items,
  doneCount,
  index,
  onSelect,
}: {
  items: Item[];
  doneCount: (id: string) => number;
  index: number;
  onSelect: (i: number) => void;
}) {
  return (
    <ol className="flex gap-1" aria-label="Exercises">
      {items.map((item, i) => {
        const done = doneCount(item.exercise_id) >= item.sets;
        return (
          <li key={`${i}-${item.exercise_id}`} className="flex-1">
            <button
              type="button"
              onClick={() => onSelect(i)}
              // Position only, no name: the swap list's buttons are found by exercise name,
              // and a substitute can also be on today's list.
              aria-label={`Exercise ${i + 1} of ${items.length}`}
              aria-current={i === index ? "step" : undefined}
              // The bar is the visible part; the button keeps a usable hit area.
              className="flex w-full items-center py-2"
              style={{ minHeight: "var(--tap-sm)" }}
            >
              <span
                className={cn(
                  "h-1.5 w-full rounded-full transition-colors duration-300",
                  done ? "bg-accent" : i === index ? "bg-ink" : "bg-raised",
                )}
              />
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** Logged sets as filled rows, the rest as dashed placeholders at the prescription. */
export function SetList({ item, sets, units }: { item: Item; sets: LoggedSet[]; units: Units }) {
  const prescribed = displayLoad(item.load, units);
  const remaining = Math.max(0, item.sets - sets.length);
  return (
    <ol className="space-y-1.5" aria-label="Sets completed">
      {sets.map((set, i) => (
        <li
          key={set.id}
          className="flex items-center gap-3 rounded-control bg-surface px-3.5 py-2.5"
        >
          <CheckIcon className="size-4 shrink-0 text-accent" />
          <span className="w-5 font-display text-[1.125rem] font-semibold text-ink-faint">{i + 1}</span>
          <span className="flex-1 font-display text-[1.125rem] font-semibold text-ink">
            {set.reps} reps{set.load ? ` · ${displayLoad(set.load, units)}` : ""}
          </span>
          <span className="text-[0.875rem] text-ink-faint">RIR {set.rir}</span>
        </li>
      ))}
      {Array.from({ length: remaining }).map((_, i) => (
        <li
          key={`todo-${i}`}
          className="flex items-center gap-3 rounded-control border border-dashed border-line px-3.5 py-2.5 text-ink-faint"
        >
          <span className="size-4 shrink-0" />
          <span className="w-5 font-display text-[1.125rem] font-semibold">{sets.length + i + 1}</span>
          <span className="flex-1 font-display text-[1.125rem] font-semibold">
            {item.target_reps} reps{prescribed ? ` · ${prescribed}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * Time since the last set. Counts up rather than down from a prescribed rest, because
 * the engine does not prescribe one and inventing a number here would be the app
 * pretending to know something it does not.
 */
export function RestTimer({ since }: { since: string }) {
  const [elapsed, setElapsed] = useState(() => secondsSince(since));

  useEffect(() => {
    setElapsed(secondsSince(since));
    const timer = setInterval(() => setElapsed(secondsSince(since)), 1000);
    return () => clearInterval(timer);
  }, [since]);

  return (
    <div className="flex items-baseline justify-between rounded-control bg-surface px-4 py-3" aria-live="off">
      <span className="label">Rest</span>
      <span className="font-display text-[2rem] leading-none font-extrabold text-ink">
        {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
      </span>
    </div>
  );
}

const secondsSince = (iso: string): number =>
  Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));

/**
 * The occupied-machine alternatives, inline rather than in a modal: a dialog needing a
 * precise tap to dismiss is a trap when the user is holding a dumbbell.
 */
export function SwapList({
  item,
  onPick,
}: {
  item: Item;
  onPick: (substitute: Item["substitutes"][number]) => void;
}) {
  return (
    <div className="space-y-2">
      {item.substitutes.map((substitute) => (
        <button
          key={substitute.exercise_id}
          type="button"
          onClick={() => onPick(substitute)}
          className={cn(
            "no-select flex w-full items-center gap-4 rounded-card bg-surface px-4 py-3 text-left capitalize",
            "transition-colors duration-150 ease-out-soft hover:bg-raised active:bg-raised",
          )}
        >
          {/* Seeing the alternative matters most here: the choice is made mid-session. */}
          <Thumb slug={substitute.slug} />
          <span className="min-w-0">
            <span className="block text-[0.9375rem] font-medium text-ink">
              {substitute.slug.replaceAll("_", " ")}
            </span>
            <span className="mt-0.5 block text-[0.8125rem] normal-case text-ink-faint">
              {substitute.equipment.length
                ? substitute.equipment.join(", ").replaceAll("_", " ")
                : "no equipment"}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
