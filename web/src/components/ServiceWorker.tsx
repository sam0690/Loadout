"use client";

import { useEffect } from "react";

/** Registers the app-shell cache so the app opens with no network. */
export function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // An unregistered worker costs offline cold-start, not correctness: every write
      // still goes to IndexedDB first.
    });
  }, []);
  return null;
}
