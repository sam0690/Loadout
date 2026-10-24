"use client";

import { useState } from "react";
import type { ProfilePatch } from "@/lib/api/client";
import {
  cmToFtIn,
  ftInToCm,
  kgToLb,
  lbToKg,
  readUnits,
  writeUnits,
  type Units,
} from "@/lib/units";
import { Field } from "../ui/Field";
import { SegmentedControl } from "../ui/SegmentedControl";

/**
 * Year of birth, height and bodyweight.
 *
 * Worth being straight about: nothing in `engine/` reads these yet (D29). They are
 * collected ahead of their consumers, and the copy below says so rather than implying
 * a personalisation that is not happening. Bodyweight is the one with a consumer
 * waiting — press-ups, pull-ups and dips currently carry no load at all, so e1RM and
 * load progression silently do not apply to them.
 *
 * Framed as measurements, never as targets. There is no goal weight and no body-fat
 * field here, because this app prescribes training and has no business pointing anyone
 * at a number on a scale.
 */
interface Props {
  value: ProfilePatch;
  onChange: (patch: ProfilePatch) => void;
}

const THIS_YEAR = new Date().getFullYear();

export function ProfileFields({ value, onChange }: Props) {
  const [units, setUnits] = useState<Units>(readUnits);

  const changeUnits = (next: Units) => {
    setUnits(next);
    writeUnits(next);
  };

  const heightCm = value.height_cm ?? null;
  const weightKg = value.bodyweight_kg == null ? null : Number(value.bodyweight_kg);

  return (
    <div className="space-y-5">
      <SegmentedControl
        label="Units"
        value={units}
        onChange={changeUnits}
        options={[
          { value: "metric", label: "kg · cm" },
          { value: "imperial", label: "lb · ft" },
        ]}
      />

      <Field
        label="Year of birth"
        type="number"
        inputMode="numeric"
        placeholder={String(THIS_YEAR - 30)}
        value={value.birth_year ?? ""}
        min={1900}
        max={THIS_YEAR}
        error={
          value.birth_year != null && (value.birth_year < 1900 || value.birth_year > THIS_YEAR)
            ? `Use a year between 1900 and ${THIS_YEAR}.`
            : null
        }
        onChange={(e) =>
          onChange({ birth_year: e.target.value === "" ? null : Number(e.target.value) })
        }
      />

      {units === "metric" ? (
        <Field
          label="Height"
          type="number"
          inputMode="numeric"
          unit="cm"
          placeholder="178"
          value={heightCm ?? ""}
          min={50}
          max={280}
          error={heightCm !== null && (heightCm < 50 || heightCm > 280)
            ? "Use a height between 50 and 280 cm."
            : null}
          onChange={(e) =>
            onChange({ height_cm: e.target.value === "" ? null : Number(e.target.value) })
          }
        />
      ) : (
        <FeetAndInches
          cm={heightCm}
          onChange={(next) => onChange({ height_cm: next })}
        />
      )}

      <Field
        label="Bodyweight"
        type="number"
        inputMode="decimal"
        unit={units === "metric" ? "kg" : "lb"}
        placeholder={units === "metric" ? "80" : "176"}
        value={
          weightKg === null ? "" : units === "metric" ? weightKg : kgToLb(weightKg)
        }
        step={units === "metric" ? 0.5 : 1}
        hint="Used to work out loads for press-ups, pull-ups and dips."
        onChange={(e) => {
          if (e.target.value === "") return onChange({ bodyweight_kg: null });
          const entered = Number(e.target.value);
          onChange({
            bodyweight_kg: units === "metric" ? entered : lbToKg(entered),
          });
        }}
      />
    </div>
  );
}

/** Two boxes, because nobody knows their height as a decimal number of feet. */
function FeetAndInches({
  cm,
  onChange,
}: {
  cm: number | null;
  onChange: (cm: number | null) => void;
}) {
  const parts = cm === null ? { ft: "", in: "" } : cmToFtIn(cm);

  const update = (ft: string | number, inches: string | number) => {
    if (ft === "" && inches === "") return onChange(null);
    onChange(ftInToCm(Number(ft) || 0, Number(inches) || 0));
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      <Field
        label="Height"
        type="number"
        inputMode="numeric"
        unit="ft"
        placeholder="5"
        value={parts.ft}
        min={1}
        max={8}
        onChange={(e) => update(e.target.value, parts.in)}
      />
      <Field
        label="&nbsp;"
        type="number"
        inputMode="numeric"
        unit="in"
        placeholder="10"
        value={parts.in}
        min={0}
        max={11}
        onChange={(e) => update(parts.ft, e.target.value)}
      />
    </div>
  );
}
