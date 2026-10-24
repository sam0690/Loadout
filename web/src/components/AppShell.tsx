"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "./ui/cn";
import { SyncBadge } from "./Sync";
import { HistoryIcon, PlanIcon, SettingsIcon } from "./ui/icons";

/**
 * The application frame. One nav, two layouts.
 *
 * Bottom bar on a phone, because the top of a phone is out of thumb reach one-handed
 * and this app is used one-handed. A left rail from `md`, because a 448px column
 * stranded in the middle of a laptop screen — which is what the whole app was before
 * this — is not a design, it is an unconsidered default.
 *
 * The logger deliberately does not use this. It is a focused task surface: no tab bar
 * competing with the primary control, and a single back affordance out.
 */
const TABS = [
  { href: "/plan", label: "Plan", Icon: PlanIcon },
  { href: "/history", label: "History", Icon: HistoryIcon },
  { href: "/settings", label: "Settings", Icon: SettingsIcon },
] as const;

export function AppShell({
  children,
  width = "max-w-2xl",
}: {
  children: ReactNode;
  width?: string;
}) {
  const path = usePathname();
  const isActive = (href: string) => path.startsWith(href);

  return (
    <div className="md:flex md:min-h-dvh">
      {/* --- Desktop rail. The wrapper carries the background so it runs the full height
          of a long page; only the nav inside it sticks. */}
      <div className="hidden w-56 shrink-0 border-r border-line bg-chrome md:block">
        <nav
          aria-label="Main"
          className="sticky top-0 flex h-dvh flex-col px-3 py-6"
        >
          <span className="px-3 pb-6 text-[0.9375rem] font-semibold tracking-[-0.01em] text-ink">
            Loadout
          </span>
          <ul className="flex flex-col gap-1">
            {TABS.map(({ href, label, Icon }) => (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={isActive(href) ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-control px-3 py-2.5 text-[0.9375rem]",
                    "transition-colors duration-150 ease-out-soft",
                    isActive(href)
                      ? "bg-surface text-ink"
                      : "text-ink-faint hover:bg-surface hover:text-ink-muted",
                  )}
                >
                  <Icon
                    className={cn("size-5", isActive(href) ? "text-accent" : undefined)}
                  />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
          <SyncBadge className="mt-auto px-3" />
        </nav>
      </div>

      {/* --- Content. pb clears the mobile tab bar; md drops it. */}
      <div className="min-w-0 flex-1">
        <div className={cn("mx-auto w-full px-5 pb-28 md:px-8 md:pb-10", width)}>
          {children}
        </div>
      </div>

      {/* --- Mobile tab bar */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-chrome/95 backdrop-blur-sm md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <ul className="mx-auto flex max-w-md">
          {TABS.map(({ href, label, Icon }) => (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-current={isActive(href) ? "page" : undefined}
                className={cn(
                  "flex flex-col items-center justify-center gap-1 py-2.5",
                  "transition-colors duration-150 ease-out-soft",
                  isActive(href) ? "text-ink" : "text-ink-faint",
                )}
                style={{ minHeight: "var(--tap)" }}
              >
                <Icon className={cn("size-5", isActive(href) && "text-accent")} />
                <span className="text-2xs">{label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

/**
 * Page header. Title, an optional line under it, and room for one action.
 * Consistent across every screen, which is why it lives here rather than in each page.
 */
export function PageHeader({
  title,
  meta,
  action,
}: {
  title: string;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-4 pt-8 pb-6">
      <div className="min-w-0">
        <h1 className="text-[1.5rem] leading-tight font-semibold tracking-[-0.02em] text-ink">
          {title}
        </h1>
        {meta && <div className="mt-1 text-[0.875rem] text-ink-faint">{meta}</div>}
      </div>
      {action}
    </header>
  );
}
