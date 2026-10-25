import Link from "next/link";
import { SettingsIcon } from "./ui/icons";

/** First letters of the first two words of the name, else the email's first letter. */
export function initials(name: string | null | undefined, email: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length > 0) return words.slice(0, 2).map((w) => w[0]!).join("").toUpperCase();
  return (email?.[0] ?? "?").toUpperCase();
}

/**
 * Who you are and what you have done, above the numbers that prove it. The gear is the
 * only way into Settings: Settings is visited rarely, so it does not get a tab of its own.
 */
export function ProfileHeader({
  name,
  email,
  since,
  stats,
}: {
  name: string | null | undefined;
  email: string | null | undefined;
  since: string | null | undefined;
  stats: { label: string; value: number }[] | null;
}) {
  const joined = since
    ? new Date(since).toLocaleDateString(undefined, { month: "short", year: "numeric" })
    : null;

  return (
    <header className="pt-8 pb-8">
      <div className="flex items-center gap-4">
        <span
          aria-hidden="true"
          className="flex size-16 shrink-0 items-center justify-center rounded-full bg-raised font-display text-[1.75rem] font-extrabold text-accent ring-2 ring-accent"
        >
          {initials(name, email)}
        </span>
        <div className="min-w-0 flex-1">
          {/* An address is too long for the display face; its local part stands in. */}
          <h1 className="truncate text-display text-ink">
            {name || email?.split("@")[0] || "Profile"}
          </h1>
          <p className="mt-1 truncate text-[0.875rem] text-ink-faint">{email}</p>
          {joined && <p className="text-2xs text-ink-faint">Since {joined}</p>}
        </div>
        <Link
          href="/profile/settings"
          aria-label="Settings"
          className="-mr-3 flex shrink-0 items-center justify-center rounded-control text-ink-muted transition-colors duration-150 ease-out-soft hover:text-ink"
          style={{ minWidth: "var(--tap)", minHeight: "var(--tap)" }}
        >
          <SettingsIcon className="size-6" />
        </Link>
      </div>

      {stats && (
        <dl className="mt-6 grid grid-cols-3 gap-2">
          {stats.map((s) => (
            <div key={s.label} className="rounded-card bg-surface px-3 py-3">
              <dd className="font-display text-[2rem] leading-none font-extrabold text-ink tabular-nums">
                {s.value}
              </dd>
              <dt className="label mt-1.5">{s.label}</dt>
            </div>
          ))}
        </dl>
      )}
    </header>
  );
}
