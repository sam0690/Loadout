"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/plan", label: "Plan" },
  { href: "/history", label: "History" },
];

/** Bottom bar, because the top of a phone is out of thumb reach one-handed. */
export function Chrome({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <>
      <div className="pb-24">{children}</div>
      <nav className="fixed inset-x-0 bottom-0 mx-auto flex max-w-md border-t border-white/10 bg-[#0b0d10]">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex-1 py-5 text-center text-sm ${
              path.startsWith(tab.href) ? "text-white" : "text-white/40"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
