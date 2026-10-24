"use client";

import type { Experience, Goal, ProfilePatch } from "@/lib/api/client";
import { SegmentedControl } from "../ui/SegmentedControl";

/**
 * The four answers the engine actually consumes.
 *
 * Every one of these was a constant hardcoded in the plan screen — goal, experience,
 * a fixed 60 minutes and a fixed Mon/Wed/Fri — while the API had accepted all four
 * from the start. The detail line under each option says what it changes, because a
 * question whose effect is invisible is a question not worth asking.
 */
interface Props {
  value: ProfilePatch;
  onChange: (patch: ProfilePatch) => void;
}

const GOALS: readonly { value: Goal; label: string; detail: string }[] = [
  {
    value: "hypertrophy",
    label: "Build muscle",
    detail: "Sets of around 10, more total volume",
  },
  {
    value: "strength",
    label: "Get stronger",
    detail: "Sets of around 5, heavier loads",
  },
];

const EXPERIENCE: readonly { value: Experience; label: string; detail: string }[] = [
  { value: "beginner", label: "New to lifting", detail: "Under a year of training" },
  { value: "intermediate", label: "Experienced", detail: "A year or more, consistently" },
  { value: "advanced", label: "Advanced", detail: "Years in, near your ceiling" },
];

const DAYS = [2, 3, 4, 5, 6] as const;
const LENGTHS = [30, 45, 60, 75, 90] as const;

export function TrainingFields({ value, onChange }: Props) {
  return (
    <div className="space-y-7">
      <SegmentedControl
        label="What are you training for?"
        value={value.goal ?? null}
        options={GOALS}
        onChange={(goal) => onChange({ goal })}
        stacked
      />

      <div className="space-y-2.5">
        <p className="text-[0.8125rem] text-ink-muted">How long have you been lifting?</p>
        <SegmentedControl
          label="Experience"
          value={value.experience ?? null}
          options={EXPERIENCE}
          onChange={(experience) => onChange({ experience })}
          stacked
        />
        <p className="text-2xs text-ink-faint">
          Sets your weekly volume. More experience means more work before recovery
          becomes the limit.
        </p>
      </div>

      <div className="space-y-2.5">
        <p className="text-[0.8125rem] text-ink-muted">Sessions a week</p>
        <SegmentedControl
          label="Sessions a week"
          value={value.days_per_week == null ? null : String(value.days_per_week)}
          options={DAYS.map((d) => ({ value: String(d), label: String(d) }))}
          onChange={(days) => onChange({ days_per_week: Number(days) })}
        />
      </div>

      <div className="space-y-2.5">
        <p className="text-[0.8125rem] text-ink-muted">Time per session</p>
        <SegmentedControl
          label="Time per session"
          value={value.session_minutes == null ? null : String(value.session_minutes)}
          options={LENGTHS.map((m) => ({ value: String(m), label: `${m}m` }))}
          onChange={(minutes) => onChange({ session_minutes: Number(minutes) })}
        />
        <p className="text-2xs text-ink-faint">
          Caps how many sets fit in a session. Shorter sessions get the highest-value
          work first.
        </p>
      </div>
    </div>
  );
}
