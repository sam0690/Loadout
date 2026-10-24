"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { token } from "@/lib/api/client";

/**
 * The redirect. Signed in goes to the plan, everyone else to onboarding.
 *
 * This used to render the literal string "…", which meant every cold start — including
 * every launch from the home screen — began with a flash of a black screen and one
 * grey ellipsis. The wordmark below occupies the same moment and says what is opening.
 */
export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace(token() ? "/plan" : "/onboarding");
  }, [router]);

  return (
    <main className="flex min-h-dvh items-center justify-center">
      <p className="text-lg font-semibold tracking-[-0.01em] text-ink-faint motion-safe:animate-pulse">
        Loadout
      </p>
    </main>
  );
}
