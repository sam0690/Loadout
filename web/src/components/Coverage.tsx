import Link from "next/link";
import { cn } from "./ui/cn";

/**
 * What the current kit cannot train, said plainly.
 *
 * Before this the generator quietly returned a plan with no chest work in it and the app
 * showed it like any other week — indistinguishable from a week where chest simply was
 * not scheduled. Naming the gap is the whole point; it is not an error state and is
 * deliberately not styled as one, because for a user training on a floor this is a fact
 * about their room rather than a fault.
 *
 * ponytail: the unlock hints are a hand-written map. Deriving "a pull-up bar would add
 * lats" from the catalog is a query the client cannot run offline — do it properly with
 * an endpoint when there is a second reason to want one.
 */
// Short noun phrases, no internal punctuation: these get joined into one sentence, and
// a hint carrying its own dash clause turns that sentence into rubble.
const UNLOCK: Record<string, string> = {
  lats: "a pull-up bar",
  upper_back: "a table to row under",
  rear_delts: "a resistance band",
  traps: "something heavy to hold",
  forearms: "something to hang from",
  chest: "a chair",
  hamstrings: "a resistance band",
};

export function Coverage({
  unreachable,
  className,
}: {
  unreachable: string[];
  className?: string;
}) {
  if (unreachable.length === 0) return null;

  const readable = unreachable.map((m) => m.replaceAll("_", " "));
  const hints = [
    // filter(Boolean) does not narrow the type; a muscle with no hint is expected.
    ...new Set(
      unreachable
        .map((m) => UNLOCK[m])
        .filter((hint): hint is string => hint !== undefined),
    ),
  ];

  return (
    <section
      className={cn("rounded-card border border-line bg-surface px-4 py-3.5", className)}
      aria-label="Equipment coverage"
    >
      <p className="text-[0.9375rem] text-ink">
        Your kit can&rsquo;t train {list(readable)}.
      </p>
      <p className="mt-1.5 text-[0.8125rem] leading-relaxed text-ink-faint">
        Everything else is covered.{" "}
        {hints.length > 0 && `Add ${list(hints, "or")} to close the gap. `}
        Update{" "}
        <Link
          href="/profile/settings"
          className="underline underline-offset-2 hover:text-ink-muted"
        >
          your training places
        </Link>{" "}
        and regenerate.
      </p>
    </section>
  );
}

/** "a, b and c" — an Oxford-comma-free list, because this is prose, not data. */
function list(items: string[], conjunction = "and"): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} ${conjunction} ${items[items.length - 1]}`;
}
