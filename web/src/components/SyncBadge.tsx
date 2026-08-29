"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { pending } from "@/lib/queue";
import { syncOnReconnect } from "@/lib/sync";

/**
 * How many sets are still only on this phone.
 *
 * Deliberately not an error state: offline is the normal case in a gym basement, so this
 * reads as a count of things still to send rather than as something being wrong.
 */
export function SyncBadge() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const refresh = () => void pending().then((q) => setCount(q.length));
    refresh();
    const stop = syncOnReconnect(async (events) => {
      const result = await api.postEvents(events);
      refresh();
      return result;
    });
    const timer = setInterval(refresh, 3000);
    return () => {
      stop();
      clearInterval(timer);
    };
  }, []);

  if (count === 0) return null;
  return (
    <p className="px-6 pb-2 text-xs text-white/40">
      {count} set{count === 1 ? "" : "s"} waiting to sync
    </p>
  );
}
