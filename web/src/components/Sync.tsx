"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { pending } from "@/lib/queue";
import { keepSynced } from "@/lib/sync";
import { OfflineIcon } from "./ui/icons";

/**
 * One sync engine for the whole app.
 *
 * It used to live inside SyncBadge, which meant the reconnect listener was torn down
 * and rebuilt on every navigation — and never ran at all on a screen that forgot to
 * render the badge. Mounted once at the root, it runs everywhere, including the logger,
 * which is the screen that actually generates the events.
 */
const REFRESH_MS = 3000;

const PendingContext = createContext(0);

export function usePending() {
  return useContext(PendingContext);
}

export function SyncProvider({ children }: { children: React.ReactNode }) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const refresh = () => void pending().then((q) => setCount(q.length));
    refresh();
    const stop = keepSynced(async (events) => {
      const result = await api.postEvents(events);
      refresh();
      return result;
    }, REFRESH_MS);
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      stop();
      clearInterval(timer);
    };
  }, []);

  return <PendingContext.Provider value={count}>{children}</PendingContext.Provider>;
}

/**
 * How many sets are still only on this phone.
 *
 * Deliberately not an error state and deliberately not red: offline is the normal case
 * in a gym basement, so this reads as a count of things still to send rather than as
 * something being wrong.
 */
export function SyncBadge({ className }: { className?: string }) {
  const count = usePending();
  if (count === 0) return null;
  return (
    <p
      className={className}
      title={`${count} event${count === 1 ? "" : "s"} queued on this device`}
    >
      <span className="inline-flex items-center gap-1.5 rounded-full bg-surface px-2.5 py-1 text-2xs text-ink-faint">
        <OfflineIcon className="size-3.5" />
        {count} waiting
      </span>
    </p>
  );
}
